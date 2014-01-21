# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core management commands.
"""
from __future__ import unicode_literals
from django.test import SimpleTestCase
from django.test import TestCase
from django.utils.six.moves import mock
from django.core.management import call_command
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import EmailNews
from distro_tracker.core.models import News
from distro_tracker.core.utils import message_from_bytes
from distro_tracker.core.tests.common import make_temp_directory
from distro_tracker.core.tests.common import temporary_media_dir

import os
import gpgme


class RunTaskManagementCommandTest(SimpleTestCase):
    """
    Test for the :mod:`distro_tracker.core.management.commands.tracker_run_task` management
    command.
    """
    def run_command(self, tasks, **kwargs):
        call_command('tracker_run_task', *tasks, **kwargs)

    @mock.patch('distro_tracker.core.management.commands.tracker_run_task.run_task')
    def test_runs_all(self, mock_run_task):
        """
        Tests that the management command calls the
        :func:`run_task <distro_tracker.core.tasks.run_task>` function for each given task
        name.
        """
        self.run_command(['TaskName1', 'TaskName2'])

        # The run task was called only for the given commands
        self.assertEqual(2, mock_run_task.call_count)
        mock_run_task.assert_any_call('TaskName1', None)
        mock_run_task.assert_any_call('TaskName2', None)

    @mock.patch('distro_tracker.core.management.commands.tracker_run_task.run_task')
    def test_passes_force_flag(self, mock_run_task):
        """
        Tests that the management command passes the force flag to the task
        invocations when it is given.
        """
        self.run_command(['TaskName1'], force=True)

        mock_run_task.assert_called_with('TaskName1', {
            'force_update': True,
        })


@mock.patch('distro_tracker.core.tasks.import_all_tasks')
@mock.patch('distro_tracker.core.management.commands.tracker_run_all_tasks.run_all_tasks')
class RunAllTasksTests(SimpleTestCase):
    """
    Test for the :mod:`distro_tracker.core.management.commands.tracker_run_task` management
    command.
    """
    def run_command(self, *args, **kwargs):
        call_command('tracker_run_all_tasks', *args, **kwargs)

    def test_runs_all(self, mock_run_all_tasks, *args, **kwargs):
        """
        Tests that the management command calls the
        :func:`run_task <distro_tracker.core.tasks.run_task>` function for each given task
        name.
        """
        self.run_command()

        # The run task was called only for the given commands
        mock_run_all_tasks.assert_called_once_with(None)

    def test_passes_force_flag(self, mock_run_all_tasks, *args, **kwargs):
        """
        Tests that the management command passes the force flag to the task
        invocations when it is given.
        """
        self.run_command(force=True)

        mock_run_all_tasks.assert_called_once_with({
            'force_update': True,
        })


class UpdateNewsSignaturesCommandTest(TestCase):
    """
    Tests for the
    :mod:`distro_tracker.core.management.commands.tracker_update_news_signatures`
    management command.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

    def import_key_from_test_file(self, file_name):
        """
        Helper function which imports the given test key file into the test
        keyring.
        """
        old = os.environ.get('GNUPGHOME', None)
        os.environ['GNUPGHOME'] = self.TEST_KEYRING_DIRECTORY
        ctx = gpgme.Context()
        file_path = os.path.join(
            os.path.dirname(__file__),
            'tests-data/keys',
            file_name
        )
        with open(file_path, 'rb') as key_file:
            ctx.import_(key_file)

        if old:
            os.environ['GNUPGHOME'] = old

    def get_test_file_path(self, file_name):
        """
        Helper method returning the full path to the test file with the given
        name.
        """
        return os.path.join(
            os.path.dirname(__file__),
            'tests-data',
            file_name)

    @temporary_media_dir
    def test_signatures_added(self):
        """
        Tests that signatures are correctly added to the news which previously
        didn't have any, despite having signed content.
        """
        # Set up news based on a signed message.
        signed_news = []
        unsigned_news = []
        with make_temp_directory('-pts-keyring') as TEST_KEYRING_DIRECTORY:
            self.TEST_KEYRING_DIRECTORY = TEST_KEYRING_DIRECTORY
            with self.settings(
                    DISTRO_TRACKER_KEYRING_DIRECTORY=self.TEST_KEYRING_DIRECTORY):
                self.import_key_from_test_file('key1.pub')
                # The content of the test news item is found in a file
                file_path = self.get_test_file_path(
                    'signed-message-quoted-printable')
                with open(file_path, 'rb') as f:
                    content = f.read()
                expected_name = 'PTS Tests'
                expected_email = 'fake-address@domain.com'
                sender_name = 'Some User'
                # The first signed news has the same content as what is found
                # the signed test file.
                signed_news.append(EmailNews.objects.create_email_news(
                    message=message_from_bytes(content),
                    package=self.package))
                # For the second one, add some text after the signature: this
                # should still mean that the correct signature can be extracted!
                signed_news.append(EmailNews.objects.create_email_news(
                    message=message_from_bytes(content + b'\nMore content'),
                    package=self.package))
                # Set up some unsigned news.
                unsigned_news.append(EmailNews.objects.create_email_news(
                    message=message_from_bytes(b'Subject: Hi\n\nPayload.'),
                    package=self.package))
                # A non-email based news item
                unsigned_news.append(News.objects.create(
                    package=self.package,
                    content="Some content.."
                ))
                # Make sure that the signed news do not have associated
                # signature information
                for signed in signed_news:
                    signed.signed_by.clear()

                # Run the command
                call_command("tracker_update_news_signatures")

                # The signed news items have associated signature information
                for signed in signed_news:
                    self.assertEqual(1, signed.signed_by.count())
                    signer = signed.signed_by.all()[0]
                    # The signature is actually correct too?
                    self.assertEqual(expected_name, signer.name)
                    self.assertEqual(expected_email, signer.email)
                # The unsigned messages still do not have any signature info
                for unsigned in unsigned_news:
                    self.assertEqual(0, unsigned.signed_by.count())
