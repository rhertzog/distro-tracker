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

from pts.core.models import Package, EmailUser
from pts.core.models import Subscription

from pts.control.tests.common import EmailControlTest


class WhichCommandTest(EmailControlTest):
    """
    Tests for the which command.
    """
    def setUp(self):
        EmailControlTest.setUp(self)
        self.packages = [
            Package.objects.create(name='package' + str(i))
            for i in range(10)
        ]
        self.users = [
            EmailUser.objects.create(email='email' + str(i))
            for i in range(3)
        ]
        for i in range(5):
            Subscription.objects.create(
                package=self.packages[i],
                email_user=self.users[0]
            )
        Subscription.objects.create_for(
            package_name=self.packages[0].name,
            email=self.users[2].email,
            active=False)

    def get_subscriptions_for_user(self, user):
        return [
            subscription.package.name
            for subscription in user.subscription_set.all_active()
        ]

    def assert_correct_packages_output(self, user):
        """
        Helper method tests whether the response contains the correct output
        for the given user.
        """
        self.assert_response_sent()
        package_names = self.get_subscriptions_for_user(user)
        if not package_names:
            # This user is not subscribed to any packages
            # Make sure that no package was output.
            for package in Package.objects.all():
                self.assert_not_in_response('* ' + package.name)
            self.assert_in_response('No subscriptions found')
        else:
            for package_name in package_names:
                self.assert_in_response('* ' + package_name)

    def test_list_packages_subscribed_to(self):
        """
        Tests that the which command lists the right packages.
        """
        self.set_input_lines(['which ' + self.users[0].email])

        self.control_process()

        self.assert_correct_packages_output(self.users[0])

    def test_list_packages_no_email_given(self):
        """
        Tests that the which command lists the right packages when no email is
        given.
        """
        self.set_header('From', self.users[0].email)
        self.set_input_lines(['which'])

        self.control_process()

        self.assert_correct_packages_output(self.users[0])

    def test_list_packages_no_subscriptions(self):
        """
        Tests the which command when the user is not subscribed to any packages.
        """
        self.set_input_lines(['which ' + self.users[1].email])

        self.control_process()

        self.assert_correct_packages_output(self.users[1])

    def test_list_packages_no_active_subscriptions(self):
        """
        Tests the which command when the user does not have any active
        subscriptions.
        """
        self.set_input_lines(['which ' + self.users[2].email])

        self.control_process()

        self.assert_correct_packages_output(self.users[2])
