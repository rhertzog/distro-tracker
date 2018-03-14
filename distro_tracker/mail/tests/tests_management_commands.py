# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests the management command of the :mod:`distro_tracker.mail` app.
"""
import io
import json
from email.message import Message
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from django.utils.encoding import force_bytes

from distro_tracker.core.models import (
    EmailSettings,
    Keyword,
    PackageName,
    PseudoPackageName,
    SourcePackageName,
    Subscription,
    UserEmail
)
from distro_tracker.mail.management.commands.tracker_control import \
    Command as ControlCommand
from distro_tracker.mail.management.commands.tracker_dispatch import \
    Command as DispatchCommand
from distro_tracker.test import TestCase


class CommandWithInputTestCase(TestCase):
    def build_input_message(self, text, target):
        msg = Message()
        msg['From'] = 'user@example.net'
        msg['To'] = '{}@{}'.format(target, settings.DISTRO_TRACKER_FQDN)
        msg['Delivered-To'] = msg['To']
        msg['Subject'] = 'Test message'
        msg.set_payload(text)
        self.input_message = msg
        return force_bytes(msg.as_string(), 'utf-8')

    def call_command(self, input_data, *args, **kwargs):
        cmd = self.command_class()
        cmd.input_file = io.BytesIO(input_data)
        cmd.handle(*args, **kwargs)

    def assert_is_input_message(self, msg):
        """
        Ensure passed message is the same as the message we have fed to the
        command
        """
        self.assertEqual(force_bytes(self.input_message.as_string(), 'utf-8'),
                         force_bytes(msg.as_string(), 'utf-8'))


class CommandWithOutputTestCase(TestCase):
    def call_command(self, *args, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        kwargs['stdout'] = stdout
        kwargs['stderr'] = stderr

        call_command(self.command_name, *args, **kwargs)

        self.out = stdout.getvalue()
        self.err_out = stderr.getvalue()


class ControlManagementCommand(CommandWithInputTestCase):
    command_class = ControlCommand

    @mock.patch('distro_tracker.mail.control.process')
    def test_control_command_calls_process(self, mock_process):
        data = self.build_input_message('help\n', 'control')
        self.call_command(data)
        self.assertTrue(mock_process.called)
        self.assert_is_input_message(mock_process.call_args[0][0])

    def test_control_command_does_something(self):
        data = self.build_input_message('help\n', 'control')
        self.call_command(data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('The package tracker supports the following commands:',
                      mail.outbox[0].message().get_payload())


class DispatchManagementCommand(CommandWithInputTestCase):
    command_class = DispatchCommand

    @mock.patch('distro_tracker.mail.dispatch.process')
    def test_dispatch_command_with_normal_message(self, mock_process):
        msg = self.build_input_message('hello\n', 'dispatch+dummy')
        self.call_command(msg)
        mock_process.assert_called_with(mock.ANY, package='dummy', keyword=None)
        self.assert_is_input_message(mock_process.call_args[0][0])

    def test_dispatch_command_forwards_something(self):
        PackageName.objects.create(name='dummy')
        Subscription.objects.create_for(
            package_name='dummy',
            email='user@example.net',
            active=True)
        msg = self.build_input_message('hello\n', 'dispatch+dummy_contact')
        self.call_command(msg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].message()['X-Distro-Tracker-Package'],
                         'dummy')

    @mock.patch('distro_tracker.mail.dispatch.handle_bounces')
    def test_dispatch_command_with_bounces(self, mock_handle_bounces):
        msg = self.build_input_message('hello\n', 'bounces+verpdata')
        self.call_command(msg)
        mock_handle_bounces.assert_called_with(
            'bounces+verpdata@{}'.format(settings.DISTRO_TRACKER_FQDN),
            mock.ANY)


class UnsubscribeAllManagementCommand(CommandWithOutputTestCase):
    command_name = 'tracker_unsubscribe_all'

    def setUp(self):
        self.packages = [
            PackageName.objects.create(name='dummy-package'),
            PackageName.objects.create(name='second-package'),
        ]
        self.user = UserEmail.objects.create(email='email-user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)
        for package in self.packages:
            Subscription.objects.create(package=package,
                                        email_settings=self.email_settings)

        self.nosub_user = UserEmail.objects.create(email='nosub@dom.com')

    def assert_unsubscribed_user_response(self):
        for package in self.packages:
            self.assertIn(
                'Unsubscribing {email} from {package}'.format(
                    email=self.user.email, package=package.name),
                self.out)

    def assert_no_subscriptions_response(self):
        self.assertIn(
            'Email {email} is not subscribed to any packages.'.format(
                email=self.nosub_user),
            self.out)

    def assert_user_does_not_exist_response(self, user):
        self.assertIn(
            'Email {email} is not subscribed to any packages. '
            'Bad email?'.format(
                email=user),
            self.out)

    def test_unsubscribe_user(self):
        """
        Tests the management command ``distro_tracker_unsubscribe_all`` when a
        user with subscriptions is given.
        """
        self.call_command(self.user.email)

        self.assert_unsubscribed_user_response()
        self.assertEqual(self.email_settings.subscription_set.count(), 0)

    def test_unsubscribe_doesnt_exist(self):
        """
        Tests the management command ``distro_tracker_unsubscribe_all`` when
        the given user does not exist.
        """
        self.call_command('no-exist')

        self.assert_user_does_not_exist_response('no-exist')

    def test_unsubscribe_no_subscriptions(self):
        """
        Tests the management command ``distro_tracker_unsubscribe_all`` when
        the given user is not subscribed to any packages.
        """
        self.call_command(self.nosub_user.email)

        self.assert_no_subscriptions_response()

    def test_unsubscribe_multiple_user(self):
        """
        Tests the management command ``distro_tracker_unsubscribe_all`` when
        multiple users are passed to it.
        """
        args = ['no-exist', self.nosub_user.email, self.user.email]
        self.call_command(*args)

        self.assert_unsubscribed_user_response()
        self.assertEqual(self.email_settings.subscription_set.count(), 0)
        self.assert_user_does_not_exist_response('no-exist')
        self.assert_no_subscriptions_response()


class DumpSubscribersManagementCommandTest(CommandWithOutputTestCase):
    command_name = 'tracker_dump_subscribers'

    def setUp(self):
        self.packages = [
            PackageName.objects.create(name='package' + str(i))
            for i in range(5)
        ]
        self.users = [
            UserEmail.objects.create(email='user@domain.com'),
            UserEmail.objects.create(email='other-user@domain.com'),
        ]

    def assert_warning_in_output(self, text):
        self.assertIn('Warning: ' + text, self.err_out)

    def assert_package_in_output(self, package):
        self.assertIn('{package} => ['.format(package=package), self.out)

    def assert_user_list_in_output(self, users):
        self.assertIn('[ ' + ' '.join(str(user) for user in users) + ' ]',
                      self.out)

    def test_dump_one_package(self):
        user = self.users[0]
        email_settings = EmailSettings.objects.create(user_email=user)
        package = self.packages[0]
        Subscription.objects.create(email_settings=email_settings,
                                    package=package)

        self.call_command()

        self.assert_package_in_output(package)
        self.assert_user_list_in_output([user])

    def test_dump_all_active(self):
        # Subscribe the users
        for user in self.users:
            email_settings = EmailSettings.objects.create(user_email=user)
            for package in self.packages:
                Subscription.objects.create(email_settings=email_settings,
                                            package=package)

        self.call_command()

        for package in self.packages:
            self.assert_package_in_output(package)
        self.assert_user_list_in_output(self.users)

    def test_dump_only_active(self):
        """
        Tests that only users with an active subscriptions are returned by
        default.
        """
        # All users have an active subscription to the first package
        for user in self.users:
            email_settings = EmailSettings.objects.create(user_email=user)
            Subscription.objects.create(email_settings=email_settings,
                                        package=self.packages[0])
        # The first user has an active subscription to the second package
        Subscription.objects.create(email_settings=self.users[0].emailsettings,
                                    package=self.packages[1])
        # Whereas the second user has an inactive subscription.
        Subscription.objects.create(email_settings=self.users[1].emailsettings,
                                    package=self.packages[1],
                                    active=False)

        self.call_command()

        self.assert_user_list_in_output(self.users)
        self.assert_user_list_in_output([self.users[0]])

    def test_dump_inactive(self):
        user = self.users[0]
        package = self.packages[0]
        email_settings = EmailSettings.objects.create(user_email=user)
        Subscription.objects.create(email_settings=email_settings,
                                    package=package, active=False)

        self.call_command(inactive=True)

        self.assert_package_in_output(package)
        self.assert_user_list_in_output([user])

    def test_dump_json(self):
        # Subscribe all the users
        for user in self.users:
            email_settings = EmailSettings.objects.create(user_email=user)
            for package in self.packages:
                Subscription.objects.create(email_settings=email_settings,
                                            package=package)

        self.call_command(json=True)

        output = json.loads(self.out)
        # All packages in output?
        for package in self.packages:
            self.assertIn(str(package), output)
        # All users in each output list?
        for subscribers in output.values():
            for user in self.users:
                self.assertIn(str(user), subscribers)

    def test_dump_udd_format(self):
        # Subscribe all the users
        for user in self.users:
            email_settings = EmailSettings.objects.create(user_email=user)
            for package in self.packages:
                Subscription.objects.create(email_settings=email_settings,
                                            package=package)

        self.call_command(udd_format=True)

        out_lines = self.out.splitlines()
        out_packages = {}
        for line in out_lines:
            package_name, subscribers = line.split('\t', 1)
            out_packages[package_name] = [
                subscriber.strip()
                for subscriber in subscribers.split(',')
            ]
        # All packages output
        for package in self.packages:
            self.assertIn(package.name, out_packages)
            # All its subscribers output?
            subscribers = out_packages[package.name]
            for user in self.users:
                self.assertIn(str(user), subscribers)

    def test_dump_package_does_not_exist(self):
        self.call_command('does-not-exist', verbosity=2)

        self.assert_warning_in_output('does-not-exist does not exist')


class StatsCommandTest(CommandWithOutputTestCase):
    command_name = 'tracker_stats'

    def setUp(self):
        self.package_count = 5
        for i in range(self.package_count):
            SourcePackageName.objects.create(name='package' + str(i))
        # Add some pseudo packages in the mix
        PseudoPackageName.objects.create(name='pseudo')
        self.user_count = 2
        for i in range(self.user_count):
            UserEmail.objects.create(email='email' + str(i) + '@domain.com')
        # Subscribe all users to all source packages
        self.subscription_count = self.package_count * self.user_count
        for user in UserEmail.objects.all():
            email_settings = EmailSettings.objects.create(user_email=user)
            for package in SourcePackageName.objects.all():
                Subscription.objects.create(email_settings=email_settings,
                                            package=package)

    def test_legacy_output(self):
        self.call_command()

        self.assertIn('Src pkg\tSubscr.\tDate\t\tNb email', self.out)
        expected = '\t'.join(map(str, (
            self.package_count,
            self.subscription_count,
            timezone.now().strftime('%Y-%m-%d'),
            self.user_count,
        )))
        self.assertIn(expected, self.out)

    def test_json_output(self):
        self.call_command(json=True)

        output = json.loads(self.out)
        expected = {
            'package_number': self.package_count,
            'subscription_number': self.subscription_count,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'unique_emails_number': self.user_count,
        }
        self.assertDictEqual(expected, output)


class AddKeywordManagementCommandTest(TestCase):
    def test_simple_add(self):
        """
        Tests the management command when it is only supposed to create a new
        keyword.
        """
        # Sanity check - the keyword we are about to add does not already exist
        self.assertEqual(Keyword.objects.filter(name='new-keyword').count(), 0)

        call_command('tracker_add_keyword', 'new-keyword')

        qs = Keyword.objects.filter(name='new-keyword', default=False)
        self.assertEqual(qs.count(), 1)

    def test_simple_add_default(self):
        """
        Tests the management command when it is only supposed to create a new
        default keyword.
        """
        # Sanity check - the keyword we are about to add does not already exist
        self.assertEqual(Keyword.objects.filter(name='new-keyword').count(), 0)

        call_command('tracker_add_keyword', 'new-keyword',
                     is_default_keyword=True)

        qs = Keyword.objects.filter(name='new-keyword', default=True)
        self.assertEqual(qs.count(), 1)

    def test_create_and_add_to_subscribers(self):
        """
        Tests the management command when the new keyword should be added to
        subscribers that already have another specified keyword.
        """
        existing_keyword = Keyword.objects.create(name='existing-keyword')
        # A user who added the existing keyword to its subscription keywords
        u = UserEmail.objects.create(email='subscription-user@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        p = PackageName.objects.create(name='dummy-package')
        sub = Subscription.objects.create(email_settings=s, package=p)
        sub.keywords.add(existing_keyword)
        sub.save()
        # A user who added the existing keyword to its default keywords
        u = UserEmail.objects.create(email='defaultuser@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        s.default_keywords.add(existing_keyword)
        s.save()
        # A user who does not have the existing keyword.
        u = UserEmail.objects.create(email='no-keyword@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        # Make sure that it is so!
        self.assertNotIn(existing_keyword, s.default_keywords.all())
        # Sanity check - the keyword we want to add does not already exist
        self.assertEqual(Keyword.objects.filter(name='new-keyword').count(), 0)
        # Sanity check -- only one subscription exists
        self.assertEqual(Subscription.objects.count(), 1)

        call_command('tracker_add_keyword', 'new-keyword', 'existing-keyword')

        # New keyword created?
        keyword = Keyword.objects.filter(name='new-keyword')
        self.assertTrue(keyword.exists())
        keyword = keyword[0]
        # No subscriptions changed
        self.assertEqual(Subscription.objects.count(), 1)
        sub = Subscription.objects.all()[0]
        # Keyword added to the subscription specific keywords.
        self.assertIn(keyword, sub.keywords.all())
        # New keyword added to the user that had the existing keyword in its
        # default list
        default_user = UserEmail.objects.get(email='defaultuser@domain.com')
        self.assertIn(keyword,
                      default_user.emailsettings.default_keywords.all())
        # Keyword not added to the default list of the user that did not have
        # the existing keyword
        u = UserEmail.objects.get(email='no-keyword@domain.com')
        self.assertNotIn(keyword, u.emailsettings.default_keywords.all())

    def test_create_and_add_to_subscribers_no_unlink(self):
        """
        Tests that adding a new keyword to subscriptions which had a particular
        given keyword does not cause it to become unlinked from the user's
        default keywords.
        """
        Keyword.objects.create(name='existing-keyword')
        u = UserEmail.objects.create(email='subscription-user@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        p = PackageName.objects.create(name='dummy-package')
        sub = Subscription.objects.create(email_settings=s, package=p)

        call_command('tracker_add_keyword', 'new-keyword', 'existing-keyword')

        sub = Subscription.objects.get(email_settings=s, package=p)
        self.assertTrue(sub._use_user_default_keywords)

    def test_create_and_add_no_existing_keyword(self):
        """
        Tests that the command has no effect if the given "existing" keyword
        does not actually exist.
        """
        old_count = Keyword.objects.count()

        # Error raised
        with self.assertRaises(CommandError):
            call_command('tracker_add_keyword', 'new-keyword',
                         'existing-keyword')

        # ...and nothing changed.
        self.assertEqual(Keyword.objects.count(), old_count)

    def test_create_default_keyword_to_all_users(self):
        """
        Tests adding a default keyword adds it to all users' default keywords
        list.
        """
        existing_keyword = Keyword.objects.create(name='existing-keyword')
        # A user who added an existing keyword to its default keywords
        u = UserEmail.objects.create(email='defaultuser@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        s.default_keywords.add(existing_keyword)
        s.save()
        # A user who does not have any keywords apart from the defaults
        u = UserEmail.objects.create(email='no-keyword@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        # Make sure that it is so!
        self.assertNotIn(existing_keyword, s.default_keywords.all())
        # Sanity check - the keyword we want to add does not already exist
        self.assertEqual(Keyword.objects.filter(name='new-keyword').count(), 0)

        call_command('tracker_add_keyword', 'new-keyword', **{
            'is_default_keyword': True
        })

        keyword = Keyword.objects.get(name='new-keyword')
        # This keyword is given to all users
        self.assertEqual(
            EmailSettings.objects.filter(default_keywords=keyword).count(),
            EmailSettings.objects.count()
        )

    def test_create_default_keyword_existing_keyword(self):
        """
        Tests adding a default keyword which should be added to all
        subscriptions that have a different existing keyword.
        """
        existing_keyword = Keyword.objects.create(name='existing-keyword')
        # A user who added the existing keyword to its subscription keywords
        user1 = UserEmail.objects.create(email='subscription-user@domain.com')
        email_settings1 = EmailSettings.objects.create(user_email=user1)
        p = PackageName.objects.create(name='dummy-package')
        sub = Subscription.objects.create(email_settings=email_settings1,
                                          package=p)
        sub.keywords.add(existing_keyword)
        sub.save()
        # A user who added the existing keyword to its default keywords
        u = UserEmail.objects.create(email='defaultuser@domain.com')
        s = EmailSettings.objects.create(user_email=u)
        s.default_keywords.add(existing_keyword)
        s.save()
        # A user who does not have the existing keyword.
        user2 = UserEmail.objects.create(email='no-keyword@domain.com')
        email_settings2 = EmailSettings.objects.create(user_email=user2)
        # And is subscribed to a package without having the keyword
        sub = Subscription.objects.create(email_settings=email_settings2,
                                          package=p)
        sub.keywords.add(Keyword.objects.create(name='some-other-keyword'))
        # Sanity check - the keyword we want to add does not already exist
        self.assertEqual(Keyword.objects.filter(name='new-keyword').count(), 0)

        call_command('tracker_add_keyword', 'new-keyword', 'existing-keyword',
                     **{'is_default_keyword': True})

        new_keyword = Keyword.objects.get(name='new-keyword')
        # Every user has the keyword
        self.assertEqual(
            EmailSettings.objects.filter(default_keywords=new_keyword).count(),
            EmailSettings.objects.count()
        )
        # Subscription with the existing keyword has the new keyword
        sub = Subscription.objects.get(email_settings=email_settings1,
                                       package=p)
        self.assertIn(new_keyword, sub.keywords.all())
        # Subscription without the existing keyword not modified
        sub = Subscription.objects.get(email_settings=email_settings2,
                                       package=p)
        self.assertNotIn(new_keyword, sub.keywords.all())


class ProcessMailTests(TestCase):
    """Tests for the tracker_process_mail management command"""

    @mock.patch('distro_tracker.mail.management.commands.tracker_process_mail.'
                'MailQueue')
    def test_process_mail_command(self, mock_queue):
        """command is a simple wrapper around MailQueue.process_loop()"""
        call_command('tracker_process_mail')
        mock_queue.assert_called_with()
        mock_queue.return_value.process_loop.assert_called_with()
