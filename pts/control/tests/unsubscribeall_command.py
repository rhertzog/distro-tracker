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

from pts.core.models import PackageName, EmailUser, Subscription
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
        super(UnsubscribeallCommandTest, self).setUp()
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        self.package = PackageName.objects.create(name='dummy-package')
        self.other_package = PackageName.objects.create(name='other-package')
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

    def test_unsubscribeall_and_confirm(self):
        """
        Tests the unsubscribeall command with the confirmation.
        """
        old_subscriptions = [pkg.name for pkg in self.user.packagename_set.all()]
        self.set_input_lines(['unsubscribeall ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            "A confirmation mail has been sent to " + self.user.email)
        self.assert_confirmation_sent_to(self.user.email)
        match = self.regex_search_in_response(self.regexp)
        self.assertIsNotNone(match)

        self.reset_message()
        self.reset_outbox()
        self.set_input_lines([match.group(0)])

        self.control_process()

        self.assert_in_response('All your subscriptions have been terminated')
        self.assert_list_in_response(
            '{email} has been unsubscribed from {pkg}@{fqdn}'.format(
                email=self.user.email,
                pkg=package,
                fqdn=settings.PTS_FQDN)
            for package in sorted(old_subscriptions)
        )

    def test_unsubscribeall_no_subscriptions(self):
        """
        Tests the unsubscribeall command when the user is not subscribed to any
        packages.
        """
        self.user.subscription_set.all().delete()
        self.set_input_lines(['unsubscribeall ' + self.user.email])

        self.control_process()

        self.assert_warning_in_response(
            'User {email} is not subscribed to any packages'.format(
                email=self.user.email))

    def test_unsubscribeall_email_different_than_from(self):
        """
        Tests the unsubscribeall when the email given in the command is
        different than the one in the From header.
        """
        self.set_input_lines(['unsubscribeall ' + self.user.email])
        self.set_header('From', 'other-email@domain.com')

        self.control_process()

        self.assert_cc_contains_address(self.user.email)
        self.assert_confirmation_sent_to(self.user.email)

    def test_unsubscribeall_no_email_given(self):
        """
        Tests the unsubscribeall command when no email is given in the message.
        """
        self.set_input_lines(['unsubscribeall'])

        self.control_process()

        self.assert_confirmation_sent_to(self.user.email)
