# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core management commands.
"""

import io
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from distro_tracker.accounts.models import User, UserEmail
from distro_tracker.core.models import (
    EmailNews,
    EmailSettings,
    News,
    SourcePackageName,
    Subscription
)
from distro_tracker.core.utils import message_from_bytes
from distro_tracker.test import SimpleTestCase, TestCase


@mock.patch('distro_tracker.core.management.commands.tracker_run_task.run_task')
class RunTaskManagementCommandTest(SimpleTestCase):
    """
    Test for the :mod:`distro_tracker.core.management.commands.tracker_run_task`
    management command.
    """
    def run_command(self, tasks, **kwargs):
        call_command('tracker_run_task', *tasks, **kwargs)

    def test_runs_all(self, mock_run_task):
        """
        Tests that the management command calls the
        :func:`run_task <distro_tracker.core.tasks.run_task>` function for each
        given task name.
        """
        mock_run_task.return_value = True
        self.run_command(['TaskName1', 'TaskName2'])

        # The run task was called only for the given commands
        self.assertListEqual(
            mock_run_task.mock_calls,
            [mock.call('TaskName1'), mock.call('TaskName2')]
        )

    def test_passes_force_flag(self, mock_run_task):
        """
        Tests that the management command passes the force flag to the task
        invocations when it is given.
        """
        mock_run_task.return_value = True
        self.run_command(['TaskName1'], force_update=True)

        mock_run_task.assert_called_once_with('TaskName1', force_update=True)

    def test_passes_fake_flag(self, mock_run_task):
        """
        Tests that the management command passes the fake_update flag to the
        task invocations when it is given.
        """
        mock_run_task.return_value = True
        self.run_command(['TaskName1'], fake_update=True)

        mock_run_task.assert_called_once_with('TaskName1', fake_update=True)

    def test_outputs_to_stderr_when_fails(self, mock_run_task):
        mock_run_task.return_value = False
        stderr = io.StringIO()

        self.run_command(['TaskName1'], stderr=stderr)

        self.assertEqual(stderr.getvalue(),
                         'Task TaskName1 failed to run.\n')


@mock.patch('distro_tracker.core.management.commands.'
            'tracker_run_all_tasks.run_all_tasks')
class RunAllTasksTests(SimpleTestCase):
    """
    Test for the :mod:`distro_tracker.core.management.commands.tracker_run_task`
    management command.
    """
    def run_command(self, *args, **kwargs):
        call_command('tracker_run_all_tasks', *args, **kwargs)

    def test_runs_all(self, mock_run_all_tasks, *args, **kwargs):
        """
        Tests that the management command calls the
        :func:`run_all_tasks <distro_tracker.core.tasks.base.run_all_tasks>`
        function.
        """
        self.run_command()

        mock_run_all_tasks.assert_called_once_with()

    def test_passes_force_flag(self, mock_run_all_tasks):
        """
        Tests that the management command passes the force flag to the task
        invocations when it is given.
        """
        self.run_command(force_update=True)

        mock_run_all_tasks.assert_called_once_with(force_update=True)

    def test_passes_fake_flag(self, mock_run_all_tasks):
        """
        Tests that the management command passes the fake_update flag to the
        task invocations when it is given.
        """
        self.run_command(fake_update=True)

        mock_run_all_tasks.assert_called_once_with(fake_update=True)


class UpdateNewsSignaturesCommandTest(TestCase):
    """
    Tests for the
    :mod:`distro_tracker.core.management.commands.tracker_update_news_signatures`
    management command.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

    def test_signatures_added(self):
        """
        Tests that signatures are correctly added to the news which previously
        didn't have any, despite having signed content.
        """
        # Set up news based on a signed message.
        signed_news = []
        unsigned_news = []
        self.import_key_into_keyring('key1.pub')
        # The content of the test news item is found in a file
        file_path = self.get_test_data_path(
            'signed-message-quoted-printable')
        with open(file_path, 'rb') as f:
            content = f.read()
        expected_name = 'PTS Tests'
        expected_email = 'fake-address@domain.com'
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


class FixDatabaseCommandTests(TestCase):

    def setUp(self):
        self.email = 'user@example.net'
        self.alt_email = self.email.capitalize()
        self.user_email = UserEmail.objects.create(email=self.email)
        self.alt_user_email = UserEmail.objects.create(email=self.alt_email)
        self.subscribe(self.user_email, 'pkg-1')
        self.subscribe(self.alt_user_email, 'pkg-2')

    def subscribe(self, email, package):
        # Special subscribe method which avoids the case insensitive lookup
        pkg, _ = SourcePackageName.objects.get_or_create(name=package)
        user_email, _ = UserEmail.objects.get_or_create(
            email__exact=email,
            defaults={'email': email}
        )
        es, _ = EmailSettings.objects.get_or_create(user_email=user_email)
        Subscription.objects.create(package=pkg, email_settings=es)

    def test_management_command_drop_duplicates(self):
        call_command('tracker_fix_database')
        self.assertEqual(UserEmail.objects.filter(email=self.alt_email).count(),
                         0)

    def test_management_command_merges_users(self):
        user = User(main_email=self.alt_email)
        user.save()
        user.emails.add(self.alt_user_email)

        self.alt_user_email.refresh_from_db()
        self.assertIsNotNone(self.alt_user_email.user)
        self.user_email.refresh_from_db()
        self.assertIsNone(self.user_email.user)

        call_command('tracker_fix_database')

        self.user_email.refresh_from_db()
        self.assertEqual(self.user_email.user.pk, user.pk)

    def test_management_command_merges_subscriptions(self):
        call_command('tracker_fix_database')

        subscriptions = self.user_email.emailsettings.subscription_set
        self.assertEqual(subscriptions.filter(package__name='pkg-1').count(), 1)
        self.assertEqual(subscriptions.filter(package__name='pkg-2').count(), 1)

    def test_management_command_merges_subscriptions_ignores_existing(self):
        """
        Ensure that the subscription merge handles properly the case where
        the same subscription is present on both UserEmail
        """
        self.subscribe(self.user_email, 'pkg-2')

        call_command('tracker_fix_database')

        subscriptions = self.user_email.emailsettings.subscription_set
        self.assertEqual(subscriptions.filter(package__name='pkg-2').count(), 1)

    def test_management_command_no_email_settings_on_main_email(self):
        # Drop the EmailSettings on the main UserEmail
        self.user_email.emailsettings.delete()
        self.user_email = UserEmail.objects.get(email=self.email)
        with self.assertRaises(Exception):
            self.user_email.emailsettings

        call_command('tracker_fix_database')

        # Ensure migrations happened
        self.user_email = UserEmail.objects.get(email=self.email)
        self.assertIsNotNone(self.user_email.emailsettings)
        subscriptions = self.user_email.emailsettings.subscription_set
        self.assertEqual(subscriptions.filter(package__name='pkg-2').count(), 1)

    def test_management_command_no_email_settings_on_alt_email(self):
        # Drop the EmailSettings on the main UserEmail
        self.alt_user_email.emailsettings.delete()
        self.alt_user_email = UserEmail.objects.get(email=self.alt_email)
        with self.assertRaises(Exception):
            self.alt_user_email.emailsettings

        call_command('tracker_fix_database')

    def test_management_command_no_email_settings_at_all(self):
        self.user_email.emailsettings.delete()
        self.alt_user_email.emailsettings.delete()
        call_command('tracker_fix_database')

    def test_management_command_drops_duplicate_news_multiple_packages(self):
        src1 = self.create_source_package(name='src1').source_package_name
        src2 = self.create_source_package(name='src2').source_package_name
        src3 = self.create_source_package(name='src3').source_package_name
        for src in (src1, src2, src3):
            for i in range(5):
                News.objects.create(package=src, title='Duplicate title',
                                    content='Nothing interesting',
                                    created_by='Test Suite')
        self.assertEqual(src1.news_set.count(), 5)
        self.assertEqual(src2.news_set.count(), 5)
        self.assertEqual(src3.news_set.count(), 5)

        call_command('tracker_fix_database')

        self.assertEqual(src1.news_set.count(), 1)
        self.assertEqual(src2.news_set.count(), 1)
        self.assertEqual(src3.news_set.count(), 1)

    def test_management_command_drops_duplicate_news_multiple_titles(self):
        src1 = self.create_source_package(name='src1').source_package_name
        for i in range(5):
            News.objects.create(package=src1, title='Title %i' % i,
                                content='Nothing interesting',
                                created_by='Test Suite')
        self.assertEqual(src1.news_set.count(), 5)

        call_command('tracker_fix_database')

        self.assertEqual(src1.news_set.count(), 5)

    def test_management_command_drops_duplicate_news_multiple_days(self):
        src1 = self.create_source_package(name='src1').source_package_name
        now = timezone.now()
        for i in range(5):
            news = News.objects.create(
                package=src1, title='Duplicate title',
                content='Nothing interesting', created_by='Test Suite')
            news.datetime_created = now - timedelta(days=i)
            news.save()
        self.assertEqual(src1.news_set.count(), 5)

        call_command('tracker_fix_database')

        self.assertEqual(src1.news_set.count(), 5)
