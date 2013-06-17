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
from pts.control.management.commands.pts_unsubscribe_all import Command

from pts.core.models import Package, EmailUser, Subscription

import io


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
        cmd = Command()
        cmd.stdout = io.StringIO()
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
