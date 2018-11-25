# Copyright 2015-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Module implementing the processing of incoming email messages.
"""
import asyncore
import email
import logging
import os
from datetime import timedelta
from itertools import chain
from multiprocessing import Pool

from django.conf import settings

import pyinotify

import distro_tracker.mail.control
import distro_tracker.mail.dispatch
from distro_tracker.core.utils import message_from_bytes

logger = logging.getLogger(__name__)


class MailProcessorException(Exception):
    pass


class ConflictingDeliveryAddresses(MailProcessorException):
    """
    The message contained multiple headers with possible delivery addresses
    for the domain defined in settings.DISTRO_TRACKER_FQDN.
    """
    pass


class MissingDeliveryAddress(MailProcessorException):
    """
    The message contained no header with a delivery address for the domain
    defined in settings.DISTRO_TRACKER_FQDN.
    """
    pass


class InvalidDeliveryAddress(MailProcessorException):
    """
    The message contained a delivery address for the domain defined in
    settings.DISTRO_TRACKER_FQDN but it did not match any known Distro Tracker
    service.
    """
    pass


class MailProcessor(object):
    """
    Takes an incoming email and do something useful out of it.

    To this end, it must find out where the email was sent
    and adjust the processing depending on the role of
    the target address.
    """

    def __init__(self, message_or_filename):
        if isinstance(message_or_filename, email.message.Message):
            self.message = message_or_filename
        else:
            self.load_mail_from_file(message_or_filename)

    def load_mail_from_file(self, filename):
        """
        Load the mail to process from a file.

        :param str filename: Path of the file to parse as mail.
        """
        with open(filename, 'rb') as f:
            self.message = message_from_bytes(f.read())

    @staticmethod
    def find_delivery_address(message):
        """
        Identify the email address the message was delivered to.

        The message headers Delivered-To, Envelope-To, X-Original-To, and
        X-Envelope-To are scanned to find out an email that matches the FQDN of
        the Distro Tracker setup.
        """
        addresses = []
        for field in chain(message.get_all('Delivered-To', []),
                           message.get_all('Envelope-To', []),
                           message.get_all('X-Original-To', []),
                           message.get_all('X-Envelope-To', [])):
            if field.endswith('@' + settings.DISTRO_TRACKER_FQDN):
                if field not in addresses:
                    addresses.append(field)
        if len(addresses) > 1:
            raise ConflictingDeliveryAddresses()
        elif len(addresses) == 1:
            return addresses[0]

    @staticmethod
    def identify_service(address):
        """
        Identify service associated to target email and extract optional args.

        The address has the generic form <service>+<details>@<fqdn>.
        """
        local_part = address.split('@', 1)[0]
        if '+' in local_part:
            return local_part.split('+', 1)
        else:
            return (local_part, None)

    @staticmethod
    def do_nothing(self):
        """Just used by unit tests to disable process()"""

    def process(self):
        """
        Process the message stored in self.message.

        Find out the delivery address and identify the associated service.
        Then defer to handle_*() for service-specific processing. Can raise
        MissingDeliveryAddress and UnknownService
        """
        addr = self.find_delivery_address(self.message)
        if addr is None:
            raise MissingDeliveryAddress()
        service, details = self.identify_service(addr)
        if service == 'dispatch':
            package, keyword = (details, None)
            if details and '_' in details:
                package, keyword = details.split('_', 1)
            self.handle_dispatch(package, keyword)
        elif service == 'bounces':
            self.handle_bounces(details)
        elif service == 'control':
            self.handle_control()
        elif service == 'team':
            self.handle_team(details)
        elif settings.DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS:
            package, keyword = (addr.split('@', 1)[0], None)
            if package and '_' in package:
                package, keyword = package.split('_', 1)
            self.handle_dispatch(package, keyword)
        else:
            raise InvalidDeliveryAddress(
                '{} is not a valid Distro Tracker address'.format(addr))

    @staticmethod
    def build_delivery_address(service, details):
        local_part = service
        if details:
            local_part += '+' + details
        return '{}@{}'.format(local_part, settings.DISTRO_TRACKER_FQDN)

    def handle_control(self):
        distro_tracker.mail.control.process(self.message)

    def handle_bounces(self, details):
        sent_to_addr = self.build_delivery_address('bounces', details)
        distro_tracker.mail.dispatch.handle_bounces(sent_to_addr, self.message)

    def handle_dispatch(self, package=None, keyword=None):
        distro_tracker.mail.dispatch.process(self.message, package=package,
                                             keyword=keyword)

    def handle_team(self, team):
        distro_tracker.mail.dispatch.process_for_team(self.message, team)


def run_mail_processor(mail_path, log_failure=False):
    """
    Run a :class:`MailProcessor` on a stored email.

    :param str mail_path: path of the email
    :param bool log_failure: indicates whether to log any failure
    """
    try:
        processor = MailProcessor(mail_path)
        processor.process()
    except Exception:
        if log_failure:
            logger.exception("Failed to process incoming mail %s", mail_path)
        raise


class MailQueue(object):
    """
    A queue of mails to process. The mails are identified by their filename
    within `DISTRO_TRACKER_MAILDIR_DIRECTORY`.
    """

    #: The maximum number of sub-process used to process the mail queue
    MAX_WORKERS = 4

    SLEEP_TIMEOUT_EMPTY = 30.0
    SLEEP_TIMEOUT_TASK_RUNNING = 0.010
    SLEEP_TIMEOUT_TASK_FINISHED = 0.0
    SLEEP_TIMEOUT_TASK_RUNNABLE = 0.0

    def __init__(self):
        self.queue = []
        self.entries = {}
        self.processed_count = 0

    def add(self, identifier):
        """
        Add a new mail in the queue.

        :param str identifiername: Filename identifying the mail.
        """
        if identifier in self.entries:
            return

        entry = MailQueueEntry(self, identifier)
        self.queue.append(entry)
        self.entries[identifier] = entry
        return entry

    def remove(self, identifier):
        """
        Remove a mail from the queue. This does not unlink the file.

        :param str identifier: Filename identifying the mail.
        """
        if identifier not in self.entries:
            return
        self.queue.remove(self.entries[identifier])
        self.entries.pop(identifier)
        self.processed_count += 1

    @staticmethod
    def _get_maildir(subfolder=None):
        if subfolder:
            return os.path.join(settings.DISTRO_TRACKER_MAILDIR_DIRECTORY,
                                subfolder, 'new')
        return os.path.join(settings.DISTRO_TRACKER_MAILDIR_DIRECTORY, 'new')

    @classmethod
    def _get_mail_path(cls, entry, subfolder=None):
        return os.path.join(cls._get_maildir(subfolder), entry)

    def initialize(self):
        """Scan the Maildir and fill the queue with the mails in it."""
        for mail in os.listdir(self._get_maildir()):
            self.add(mail)

    @property
    def pool(self):
        if getattr(self, '_pool', None):
            return self._pool
        self._pool = Pool(self.MAX_WORKERS, maxtasksperchild=100)
        return self._pool

    def close_pool(self):
        """Wait until all worker processes are finished and destroy the pool"""
        if getattr(self, '_pool', None) is None:
            return
        self._pool.close()
        self._pool.join()
        self._pool = None

    def process_queue(self):
        """
        Iterate over messages in the queue and do whateever is appropriate.
        """
        # Work on a snapshot of the queue as it will be modified each time
        # a task is finished
        queue = [item for item in self.queue]
        for entry in queue:
            if not entry.processing_task_started():
                entry.start_processing_task()
            if entry.processing_task_finished():
                entry.handle_processing_task_result()

    def sleep_timeout(self):
        """
        Return the maximum delay we can sleep before we process the queue
        again.
        """
        timeout = 86400.0
        for entry in self.queue:
            next_try_time = entry.get_data('next_try_time')
            if entry.processing_task_finished():
                timeout = min(timeout, self.SLEEP_TIMEOUT_TASK_FINISHED)
            elif entry.processing_task_started():
                timeout = min(timeout, self.SLEEP_TIMEOUT_TASK_RUNNING)
            elif next_try_time is not None:
                wait_time = next_try_time - distro_tracker.core.utils.now()
                timeout = min(timeout, wait_time.total_seconds())
            else:
                timeout = min(timeout, self.SLEEP_TIMEOUT_TASK_RUNNABLE)
        timeout = self.SLEEP_TIMEOUT_EMPTY if not len(self.queue) else timeout
        return timeout

    def process_loop(self, stop_after=None, ready_cb=None):
        """
        Process all messages as they are delivered. Also processes pre-existing
        messages. This method never returns.

        :param int stop_after: Stop the loop after having processed the given
            number of messages. Used mainly by unit tests.
        :param ready_cb: a callback executed after setup of filesystem
            monitoring and initial scan of the mail queue, but before the
            start of the loop.
        """
        watcher = MailQueueWatcher(self)
        watcher.start()
        self.initialize()
        if ready_cb:
            ready_cb()
        while True:
            watcher.process_events(timeout=self.sleep_timeout())
            self.process_queue()
            if stop_after is not None and self.processed_count >= stop_after:
                break


class MailQueueEntry(object):
    """
    An entry in a :py:class:MailQueue.

    Contains the following public attributes:

    .. :py:attr: queue

    The parent :py:class:MailQueue.

    .. :py:attr: identifier

    The entry identifier, it's the name of the file within the directory
    of the MailQueue. Used to uniquely identify the entry in the MailQueue.

    .. :py:attr: path

    The full path to the mail file.
    """

    def __init__(self, queue, identifier):
        self.queue = queue
        self.identifier = identifier
        self.path = os.path.join(self.queue._get_maildir(), self.identifier)
        self.data = {
            'creation_time': distro_tracker.core.utils.now(),
        }

    def set_data(self, key, value):
        self.data[key] = value

    def get_data(self, key):
        return self.data.get(key)

    def move_to_subfolder(self, folder):
        """
        Move an entry from the mailqueue to the given subfolder.
        """
        new_maildir = self.queue._get_maildir(folder)
        if not os.path.exists(new_maildir):
            os.makedirs(new_maildir)
        os.rename(self.path, os.path.join(new_maildir, self.identifier))

    def _processed_cb(self, _):
        """Callback executed when a worker completes successfully"""
        self.queue.remove(self.identifier)
        if os.path.exists(self.path):
            os.unlink(self.path)

    def start_processing_task(self):
        """
        Create a MailProcessor and schedule its execution in the worker pool.
        """
        next_try_time = self.get_data('next_try_time')
        log_failure = self.get_data('log_failure')
        now = distro_tracker.core.utils.now()
        if next_try_time and next_try_time > now:
            return

        result = self.queue.pool.apply_async(run_mail_processor,
                                             (self.path, log_failure),
                                             callback=self._processed_cb)
        self.set_data('task_result', result)

    def processing_task_started(self):
        """
        Returns True when the entry has been fed to workers doing mail
        processing. Returns False otherwise.

        :return: an indication whether the mail processing is on-going.
        :rtype: bool
        """
        return self.get_data('task_result') is not None

    def processing_task_finished(self):
        """
        Returns True when the worker processing the mail has finished its work.
        Returns False otherwise, notably when the entry has not been fed to
        any worker yet.

        :return: an indication whether the mail processing has finished.
        :rtype: bool
        """
        if not self.processing_task_started():
            return False
        return self.get_data('task_result').ready()

    def handle_processing_task_result(self):
        """
        Called with mails that have been pushed to workers but that are
        still in the queue. The task likely failed and we need to handle
        the failure smartly.

        Mails whose task raised an exception derived from
        :py:class:MailProcessorException are directly moved to a "broken"
        subfolder and the corresponding entry is dropped from the queue.

        Mails whose task raised other exceptions are kept around for
        multiple retries and after some time they are moved to a "failed"
        subfolder and the corresponding entry is dropped from the queue.
        """
        task_result = self.get_data('task_result')
        if task_result is None:
            return
        try:
            task_result.get()
            self._processed_cb(task_result)
        except MailProcessorException:
            logger.warning('Failed processing %s', self.identifier)
            self.move_to_subfolder('failed')
            self.queue.remove(self.identifier)
        except Exception:
            if not self.schedule_next_try():
                logger.warning('Failed processing %s (and stop retrying)',
                               self.identifier)
                self.move_to_subfolder('broken')
                self.queue.remove(self.identifier)
            else:
                logger.warning('Failed processing %s (but will retry later)',
                               self.identifier)

    def schedule_next_try(self):
        """
        When the mail processing failed, schedule a new try for later.
        Progressively increase the delay between two tries. After 5 tries,
        refuse to schedule a new try and return False.

        :return: True if a new try has been scheduled, False otherwise.
        """
        count = self.get_data('tries') or 0
        delays = [
            timedelta(seconds=150),
            timedelta(seconds=300),
            timedelta(seconds=600),
            timedelta(seconds=1800),
            timedelta(seconds=3600),
            timedelta(seconds=7200),
        ]

        try:
            delay = delays[count]
        except IndexError:
            return False

        now = distro_tracker.core.utils.now()
        self.set_data('next_try_time', now + delay)
        self.set_data('tries', count + 1)
        self.set_data('task_result', None)
        self.set_data('log_failure', count + 1 == len(delays))

        return True


class MailQueueWatcher(object):
    """Watch a mail queue and add entries as they appear on the filesystem"""

    class EventHandler(pyinotify.ProcessEvent):
        def my_init(self, queue=None):
            self.queue = queue

        def process_IN_CREATE(self, event):
            self.queue.add(event.name)

        def process_IN_MOVED_TO(self, event):
            self.queue.add(event.name)

    def __init__(self, queue):
        self.queue = queue

    def start(self):
        """Start watching the directory of the mail queue."""
        path = self.queue._get_maildir()
        self.wm = pyinotify.WatchManager()
        event_handler = self.EventHandler(queue=self.queue)
        pyinotify.AsyncNotifier(self.wm, event_handler)
        self.wm.add_watch(path, pyinotify.IN_CREATE | pyinotify.IN_MOVED_TO,
                          quiet=False)

    def process_events(self, timeout=0, count=1):
        """
        Process all pending events since last call of the function.

        :param float timeout: Maximum time to wait for an event to happen.
        :param int count: Number of processing loops to do.
        """
        asyncore.loop(timeout=timeout, count=count)
