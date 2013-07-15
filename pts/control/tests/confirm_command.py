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
from pts.core.utils import pts_render_to_string
from pts.core.models import PackageName, EmailUser, Subscription
import re

from pts.control.tests.common import EmailControlTest
from pts.control.models import CommandConfirmation


class ConfirmationTests(EmailControlTest):
    """
    Tests the command confirmation mechanism.
    """
    def setUp(self):
        super(ConfirmationTests, self).setUp()
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        # Regular expression to extract the confirmation code from the body of
        # the response mail
        self.regexp = re.compile(r'^CONFIRM (.*)$', re.MULTILINE)
        self.packages = [
            PackageName.objects.create(name='dummy-package'),
            PackageName.objects.create(name='other-package'),
        ]

    def user_subscribed(self, email_address, package_name):
        """
        Helper method checks whether the given email is subscribed to the
        package.
        """
        return EmailUser.objects.is_user_subscribed_to(
            user_email=email_address,
            package_name=package_name)

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

    def test_multiple_commands_single_confirmation_email(self):
        """
        Tests that multiple commands which require confirmation cause only a
        single confirmation email.
        """
        commands = [
            'subscribe ' + package.name + ' ' + self.user_email_address
            for package in self.packages
        ]
        self.set_input_lines(commands)

        self.control_process()

        # A control commands response and confirmation email sent
        self.assert_response_sent(2)
        self.assert_confirmation_sent_to(self.user_email_address)
        # Contains the confirmation key
        self.assertIsNotNone(self.regex_search_in_response(self.regexp))
        # A confirmation key really created
        self.assertEqual(CommandConfirmation.objects.count(), 1)
        # Check the commands associated with the confirmation object.
        c = CommandConfirmation.objects.all()[0]
        self.assertEqual('\n'.join(commands), c.commands)
        for command in commands:
            self.assert_in_response(command)
        # Finally make sure the commands did not actually execute
        self.assertEqual(Subscription.objects.filter(active=True).count(), 0)

    def test_subscribe_command_confirmation_message(self):
        """
        Tests that the custom confirmation messages for commands are correctly
        included in the confirmation email.
        """
        Subscription.objects.create_for(
            email=self.user_email_address,
            package_name=self.packages[1].name)
        commands = [
            'unsubscribeall',
            'unsubscribe ' + self.packages[1].name,
            'subscribe ' + self.packages[0].name,
        ]
        self.set_input_lines(commands)

        self.control_process()

        expected_messages = [
            pts_render_to_string(
                'control/email-unsubscribeall-confirmation.txt'
            ),
            pts_render_to_string(
                'control/email-unsubscribe-confirmation.txt', {
                    'package': self.packages[1].name,
                }
            ),
            pts_render_to_string(
                'control/email-subscription-confirmation.txt', {
                    'package': self.packages[0].name,
                }
            )
        ]
        c = CommandConfirmation.objects.all()[0]
        self.assert_response_equal(
            pts_render_to_string(
                'control/email-confirmation-required.txt', {
                    'command_confirmation': c,
                    'confirmation_messages': expected_messages,
                }
            ),
            response_number=0
        )

    def test_multiple_commands_confirmed(self):
        """
        Tests that multiple commands are actually confirmed by a single key.
        """
        commands = [
            'subscribe ' + package.name + ' ' + self.user_email_address
            for package in self.packages
        ]
        c = CommandConfirmation.objects.create_for_commands(commands)
        self.set_input_lines(['CONFIRM ' + c.confirmation_key])

        self.control_process()

        self.assert_response_sent()
        for package in self.packages:
            self.assertTrue(
                self.user_subscribed(self.user_email_address, package.name))
        for command in commands:
            self.assert_command_echo_in_response(command)
        # Key no longer usable
        self.assertEqual(CommandConfirmation.objects.count(), 0)

    def test_multiple_commands_per_user(self):
        """
        Tests that if multiple emails should receive a confirmation email for
        some commands, each of them gets only one.
        """
        commands = []
        commands.extend([
            'subscribe ' + package.name + ' ' + self.user_email_address
            for package in self.packages
        ])
        other_user = 'other-user@domain.com'
        commands.extend([
            'subscribe ' + package.name + ' ' + other_user
            for package in self.packages
        ])
        self.set_input_lines(commands)

        self.control_process()

        # A control commands response and confirmation emails sent
        self.assert_response_sent(3)
        self.assert_confirmation_sent_to(self.user_email_address)
        self.assert_confirmation_sent_to(other_user)
        self.assertEqual(CommandConfirmation.objects.count(), 2)
        # Control message CCed to both of them.
        self.assert_cc_contains_address(self.user_email_address)
        self.assert_cc_contains_address(other_user)

    def test_same_command_repeated(self):
        """
        Tests that when the same command is repeated in the command email, it
        is included just once in the confirmation email.
        """
        package = self.packages[0]
        self.set_input_lines([
            'subscribe ' + package.name + ' ' + self.user_email_address,
            'subscribe ' + package.name + ' ' + self.user_email_address,
        ])

        self.control_process()

        self.assert_response_sent(2)
        c = CommandConfirmation.objects.all()[0]
        self.assertEqual(
            'subscribe ' + package.name + ' ' + self.user_email_address,
            c.commands)

    def test_confirm_only_if_needs_confirmation(self):
        """
        Tests that only the commands which need confirmation are included in
        the confirmation email.
        """
        Subscription.objects.create_for(
            email=self.user_email_address,
            package_name=self.packages[1].name)
        package = self.packages[0]
        self.set_input_lines([
            'unsubscribeall',
            'which',
            'help',
            'subscribe ' + package.name + ' ' + self.user_email_address,
            'who',
            'keywords',
            'unsubscribe ' + self.packages[1].name + ' ' + self.user_email_address,
        ])

        self.control_process()

        self.assert_response_sent(2)
        c = CommandConfirmation.objects.all()[0]
        expected = '\n'.join([
            'unsubscribeall ' + self.user_email_address,
            'subscribe ' + package.name + ' ' + self.user_email_address,
            'unsubscribe ' + self.packages[1].name + ' ' + self.user_email_address,
        ])
        self.assertEqual(expected, c.commands)

    def test_unknown_confirmation_key(self):
        """
        Tests the confirm command when an unknown key is given.
        """
        self.set_input_lines(['CONFIRM asdf'])

        self.control_process()

        self.assert_response_sent()
        self.assert_error_in_response('Confirmation failed: Unknown key')
