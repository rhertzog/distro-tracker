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

from django.utils.six.moves import mock
from django.core.management import call_command

from distro_tracker.accounts.models import User
from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import EmailNews
from distro_tracker.core.models import EmailSettings
from distro_tracker.core.models import News
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import Subscription
from distro_tracker.core.utils import message_from_bytes
from distro_tracker.test import SimpleTestCase
from distro_tracker.test import TestCase


class RunTaskManagementCommandTest(SimpleTestCase):
    """
    Test for the :mod:`distro_tracker.core.management.commands.tracker_run_task`
    management command.
    """
    def run_command(self, tasks, **kwargs):
        call_command('tracker_run_task', *tasks, **kwargs)

    @mock.patch(
        'distro_tracker.core.management.commands.tracker_run_task.run_task')
    def test_runs_all(self, mock_run_task):
        """
        Tests that the management command calls the
        :func:`run_task <distro_tracker.core.tasks.run_task>` function for each
        given task name.
        """
        self.run_command(['TaskName1', 'TaskName2'])

        # The run task was called only for the given commands
        self.assertEqual(2, mock_run_task.call_count)
        mock_run_task.assert_any_call('TaskName1', None)
        mock_run_task.assert_any_call('TaskName2', None)

    @mock.patch(
        'distro_tracker.core.management.commands.tracker_run_task.run_task')
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
        :func:`run_task <distro_tracker.core.tasks.run_task>` function for each
        given task name.
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
