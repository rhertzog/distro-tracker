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


class WhoCommandTest(EmailControlTest):
    """
    Tests for the who command.
    """
    def setUp(self):
        super(WhoCommandTest, self).setUp()
        self.package = Package.objects.create(name='dummy-package')
        self.users = [
            EmailUser.objects.create(email='user@domain.com'),
            EmailUser.objects.create(email='second-user@domain.com'),
        ]

    def get_command_message(self):
        """
        Helper function returns the message that the command should output
        before the list of all packages.
        """
        return "Here's the list of subscribers to package {package}".format(
            package=self.package)

    def test_list_all_subscribers(self):
        """
        Tests that all subscribers are output.
        """
        # Subscribe users
        for user in self.users:
            Subscription.objects.create(email_user=user, package=self.package)
        self.set_input_lines(['who ' + self.package.name])

        self.control_process()

        self.assert_in_response(self.get_command_message())
        # Check that all users are in the response
        for user in self.users:
            self.assert_in_response(user.email.rsplit('@', 1)[0])
        # Check that their exact addresses aren't
        for user in self.users:
            self.assert_not_in_response(user.email)

    def test_package_does_not_exist(self):
        """
        Tests the who command when the given package does not exist.
        """
        self.set_input_lines(['who no-exist'])

        self.control_process()

        self.assert_in_response('Package no-exist does not exist')

    def test_no_subscribers(self):
        """
        Tests the who command when the given package does not have any
        subscribers.
        """
        self.set_input_lines(['who ' + self.package.name])

        self.control_process()

        self.assert_in_response(
            'Package {package} does not have any subscribers'.format(
                package=self.package.name))
