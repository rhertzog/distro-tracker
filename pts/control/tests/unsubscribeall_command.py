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

from pts.core.models import Package, EmailUser, Subscription
from pts.core.utils import extract_email_address_from_header
from django.core import mail

from pts.control.tests.common import EmailControlTest

import re

from django.conf import settings


class UnsubscribeallCommandTest(EmailControlTest):
    """
    Tests for the unsubscribeall command.
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
        Subscription.objects.create_for(
            package_name=self.other_package.name,
            email=self.user_email_address,
            active=False)
        self.user = EmailUser.objects.get(email=self.user_email_address)

        # Regular expression to extract the confirmation code from the body of
        # the response mail
        self.regexp = re.compile(r'^CONFIRM (.*)$', re.MULTILINE)

    def assert_correct_response(self, number_of_messages=2, user=None):
        if not user:
            user = self.user

        self.assert_response_sent(number_of_messages)
        self.assert_correct_response_headers()
        self.assert_in_response(
            "A confirmation mail has been sent to " + user.email)

    def assert_correct_confirmation(self, confirmation_number=0):
        match = self.regex_search_in_response(self.regexp, confirmation_number)
        self.assertIsNotNone(match)

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

    def confirm_unsubscribeall(self, confirmation_number=0):
        match = self.regex_search_in_response(self.regexp, confirmation_number)
        self.reset_message()
        self.reset_outbox()
        self.set_input_lines([match.group(0)])
        old_subscriptions = [
            package.name
            for package in self.user.package_set.all()
        ]

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assertEqual(self.user.subscription_set.count(), 0)
        self.assert_in_response('All your subscriptions have been terminated')
        self.assert_list_in_response(
            '{email} has been unsubscribed from {pkg}@{fqdn}'.format(
                email=self.user.email,
                pkg=package,
                fqdn=settings.PTS_FQDN)
            for package in sorted(old_subscriptions)
        )

    def test_unsubscribeall_and_confirm(self):
        """
        Tests the unsubscribeall command with the confirmation.
        """
        self.set_input_lines(['unsubscribeall ' + self.user.email])

        self.control_process()

        self.assert_correct_response()
        self.assert_correct_confirmation()

        self.confirm_unsubscribeall()

    def test_unsubscribeall_no_subscriptions(self):
        """
        Tests the unsubscribeall command when the user is not subscribed to any
        packages.
        """
        self.user.subscription_set.all().delete()
        self.set_input_lines(['unsubscribeall ' + self.user.email])

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_warning_in_response(
            'User {email} is not subscribed to any package'.format(
                email=self.user.email))

    def test_unsubscribeall_email_different_than_from(self):
        """
        Tests the unsubscribeall when the email given in the command is
        different than the one in the From header.
        """
        self.set_input_lines(['unsubscribeall ' + self.user.email])
        self.set_header('From', 'other-email@domain.com')

        self.control_process()

        self.assert_correct_response()
        self.assert_cc_contains_address(self.user.email)
        self.assert_header_equal('To', self.user.email, 0)

    def test_unsubscribeall_and_confirm_no_email_given(self):
        """
        Tests the unsubscribeall command when no email is given in the message.
        """
        self.set_input_lines(['unsubscribeall'])

        self.control_process()

        self.assert_correct_response()
        self.assert_correct_confirmation()

        self.confirm_unsubscribeall()
