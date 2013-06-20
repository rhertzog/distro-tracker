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
        super(WhichCommandTest, self).setUp()
        self.packages = [
            Package.objects.create(name='package' + str(i))
            for i in range(10)
        ]
        self.user = EmailUser.objects.create(email='user@domain.com')

    def assert_no_subscriptions_in_response(self):
        self.assert_in_response('No subscriptions found')

    def test_list_packages_subscribed_to(self):
        """
        Tests that the which command lists the right packages.
        """
        subscriptions = [
            Subscription.objects.create(
                package=self.packages[i],
                email_user=self.user
            )
            for i in range(5)
        ]
        self.set_input_lines(['which ' + self.user.email])

        self.control_process()

        self.assert_list_in_response(sub.package.name for sub in subscriptions)

    def test_list_packages_no_email_given(self):
        """
        Tests that the which command lists the right packages when no email is
        given.
        """
        subscriptions = [
            Subscription.objects.create(
                package=self.packages[i],
                email_user=self.user
            )
            for i in range(5)
        ]
        self.set_header('From', self.user.email)
        self.set_input_lines(['which'])

        self.control_process()

        self.assert_list_in_response(sub.package.name for sub in subscriptions)

    def test_list_packages_no_subscriptions(self):
        """
        Tests the which command when the user is not subscribed to any packages.
        """
        self.set_input_lines(['which ' + self.user.email])

        self.control_process()

        self.assert_no_subscriptions_in_response()

    def test_list_packages_no_active_subscriptions(self):
        """
        Tests the which command when the user does not have any active
        subscriptions.
        """
        Subscription.objects.create(
            package=self.packages[0],
            email_user=self.user,
            active=False)
        self.set_input_lines(['which ' + self.user.email])

        self.control_process()

        self.assert_no_subscriptions_in_response()
