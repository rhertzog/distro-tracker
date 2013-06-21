# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.test import TestCase
from pts.control.management.commands.pts_unsubscribe_all import (
    Command as UnsubscribeCommand)
from pts.control.management.commands.pts_dump_subscribers import (
    Command as DumpCommand)

from pts.core.models import Package, EmailUser, Subscription

from django.utils import six
import json


class UnsubscribeAllManagementCommand(TestCase):
    def setUp(self):
        self.packages = [
            Package.objects.create(name='dummy-package'),
            Package.objects.create(name='second-package'),
        ]
        self.user = EmailUser.objects.create(email='email-user@domain.com')
        for package in self.packages:
            Subscription.objects.create(package=package, email_user=self.user)

        self.nosub_user = EmailUser.objects.create(email='nosub@dom.com')

    def call_command(self, *args, **kwargs):
        cmd = UnsubscribeCommand()
        cmd.stdout = six.StringIO()
        cmd.handle(*args, **kwargs)
        self.out = cmd.stdout.getvalue()

    def assert_unsubscribed_user(self):
        for package in self.packages:
            self.assertIn(
                'Unsubscribing {email} from {package}'.format(
                    email=self.user.email, package=package.name),
                self.out)
        self.assertEqual(self.user.subscription_set.count(), 0)

    def assert_no_subscriptions(self):
        self.assertIn(
            'Email {email} is not subscribed to any packages.'.format(
                email=self.nosub_user),
            self.out)

    def assert_user_doesnt_exist(self, user):
        self.assertIn(
            'Email {email} is not subscribed to any packages. '
            'Bad email?'.format(
                email=user),
            self.out)

    def test_unsubscribe_user(self):
        """
        Tests the management command ``pts_unsubscribe_all`` when a user with
        subscriptions is given.
        """
        self.call_command(self.user.email)

        self.assert_unsubscribed_user()

    def test_unsubscribe_doesnt_exist(self):
        """
        Tests the management command ``pts_unsubscribe_all`` when the given
        user does not exist.
        """
        self.call_command('no-exist')

        self.assert_user_doesnt_exist('no-exist')

    def test_unsubscribe_no_subscriptions(self):
        """
        Tests the management command ``pts_unsubscribe_all`` when the given
        user is not subscribed to any packages.
        """
        self.call_command(self.nosub_user)

        self.assert_no_subscriptions()

    def test_unsubscribe_multiple_user(self):
        """
        Tests the management command ``pts_unsubscribe_all`` when multiple
        users are passed to it.
        """
        args = ['no-exist', self.nosub_user.email, self.user.email]
        self.call_command(*args)

        self.assert_unsubscribed_user()
        self.assert_user_doesnt_exist('no-exist')
        self.assert_no_subscriptions()


class DumpSubscribersManagementCommandTest(TestCase):
    def setUp(self):
        self.packages = [
            Package.objects.create(name='package' + str(i))
            for i in range(5)
        ]
        self.users = [
            EmailUser.objects.create(email='user@domain.com'),
            EmailUser.objects.create(email='other-user@domain.com'),
        ]

    def assert_warning_in_output(self, text):
        self.assertIn('Warning: ' + text, self.out)

    def assert_package_in_output(self, package):
        self.assertIn('{package} => ['.format(package=package), self.out)

    def assert_user_list_in_output(self, users):
        self.assertIn('[ ' + ' '.join(str(user) for user in users) + ' ]',
                      self.out)

    def call_command(self, *args, **kwargs):
        if 'inactive' not in kwargs:
            kwargs['inactive'] = False
        if 'json' not in kwargs:
            kwargs['json'] = False
        cmd = DumpCommand()
        cmd.stdout = six.StringIO()
        cmd.handle(*args, **kwargs)
        self.out = cmd.stdout.getvalue()

    def test_dump_one_package(self):
        user = self.users[0]
        package = self.packages[0]
        Subscription.objects.create(email_user=user, package=package)

        self.call_command()

        self.assert_package_in_output(package)
        self.assert_user_list_in_output([user])

    def test_dump_all_active(self):
        # Subscribe the users
        for user in self.users:
            for package in self.packages:
                Subscription.objects.create(email_user=user, package=package)

        self.call_command()

        for package in self.packages:
            self.assert_package_in_output(package)
        self.assert_user_list_in_output(self.users)

    def test_dump_inactive(self):
        user = self.users[0]
        package = self.packages[0]
        Subscription.objects.create(email_user=user, package=package,
                                    active=False)

        self.call_command(inactive=True)

        self.assert_package_in_output(package)
        self.assert_user_list_in_output([user])

    def test_dump_json(self):
        # Subscribe all the users
        for user in self.users:
            for package in self.packages:
                Subscription.objects.create(email_user=user, package=package)

        self.call_command(json=True)

        output = json.loads(self.out)
        # All packages in output?
        for package in self.packages:
            self.assertIn(str(package), output)
        # All users in each output list?
        for subscribers in output.values():
            for user in self.users:
                self.assertIn(str(user), subscribers)

    def test_dump_package_does_not_exist(self):
        self.call_command('does-not-exist')

        self.assert_warning_in_output('does-not-exist does not exist')
