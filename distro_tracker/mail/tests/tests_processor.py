# -*- coding: utf-8 -*-

# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for :mod:`distro_tracker.mail.processor`.
"""
from __future__ import unicode_literals
from email.message import Message
from datetime import datetime
from datetime import timedelta
import multiprocessing
import os.path
import time

from django.conf import settings
from django.test.utils import override_settings
from django.utils import six
from django.utils.encoding import force_bytes
from django.utils.six.moves import mock
import pyinotify

from distro_tracker.test import TestCase
from distro_tracker.core.utils.email_messages import message_from_bytes
from distro_tracker.mail.processor import MailProcessor
from distro_tracker.mail.processor import MailQueue
from distro_tracker.mail.processor import MailQueueEntry
from distro_tracker.mail.processor import MailQueueWatcher
from distro_tracker.mail.processor import ConflictingDeliveryAddresses
from distro_tracker.mail.processor import InvalidDeliveryAddress
from distro_tracker.mail.processor import MissingDeliveryAddress
from distro_tracker.mail.processor import MailProcessorException


class HelperMixin(object):
    @staticmethod
    def create_mail(filename, subject='A subject', **kwargs):
        with open(filename, 'wb') as msg:
            msg.write(b'Subject: ' + force_bytes(subject) + b'\n\nBody')

    @staticmethod
    def mkdir(directory):
        if not os.path.exists(directory):
            os.makedirs(directory)

    def patch_mail_processor(self, new=mock.DEFAULT):
        process_method = 'distro_tracker.mail.processor.MailProcessor.process'
        patcher = mock.patch(process_method)
        mock_process = patcher.start()
        self.addCleanup(patcher.stop)
        return mock_process

    def patch_methods(self, entry, **kwargs):
        mock_objects = {}
        for method in kwargs:
            patcher = mock.patch.object(entry, method)
            mocked_method = patcher.start()
            if callable(kwargs[method]):
                mocked_method.side_effect = kwargs[method]
            else:
                mocked_method.return_value = kwargs[method]
            mock_objects[method] = mocked_method
            self.addCleanup(patcher.stop)
        return mock_objects

    def patch_now(self):
        """
        Replace distro_tracker.core.utils.now() with a mocked version returning
        self.current_datetime
        """
        def get_datetime(*args, **kwargs):
            return self.current_datetime
        if not hasattr(self, 'current_datetime'):
            self.current_datetime = datetime.now()
        patcher = mock.patch('distro_tracker.core.utils.now')
        now = patcher.start()
        now.side_effect = get_datetime
        self.addCleanup(patcher.stop)


@override_settings(DISTRO_TRACKER_FQDN='tracker.debian.org')
class MailProcessorTest(TestCase, HelperMixin):
    def setUp(self):
        """Create a MailProcessor object"""
        self.msg = Message()
        self.processor = MailProcessor(self.msg)
        self.DOMAIN = settings.DISTRO_TRACKER_FQDN

    def _test_find_addr_with(self, field):
        to_addr = 'foo@{}'.format(self.DOMAIN)
        self.msg.add_header(field, to_addr)
        addr = self.processor.find_delivery_address(self.msg)
        self.assertEqual(to_addr, addr)

    def test_find_addr_with_delivered_to(self):
        """Delivered-To is found and used"""
        self._test_find_addr_with('Delivered-To')

    def test_find_addr_with_envelope_to(self):
        """Envelope-To is found and used"""
        self._test_find_addr_with('Envelope-To')

    def test_find_addr_with_x_original_to(self):
        """X-Original-To is found and used"""
        self._test_find_addr_with('X-Original-To')

    def test_find_addr_with_x_envelope_to(self):
        """X-Envelope-To is found and used"""
        self._test_find_addr_with('X-Envelope-To')

    @override_settings(DISTRO_TRACKER_FQDN='domain.test')
    def test_find_addr_ignores_bad_domain(self):
        """Headers pointing to domain that do not match the FQDN are ignored """
        to_addr = 'foo@{}'.format(self.DOMAIN)
        # Entirely different domain should be ignored
        self.msg.add_header('Envelope-To', to_addr)
        self.msg.add_header('Delivered-To', to_addr)
        # Subdomains should be ignored too
        self.msg.add_header('Delivered-To', 'foo@bar.domain.test')
        addr = self.processor.find_delivery_address(self.msg)
        self.assertIsNone(addr)

    def test_find_addr_with_multiple_field_copies(self):
        """All copies of the same fields are parsed"""
        to_addr = 'foo@{}'.format(self.DOMAIN)
        self.msg.add_header('Delivered-To', 'foo@bar')
        self.msg.add_header('Delivered-To', to_addr)
        self.msg.add_header('Delivered-To', 'foo@baz')
        addr = self.processor.find_delivery_address(self.msg)
        self.assertEqual(to_addr, addr)

    def test_find_addr_conflicting(self):
        """Fails when encountering multiple headers with the same domain"""
        self.msg.add_header('Delivered-To', 'foo@{}'.format(self.DOMAIN))
        self.msg.add_header('Delivered-To', 'bar@{}'.format(self.DOMAIN))
        with self.assertRaises(ConflictingDeliveryAddresses):
            self.processor.find_delivery_address(self.msg)

    def test_find_addr_duplicate_non_conflicting(self):
        """Does not fail when encountering same address in different headers"""
        to_addr = 'foo@{}'.format(self.DOMAIN)
        self.msg.add_header('Delivered-To', to_addr)
        self.msg.add_header('X-Original-To', to_addr)
        addr = self.processor.find_delivery_address(self.msg)
        self.assertEqual(to_addr, addr)

    def test_identify_service_without_details(self):
        """identify_service(foo@bar) returns (foo, None)"""
        (service, details) = self.processor.identify_service('foo@bar')
        self.assertEqual(service, 'foo')
        self.assertIsNone(details)

    def test_identify_service_with_details(self):
        """identify_service(foo+baz@bar) returns (foo, baz)"""
        (service, details) = self.processor.identify_service('foo+baz@bar')
        self.assertEqual(service, 'foo')
        self.assertEqual(details, 'baz')

    def test_identify_service_with_details_with_plus(self):
        """identify_service(foo+baz+baz@bar) returns (foo, baz+baz)"""
        (service, details) = self.processor.identify_service('foo+baz+baz@bar')
        self.assertEqual(service, 'foo')
        self.assertEqual(details, 'baz+baz')

    def _test_process_for_addr(self, local_part, method_name, *args, **kwargs):
        self.msg.add_header('Delivered-To',
                            '{}@{}'.format(local_part, self.DOMAIN))
        with mock.patch.object(self.processor, method_name) as func:
            self.processor.process()
            func.assert_called_once_with(*args, **kwargs)

    def test_process_control(self):
        '''control@ is processed by handle_control()'''
        self._test_process_for_addr('control', 'handle_control')

    def test_process_dispatch(self):
        '''dispatch@ is processed by handle_dispatch(None, None)'''
        self._test_process_for_addr('dispatch', 'handle_dispatch', None, None)

    def test_process_dispatch_with_package(self):
        '''dispatch+foo@ is processed by handle_dispatch(foo, None)'''
        self._test_process_for_addr('dispatch+foo', 'handle_dispatch',
                                    'foo', None)

    def test_process_dispatch_with_package_and_keyword(self):
        '''dispatch+foo_bar@ is processed by handle_dispatch(foo, bar)'''
        self._test_process_for_addr('dispatch+foo_bar', 'handle_dispatch',
                                    'foo', 'bar')

    def test_process_bounces(self):
        '''bounces+foo@ is processed by handle_bounces()'''
        self._test_process_for_addr('bounces+foo', 'handle_bounces', 'foo')

    def test_process_without_delivery_address(self):
        '''process() fails when no delivery address can be identified'''
        with self.assertRaises(MissingDeliveryAddress):
            self.processor.process()

    @override_settings(DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS=False)
    def test_process_unknown_service_fails(self):
        '''process() fails when delivery address is not a known service'''
        self.msg.add_header('Delivered-To', 'unknown@{}'.format(self.DOMAIN))
        with self.assertRaises(InvalidDeliveryAddress):
            self.processor.process()

    @override_settings(DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS=True)
    def test_process_unknown_service_works_as_dispatch(self):
        '''process() fails when delivery address is not a known service'''
        self._test_process_for_addr('unknown', 'handle_dispatch', 'unknown',
                                    None)

    def test_load_mail_from_file(self):
        '''loads the mail to process from a file'''
        mail_path = os.path.join(settings.DISTRO_TRACKER_DATA_PATH, 'a-mail')
        self.create_mail(mail_path, subject='load_mail')

        self.processor.load_mail_from_file(mail_path)

        self.assertEqual(self.processor.message['Subject'], 'load_mail')

    def test_init_with_filename(self):
        '''can create object with filename'''
        mail_path = os.path.join(settings.DISTRO_TRACKER_DATA_PATH, 'a-mail')
        self.create_mail(mail_path, subject='load_mail')

        mail_proc = MailProcessor(mail_path)

        self.assertIsInstance(mail_proc.message, Message)


class QueueHelperMixin(HelperMixin):
    def create_mail(self, filename, **kwargs):
        """
        Creates a mail and stores it in the maildir.
        """
        hardlink_from_tmp = kwargs.get('hardlink_from_tmp', False)
        maildir_new = self.queue._get_maildir()
        self.mkdir(maildir_new)
        tmp_path = path = self.get_mail_path(filename)
        if hardlink_from_tmp:
            maildir_tmp = os.path.join(maildir_new, '..', 'tmp')
            self.mkdir(maildir_tmp)
            tmp_path = os.path.join(maildir_tmp, filename)
        super(QueueHelperMixin, self).create_mail(tmp_path, **kwargs)
        if hardlink_from_tmp:
            os.link(tmp_path, path)
            os.unlink(tmp_path)
        return path

    def get_mail_path(self, filename):
        maildir = self.queue._get_maildir()
        return os.path.join(maildir, filename)

    def add_mails_to_queue(self, *args, **kwargs):
        entries = []
        for entry in args:
            if kwargs.get('create_mail', True):
                self.create_mail(entry)
            entries.append(self.queue.add(entry))
        return entries

    def assertQueueIsEmpty(self):
        self.assertListEqual(self.queue.queue, [])

    def assertNotInQueue(self, entry):
        self.assertNotIn(entry, self.queue.queue)

    def assertInQueue(self, entry):
        self.assertIn(entry, self.queue.queue)


class MailQueueTest(TestCase, QueueHelperMixin):
    def setUp(self):
        self.queue = MailQueue()
        self.queue.MAX_WORKERS = 1

    def test_default_attributes(self):
        """The needed attributes are there"""
        self.assertIsInstance(self.queue.queue, list)
        self.assertIsInstance(self.queue.entries, dict)
        self.assertEqual(self.queue.processed_count, 0)

    def test_add_returns_mail_queue_entry(self):
        identifier = 'a'
        entry = self.queue.add(identifier)
        self.assertIsInstance(entry, MailQueueEntry)
        self.assertEqual(entry.identifier, identifier)

    def test_add_twice(self):
        """Duplicate add() is ignored"""
        self.queue.add('a')
        self.queue.add('a')
        self.assertEqual(len(self.queue.queue), 1)

    def test_remove(self):
        """remove() cancels the effects of add()"""
        self.queue.add('a')
        self.queue.remove('a')
        self.assertQueueIsEmpty()
        self.assertEqual(len(self.queue.entries), 0)

    def test_remove_increases_processed_count(self):
        """remove() counts the number of processed mails"""
        self.queue.add('a')
        self.assertEqual(self.queue.processed_count, 0)
        self.queue.remove('a')
        self.assertEqual(self.queue.processed_count, 1)

    def test_remove_non_existing(self):
        """remove() is a no-op for a non-existing entry"""
        self.queue.remove('a')

    @mock.patch('os.listdir')
    def test_initialize(self, mock_listdir):
        """
        Initialize calls os.listdir() on the Maildir/new and populates
        the queue attribute with it
        """
        mock_listdir.return_value = ['a', 'b', 'c']
        new = os.path.join(settings.DISTRO_TRACKER_MAILDIR_DIRECTORY, 'new')

        self.queue.initialize()

        mock_listdir.assert_called_with(new)
        self.assertListEqual(
            list(map(lambda x: x.identifier, self.queue.queue)),
            mock_listdir.return_value)

    def test_pool_is_multiprocessing_pool(self):
        self.assertIsInstance(self.queue.pool, multiprocessing.pool.Pool)

    def test_pool_is_singleton(self):
        self.assertEqual(self.queue.pool, self.queue.pool)

    def test_close_pool_drops_cached_object(self):
        self.queue.pool
        self.queue.close_pool()
        self.assertIsNone(self.queue._pool)

    def test_close_pool_works_without_pool(self):
        self.queue.close_pool()

    def test_close_pool_really_closes_the_pool(self):
        pool = self.queue.pool
        self.queue.close_pool()
        if six.PY2:
            expected_exception = AssertionError  # assert self._state == RUN
        else:
            expected_exception = ValueError  # Pool not running exception
        with self.assertRaises(expected_exception):
            pool.apply_async(time.sleep, 0)

    def test_process_queue_handles_preexisting_mails(self):
        """Pre-existing mails are processed"""
        self.patch_mail_processor()
        self.add_mails_to_queue('a', 'b')

        self.queue.process_queue()
        self.queue.close_pool()

        self.assertQueueIsEmpty()

    def test_process_queue_does_not_start_tasks_for_entries_with_task(self):
        """Mails being processed are not re-queued"""
        self.patch_mail_processor()
        entry_a, entry_b = self.add_mails_to_queue('a', 'b')
        self.patch_methods(entry_a, processing_task_started=True,
                           processing_task_finished=False,
                           start_processing_task=None)
        self.patch_methods(entry_b, processing_task_started=False,
                           processing_task_finished=False,
                           start_processing_task=None)

        self.queue.process_queue()

        self.assertFalse(entry_a.start_processing_task.called)
        entry_b.start_processing_task.assert_called_once_with()

    def test_process_queue_handles_processing_task_result(self):
        """Mails being processed are handled when finished"""
        self.patch_mail_processor()
        entry_a, entry_b = self.add_mails_to_queue('a', 'b')
        self.patch_methods(entry_a, processing_task_started=True,
                           processing_task_finished=False,
                           handle_processing_task_result=None)
        self.patch_methods(entry_b, processing_task_started=True,
                           processing_task_finished=True,
                           handle_processing_task_result=None)

        self.queue.process_queue()

        entry_a.processing_task_finished.assert_called_once_with()
        entry_b.processing_task_finished.assert_called_once_with()
        self.assertFalse(entry_a.handle_processing_task_result.called)
        entry_b.handle_processing_task_result.assert_called_once_with()

    def test_process_queue_works_when_queue_items_are_removed(self):
        """The processing of entries results in entries being dropped. This
        should not confuse process_queue which should still properly
        process all entries"""
        queue = ['a', 'b', 'c', 'd', 'e', 'f']
        self.queue._count_mock_calls = 0
        for entry in self.add_mails_to_queue(*queue):
            def side_effect():
                entry.queue._count_mock_calls += 1
                entry.queue.remove(entry.identifier)
                return False
            self.patch_methods(entry, processing_task_started=True,
                               processing_task_finished=side_effect)

        self.queue.process_queue()

        self.assertEqual(self.queue._count_mock_calls, len(queue))

    def test_sleep_timeout_mailqueue_empty(self):
        self.assertEqual(self.queue.sleep_timeout(),
                         self.queue.SLEEP_TIMEOUT_EMPTY)

    def _add_entry_task_running(self, name):
        entry = self.add_mails_to_queue(name)[0]
        self.patch_methods(entry, processing_task_started=True,
                           processing_task_finished=False)
        return entry

    def test_sleep_timeout_task_started_not_finished(self):
        self._add_entry_task_running('a')
        self.assertEqual(self.queue.sleep_timeout(),
                         self.queue.SLEEP_TIMEOUT_TASK_RUNNING)

    def _add_entry_task_finished(self, name):
        entry = self.add_mails_to_queue(name)[0]
        self.patch_methods(entry, processing_task_started=True,
                           processing_task_finished=True)
        return entry

    def test_sleep_timeout_task_finished(self):
        self._add_entry_task_finished('a')
        self.assertEqual(self.queue.sleep_timeout(),
                         self.queue.SLEEP_TIMEOUT_TASK_FINISHED)

    def _add_entry_task_waiting_next_try(self, name):
        entry = self.add_mails_to_queue(name)[0]
        entry.schedule_next_try()
        return entry

    def _get_wait_time(self, entry):
        wait_time = entry.get_data('next_try_time') - self.current_datetime
        return wait_time.total_seconds()

    def test_sleep_timeout_task_waiting_next_try(self):
        self.patch_now()
        entry = self._add_entry_task_waiting_next_try('a')
        wait_time = self._get_wait_time(entry)
        self.assertEqual(self.queue.sleep_timeout(), wait_time)

    def _add_entry_task_runnable(self, name):
        entry = self.add_mails_to_queue(name)[0]
        return entry

    def test_sleep_timeout_task_runnable(self):
        self._add_entry_task_runnable('a')
        self.assertEqual(self.queue.sleep_timeout(),
                         self.queue.SLEEP_TIMEOUT_TASK_RUNNABLE)

    def test_sleep_timeout_picks_the_shorter_wait_time(self):
        self.patch_now()
        self._add_entry_task_running('a')
        self._add_entry_task_runnable('b')
        self._add_entry_task_finished('c')
        entry_d = self._add_entry_task_waiting_next_try('d')
        wait_time = self._get_wait_time(entry_d)
        self.assertEqual(self.queue.sleep_timeout(),
                         min(self.queue.SLEEP_TIMEOUT_TASK_RUNNING,
                             self.queue.SLEEP_TIMEOUT_TASK_RUNNABLE,
                             self.queue.SLEEP_TIMEOUT_TASK_FINISHED,
                             wait_time))

    def start_process_loop(self, stop_after=None):
        """
        Start process_loop() in a dedicated process and ensure it's
        ready to proocess new files before returning
        """
        self.mkdir(self.queue._get_maildir())
        lock = multiprocessing.Lock()
        lock.acquire()

        def process_loop(lock):
            def release_lock():
                lock.release()
            queue = MailQueue()
            queue.process_loop(stop_after=stop_after, ready_cb=release_lock)
        process = multiprocessing.Process(target=process_loop, args=(lock,))
        process.start()
        lock.acquire()
        return process

    def test_process_loop_processes_one_mail(self):
        self.patch_mail_processor()
        process = self.start_process_loop(stop_after=1)
        # The mail is created after process_loop() is ready
        path = self.create_mail('a')
        # We wait the end of the task for max 1 second
        process.join(1)
        # Process finished successfully (and we're not here due to timeout)
        if process.is_alive():
            process.terminate()
            self.fail("process_loop did not terminate")
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        # And it did its job by handling the mail
        self.assertFalse(os.path.exists(path))

    @mock.patch('distro_tracker.mail.processor.MailQueueWatcher')
    def test_process_loop_calls_sleep_timeout(self, mock_watcher):
        """Ensure we feed the sleep timeout to watcher.process_events"""
        self.mkdir(self.queue._get_maildir())
        self.patch_methods(self.queue, sleep_timeout=mock.sentinel.DELAY)
        self.queue.process_loop(stop_after=0)
        mock_watcher.return_value.process_events.assert_called_with(
            timeout=mock.sentinel.DELAY)

    @mock.patch('distro_tracker.mail.processor.MailQueueWatcher')
    def test_process_loop_calls_initialize(self, mock_watcher):
        """Ensure we call the initialize method before announcing readyness"""
        self.patch_methods(self.queue, initialize=None)

        def check_when_ready():
            self.queue.initialize.assert_called_with()
        self.queue.process_loop(stop_after=0, ready_cb=check_when_ready)


class MailQueueEntryTest(TestCase, QueueHelperMixin):

    def setUp(self):
        self.queue = MailQueue()
        self.identifier = 'mail-abc'
        self.entry = self.queue.add(self.identifier)

    def test_attributes(self):
        maildir = self.queue._get_maildir()

        self.assertEqual(self.entry.identifier, self.identifier)
        self.assertEqual(self.entry.queue, self.queue)
        self.assertEqual(self.entry.path,
                         os.path.join(maildir, self.identifier))
        self.assertIsInstance(self.entry.data, dict)

    def test_entry_has_creation_time(self):
        self.patch_now()
        entry = MailQueueEntry(self.queue, self.identifier)
        self.assertEqual(entry.get_data('creation_time'), self.current_datetime)

    def test_set_get_data_cycle(self):
        self.entry.set_data('key', mock.sentinel.data_value)
        self.assertIs(self.entry.get_data('key'), mock.sentinel.data_value)

    def test_get_data_on_unset_data(self):
        self.assertIsNone(self.entry.get_data('key'))

    def test_move_to_subfolder(self):
        old_path = self.entry.path
        new_path = os.path.join(self.queue._get_maildir('subfolder'),
                                self.identifier)
        self.mkdir(self.queue._get_maildir())
        self.create_mail(old_path, subject='move_to_subfolder')
        self.assertTrue(os.path.exists(old_path))
        self.assertFalse(os.path.exists(new_path))

        self.entry.move_to_subfolder('subfolder')

        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))
        with open(new_path, 'rb') as f:
            msg = message_from_bytes(f.read())
        self.assertEqual(msg['Subject'], 'move_to_subfolder')

    def test_start_processing_task_does_its_job(self):
        self.create_mail(self.identifier)
        self.patch_mail_processor()

        self.assertFalse(self.entry.processing_task_started())
        self.assertInQueue(self.entry)
        self.assertTrue(os.path.exists(self.entry.path))

        self.entry.start_processing_task()

        self.assertTrue(self.entry.processing_task_started())
        self.queue.close_pool()  # Wais until the worker finished
        self.assertNotInQueue(self.entry)
        self.assertFalse(os.path.exists(self.entry.path))

    def test_start_processing_task_stores_task_result(self):
        self.patch_mail_processor()

        self.entry.start_processing_task()

        result = self.entry.get_data('task_result')
        self.assertIsInstance(result, multiprocessing.pool.AsyncResult)

    def test_start_processing_task_respects_next_try_time(self):
        self.patch_now()
        self.patch_mail_processor()
        self.entry.set_data('next_try_time',
                            self.current_datetime + timedelta(seconds=10))

        self.entry.start_processing_task()

        self.assertFalse(self.entry.processing_task_started())
        self.current_datetime += timedelta(seconds=10)

        self.entry.start_processing_task()

        self.assertTrue(self.entry.processing_task_started())

    def test_processing_task_finished(self):
        self.patch_mail_processor()
        self.assertFalse(self.entry.processing_task_finished())

        self.entry.start_processing_task()
        self.entry.get_data('task_result').wait()

        self.assertTrue(self.entry.processing_task_finished())

    def test_task_result_get_forwards_exceptions(self):
        """
        Ensure that the get() method of a task's AsyncResult forwards
        exceptions thrown by the worker. This should be so as per
        documentation but ensuring that we can reproduce is better.
        """
        self.create_mail(self.identifier)
        mock_process = self.patch_mail_processor()
        mock_process.side_effect = MailProcessorException
        self.entry.start_processing_task()
        task_result = self.entry.get_data('task_result')

        with self.assertRaises(MailProcessorException):
            task_result.get()

    @staticmethod
    def _get_fake_task_result(side_effect=None):
        mock_task_result = mock.MagicMock()
        if side_effect:
            mock_task_result.get.side_effect = side_effect
        return mock_task_result

    def test_handle_processing_task_result(self):
        """Should not fail with a task that actually worked"""
        task_result = self._get_fake_task_result()
        self.entry.set_data('task_result', task_result)

        self.entry.handle_processing_task_result()

        task_result.get.assert_called_with()
        self.assertNotInQueue(self.entry)

    def test_handle_processing_task_result_without_results(self):
        """Should do nothing when task is not yet finished"""
        self.entry.handle_processing_task_result()

        self.assertInQueue(self.entry)

    def test_handle_processing_task_result_mail_processor_exception(self):
        '''Task failing with a MailProcessorException result in
        immediate failure and move to the failed subfolder'''
        task_result = self._get_fake_task_result(
            side_effect=MailProcessorException)
        self.entry.set_data('task_result', task_result)

        with mock.patch.object(self.entry, 'move_to_subfolder') as mock_move:
            self.entry.handle_processing_task_result()
            mock_move.assert_called_once_with('failed')

        self.assertNotInQueue(self.entry)

    def test_handle_processing_task_resulted_in_exception_no_tries_left(self):
        '''Task failing with a generic exception result in failure when
        the entry refuses to schedule a new try'''
        task_result = self._get_fake_task_result(side_effect=Exception)
        self.entry.set_data('task_result', task_result)
        self.patch_methods(self.entry, move_to_subfolder=None,
                           schedule_next_try=False)

        self.entry.handle_processing_task_result()

        self.entry.move_to_subfolder.assert_called_with('broken')
        self.assertNotInQueue(self.entry)

    def test_handle_processing_task_resulted_in_exception_tries_left(self):
        '''Task failing with a generic exception result in a new try when
        allowed'''
        task_result = self._get_fake_task_result(side_effect=Exception)
        self.entry.set_data('task_result', task_result)
        self.patch_methods(self.entry, move_to_subfolder=None,
                           schedule_next_try=True)

        self.entry.handle_processing_task_result()

        self.assertFalse(self.entry.move_to_subfolder.called)
        self.assertInQueue(self.entry)

    def test_schedule_next_try_returns_true_a_few_times(self):
        '''Accept to schedule a new try a few times'''
        for i in range(4):
            self.assertTrue(self.entry.schedule_next_try())

    def test_schedule_next_try_eventually_returns_false(self):
        '''Eventually decide that enough is enough'''
        count = 0
        while self.entry.schedule_next_try():
            count += 1
            if count > 50:
                self.fail("schedule_next_try doesn't want to fail")

    def test_schedule_next_try_sets_log_failure_on_first_try(self):
        '''Should not log failure on first try'''
        self.entry.set_data('log_failure', True)
        self.entry.schedule_next_try()
        self.assertFalse(self.entry.get_data('log_failure'))

    def test_schedule_next_try_does_log_failure_on_last_try_only(self):
        '''Should log failure on last try'''
        while not self.entry.get_data('log_failure'):
            self.assertTrue(self.entry.schedule_next_try())
        self.assertFalse(self.entry.schedule_next_try())

    def test_schedule_next_try_sets_next_try_time(self):
        '''The scheduling is done via next_try_time data entry'''
        self.patch_now()
        for i in range(10):
            if not self.entry.schedule_next_try():
                break
            next_try = self.entry.get_data('next_try_time')
            self.assertGreater(next_try, self.current_datetime)
            self.curent_datetime = next_try

    def test_schedule_next_try_reset_started_flag(self):
        self.entry.start_processing_task()
        self.assertTrue(self.entry.processing_task_started())

        self.entry.schedule_next_try()

        self.assertFalse(self.entry.processing_task_started())


class MailQueueWatcherTest(TestCase, QueueHelperMixin):
    def setUp(self):
        self.queue = MailQueue()
        self.watcher = MailQueueWatcher(self.queue)
        self.mkdir(self.queue._get_maildir())

    def test_process_events(self):
        self.watcher.start()
        self.assertQueueIsEmpty()

        self.create_mail('a')
        self.watcher.process_events()

        self.assertEqual(len(self.queue.queue), 1)
        self.assertEqual(self.queue.queue[0].identifier, 'a')

    def test_process_events_when_hardlinked_into_maildir(self):
        self.watcher.start()
        self.assertQueueIsEmpty()

        self.create_mail('a', hardlink_from_tmp=True)
        self.watcher.process_events()

        self.assertEqual(len(self.queue.queue), 1)
        self.assertEqual(self.queue.queue[0].identifier, 'a')

    def test_process_events_does_not_block(self):
        self.watcher.start()

        before = datetime.now()
        self.watcher.process_events()
        after = datetime.now()

        delta = after - before
        self.assertLess(delta.total_seconds(), 1)

    def test_start_fails_when_dir_does_not_exist(self):
        os.rmdir(self.queue._get_maildir())

        with self.assertRaises(pyinotify.WatchManagerError):
            self.watcher.start()
