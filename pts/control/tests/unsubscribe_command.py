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
from django.core import mail

from pts.core.utils import extract_email_address_from_header
from pts.core.models import Package, BinaryPackage
from pts.core.models import Subscription
import re

from pts.control.tests.common import EmailControlTest


class UnsubscribeFromPackageTest(EmailControlTest):
    """
    Tests for the unsubscribe from package story.
    """
    def setUp(self):
        EmailControlTest.setUp(self)
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        self.package = Package.objects.create(name='dummy-package')
        self.other_package = Package.objects.create(name='other-package')
        # The user is initially subscribed to the package
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.user_email_address)
        self.other_user = 'another-user@domain.com'
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.other_user)

        # Regular expression to extract the confirmation code from the body of
        # the response mail
        self.regexp = re.compile(r'^CONFIRM (.*)$', re.MULTILINE)

    def user_subscribed(self, email_address):
        """
        Helper method checks whether the given email is subscribed to the
        package.
        """
        return email_address in (
            user_email.email
            for user_email in self.package.subscriptions.all()
        )

    def assert_confirmation_sent_to(self, email_address):
        """
        Helper method checks whether a confirmation mail was sent to the
        given email address.
        """
        self.assertIn(
            True, (
                extract_email_address_from_header(msg.to[0]) == email_address
                for msg in mail.outbox[:-1]
            )
        )

    def assert_cc_contains_address(self, email_address):
        """
        Helper method which checks that the Cc header of the response contains
        the given email address.
        """
        response_mail = mail.outbox[-1]
        self.assertIn(
            email_address, (
                extract_email_address_from_header(email)
                for email in response_mail.cc
            )
        )

    def assert_correct_response_for_command(self, from_email, subscribe_email):
        """
        Helper method which checks that an unsubscribe command which came from
        ``from_email`` and unsubscribed ``subscribe_email`` has successfully
        executed.
        """
        self.assertTrue(len(mail.outbox) >= 1,
                        'No response email sent when one was expected.')
        self.assert_correct_response_headers()
        self.assert_in_response(
            'A confirmation mail has been sent to {email}'.format(
                email=subscribe_email))
        self.assert_confirmation_sent_to(subscribe_email)
        if from_email != subscribe_email:
            self.assert_cc_contains_address(subscribe_email)

    def add_binary_package(self, source_package, binary_package):
        """
        Helper method which creates a binary package for the given source
        package.
        """
        BinaryPackage.objects.create(
            name=binary_package,
            source_package=source_package)

    def add_unsubscribe_command(self, package, email=None):
        """
        Helper method which adds a subscribe command to the command message.
        """
        if not email:
            email = ''
        payload = self.message.get_payload() or ''
        commands = payload.splitlines()
        commands.append('unsubscribe ' + package + ' ' + email)
        self.set_input_lines(commands)

    def test_unsubscribe_and_confirm_normal(self):
        """
        Tests that the user is unsubscribed from the pacakge after running
        unsubscribe and confirm.
        """
        package_name = self.package.name
        self.add_unsubscribe_command(package_name, self.user_email_address)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)
        # User still not actually unsubscribed
        self.assertTrue(self.user_subscribed(self.user_email_address))
        # Check that the confirmation mail contains the confirmation code
        match = self.regex_search_in_response(self.regexp)
        self.assertIsNotNone(match)

        # Extract the code and send a confirmation mail
        self.reset_message()
        self.reset_outbox()
        self.set_input_lines([match.group(0)])
        self.control_process()

        self.assert_response_sent()
        self.assert_in_response(
            '{email} has been unsubscribed from {package}'.format(
                email=self.user_email_address,
                package=package_name))
        # User no longer subscribed
        self.assertFalse(self.user_subscribed(self.user_email_address))

    def test_unsubscribe_when_user_not_subscribed(self):
        """
        Tests the unsubscribe command when the user is not subscribed to the
        given package.
        """
        self.add_unsubscribe_command(self.other_package.name,
                                     self.user_email_address)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response(
            "{email} is not subscribed, you can't unsubscribe.".format(
                email=self.user_email_address))

    def test_unsubscribe_no_email_given(self):
        """
        Tests the unsubscribe command when there is no email address given.
        """
        self.add_unsubscribe_command(self.package.name)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)

    def test_unsubscribe_email_different_than_from(self):
        """
        Tests the unsubscribe command when the given email address is different
        than the From address of the received message.
        """
        self.add_unsubscribe_command(self.package.name,
                                     self.other_user)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.other_user)

    def test_unsubscribe_unexisting_source_package(self):
        """
        Tests the unsubscribe command when the given package is not an existing
        source package.
        """
        binary_package = 'binary-package'
        self.add_binary_package(self.package, binary_package)
        self.add_unsubscribe_command(binary_package)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)
        self.assert_in_response(
            'Warning: {package} is not a source package.'.format(
                package=binary_package))
        self.assert_in_response(
            '{package} is the source package '
            'for the {binary} binary package'.format(
                package=self.package.name,
                binary=binary_package))

    def test_unsubscribe_unexisting_source_or_binary_package(self):
        """
        Tests the unsubscribe command when the given package is neither an
        existing source nor an existing binary package.
        """
        binary_package = 'binary-package'
        self.add_unsubscribe_command(binary_package)

        self.control_process()

        self.assert_response_sent()
        self.assert_in_response(
            '{package} is neither a source package '
            'nor a binary package.'.format(package=binary_package))

    def test_unsubscribe_execute_once(self):
        """
        If the command message includes the same subscribe command multiple
        times, it is executed only once.
        """
        self.add_unsubscribe_command(self.package.name)
        self.add_unsubscribe_command(self.package.name, self.user_email_address)

        self.control_process()

        # Only one confirmation email required as the commands are equivalent
        self.assert_response_sent(2)
        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)
        self.assert_confirmation_sent_to(self.user_email_address)
