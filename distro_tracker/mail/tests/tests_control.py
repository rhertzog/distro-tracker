# -*- coding: utf-8 -*-

# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for :mod:`distro_tracker.mail.tracker_control`.
"""
from __future__ import unicode_literals
from django.conf import settings
from distro_tracker.test import TestCase
from django.core import mail

from distro_tracker.mail import control
from distro_tracker.core.utils import distro_tracker_render_to_string
from distro_tracker.core.utils import extract_email_address_from_header
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.models import PackageName, UserEmail, Subscription
from distro_tracker.core.models import EmailSettings
from distro_tracker.core.models import Keyword
from distro_tracker.core.models import Team
from distro_tracker.core.models import BinaryPackageName
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import SourcePackage
from distro_tracker.accounts.models import User
from distro_tracker.mail.models import CommandConfirmation
from distro_tracker.mail.control.commands import UNIQUE_COMMANDS

from email import encoders
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.utils import make_msgid
from datetime import timedelta

import re


DISTRO_TRACKER_CONTACT_EMAIL = settings.DISTRO_TRACKER_CONTACT_EMAIL
DISTRO_TRACKER_CONTROL_EMAIL = settings.DISTRO_TRACKER_CONTROL_EMAIL
MAX_ALLOWED_ERRORS = settings.DISTRO_TRACKER_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS


class EmailControlTest(TestCase):
    def control_process(self):
        """
        Helper method. Passes the constructed control message to the control
        processor.
        """
        control.process(self.message)

    def setUp(self):
        self.reset_message()

    def set_default_headers(self):
        """
        Helper method which adds the default headers for each test message.
        """
        self.message.add_header('From', 'John Doe <john.doe@unknown.com>')
        self.message.add_header('To', DISTRO_TRACKER_CONTROL_EMAIL)
        self.message.add_header('Subject', 'Commands')
        self.message.add_header('Message-ID', make_msgid())

    def set_header(self, header_name, header_value):
        """
        Helper method which sets the given value for the given header.

        :param header_name: The name of the header to set
        :param header_value: The value of the header to set
        """
        if header_name in self.message:
            del self.message[header_name]
        self.message.add_header(header_name, header_value)

    def set_input_lines(self, lines):
        """
        Sets the lines of the message body which represent sent commands.

        :param lines: All lines of commands
        :param type: iterable
        """
        payload = '\n'.join(lines)
        if self.multipart:
            plain_text = MIMEText('plain')
            plain_text.set_payload(payload)
            self.message.attach(plain_text)
        else:
            self.message.set_payload(payload)

    def make_multipart(self, alternative=False):
        """
        Helper method which converts the test message into a multipart message.
        """
        if alternative:
            self.message = MIMEMultipart('alternative')
        else:
            self.message = MIMEMultipart()
        self.set_default_headers()
        self.multipart = True

    def add_part(self, mime_type, subtype, data):
        """
        Adds the given part to the test message.

        :param mime_type: The main MIME type of the new part
        :param subtype: The MIME subtype of the new part
        :param data: The payload of the part
        """
        part = MIMEBase(mime_type, subtype)
        part.set_payload(data)
        if mime_type != 'text':
            encoders.encode_base64(part)
        self.message.attach(part)

    def reset_message(self):
        """
        Helper method resets any changes made to the test message.
        """
        self.message = Message()
        self.multipart = False
        self.set_default_headers()

    def make_comment(self, text):
        """
        Helper function which creates a comment from the given text.
        """
        return '# ' + text

    def assert_response_sent(self, number_of_responses=1):
        """
        Helper method which asserts that the expected number of responses is
        sent.

        :param number_of_responses: The expected number of responses.
        """
        self.assertEqual(len(mail.outbox), number_of_responses)

    def assert_response_not_sent(self):
        """
        Helper method which asserts that no responses were sent.
        """
        self.assertEqual(len(mail.outbox), 0)

    def assert_in_response(self, text, response_number=-1):
        """
        Helper method which asserts that the given text is found in the given
        response message.

        :param text: The text which needs to be found in the response.
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        self.assertTrue(mail.outbox)
        out_mail = mail.outbox[response_number]
        self.assertIn(text, out_mail.body)

    def assert_line_in_response(self, line, response_number=-1):
        """
        Helper method which asserts that the given full line of text is found
        in the given response message.

        :param line: The line of text which needs to be found in the response.
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        self.assertTrue(mail.outbox)
        out_mail = mail.outbox[response_number]
        self.assertIn(line, out_mail.body.splitlines())

    def assert_line_not_in_response(self, line, response_number=-1):
        """
        Helper method which asserts that the given full line of text is not
        found in the given response message.

        :param line: The line of text which needs to be found in the response.
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        self.assertTrue(mail.outbox)
        out_mail = mail.outbox[response_number]
        self.assertNotIn(line, out_mail.body.splitlines())

    def get_list_item(self, item, bullet='*'):
        """
        Helper method which returns a representation of a list item.

        :param item: The list item's content
        :type item: string
        :param bullet: The character used as the "bullet" of the list.
        """
        return bullet + ' ' + str(item)

    def assert_list_in_response(self, items, bullet='*'):
        """
        Helper method which asserts that a list of items is found in the
        response.
        """
        self.assert_in_response('\n'.join(
            self.get_list_item(item, bullet)
            for item in items
        ))

    def assert_list_item_in_response(self, item, bullet='*'):
        """
        Helper method which asserts that a single list item is found in the
        response.
        """
        self.assert_line_in_response(self.get_list_item(item, bullet))

    def assert_list_item_not_in_response(self, item, bullet='*'):
        """
        Helper method which asserts that a single list item is not found in the
        response.
        """
        self.assert_line_not_in_response(self.get_list_item(item, bullet))

    def assert_not_in_response(self, text, response_number=-1):
        """
        Helper method which asserts that the given text is not found in the
        given response message.

        :param text: The text which needs to be found in the response.
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        out_mail = mail.outbox[response_number]
        self.assertNotIn(text, out_mail.body)

    def assert_response_equal(self, text, response_number=-1):
        """
        Helper method which asserts that the response is completely identical
        to the given text.

        :param text: The text which the response is compared to.
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        out_mail = mail.outbox[response_number]
        self.assertEqual(text, out_mail.body)

    def assert_header_equal(self, header_name, header_value,
                            response_number=-1):
        """
        Helper method which asserts that a particular response's
        header value is equal to an expected value.

        :param header_name: The name of the header to be tested
        :param header_value: The expected value of the header
        :param response_number: The index number of the response message.
            Standard Python indexing applies, which means that -1 means the
            last sent message.
        """
        out_mail = mail.outbox[response_number].message()
        self.assertEqual(out_mail[header_name], header_value)

    def assert_command_echo_in_response(self, command):
        """
        Helper method which asserts that a given command's echo is found in
        the response.
        """
        self.assert_in_response('> ' + command)

    def assert_command_echo_not_in_response(self, command):
        """
        Helper method which asserts that a given command's echo is not found
        in the response.
        """
        self.assert_not_in_response('> ' + command)

    def assert_warning_in_response(self, text):
        """
        Helper method which asserts that a particular warning is found in the
        response.

        :param text: The text of the warning message.
        """
        self.assert_in_response("Warning: " + text)

    def assert_error_in_response(self, text):
        """
        Helper method which asserts that a particular error is found in the
        response.

        :param text: The text of the error message.
        """
        self.assert_in_response("Error: " + text)

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

    def reset_outbox(self):
        """
        Helper method which resets the structure containing all outgoing
        emails.
        """
        mail.outbox = []

    def regex_search_in_response(self, regexp, response_number=0):
        """
        Helper method which performs a regex search in a response.
        """
        return regexp.search(mail.outbox[response_number].body)


class ControlBotBasic(EmailControlTest):
    def test_basic_headers(self):
        """
        Tests if the proper headers are set for the reply message, that the
        output contains original lines prepended with '>'
        """
        input_lines = [
            "#command",
            "   thanks",
        ]
        self.set_header('Subject', 'Commands')
        self.set_input_lines(input_lines)

        self.control_process()

        self.assert_response_sent()
        self.assert_header_equal('Subject', 'Re: Commands')
        self.assert_header_equal('X-Loop', DISTRO_TRACKER_CONTROL_EMAIL)
        self.assert_header_equal('To', self.message['From'])
        self.assert_header_equal('From', DISTRO_TRACKER_CONTACT_EMAIL)
        self.assert_header_equal('In-Reply-To', self.message['Message-ID'])
        self.assert_header_equal(
            'References',
            ' '.join((self.message.get('References', ''),
                      self.message['Message-ID']))
        )

    def test_response_when_no_subject(self):
        """
        Tests that the subject of the response when there is no subject set in
        the request is correct.
        """
        self.set_input_lines(["thanks"])
        self.set_header('Subject', '')
        self.set_input_lines(['help'])

        self.control_process()

        self.assert_header_equal('Subject', 'Re: Your mail')

    def test_basic_echo_commands(self):
        """
        Tests that commands are echoed in the response.
        """
        input_lines = [
            "#command",
            "   thanks",
        ]
        self.set_header('Subject', 'Commands')
        self.set_input_lines(input_lines)

        self.control_process()

        for line in input_lines:
            self.assert_command_echo_in_response(line.strip())

    def test_not_plaintext(self):
        """
        Tests that the response to a non-plaintext message is a warning email.
        """
        self.make_multipart()
        self.add_part('application', 'octet-stream', b'asdf')

        self.control_process()

        self.assert_response_sent()
        self.assert_response_equal(distro_tracker_render_to_string(
            'control/email-plaintext-warning.txt'))

    def test_multipart_with_plaintext(self):
        """
        Tests that the response to a multipart message which contains a
        text/plain part is correct.
        """
        self.make_multipart(alternative=True)
        input_lines = [
            '#command',
            'thanks',
        ]
        self.set_input_lines(input_lines)
        self.add_part('text', 'html', "#command\nthanks")

        self.control_process()

        self.assert_response_sent()
        for line in input_lines:
            self.assert_command_echo_in_response(line.strip())

    def test_empty_no_response(self):
        """
        Tests that there is no response to an empty message.
        """
        self.set_input_lines([])

        self.control_process()

        self.assert_response_not_sent()

    def test_loop_no_response(self):
        """
        Tests that there is no response if the message's X-Loop is set to
        DISTRO_TRACKER_CONTROL_EMAIL
        """
        self.set_header('X-Loop', 'something-else')
        self.set_header('X-Loop', DISTRO_TRACKER_CONTROL_EMAIL)
        self.set_input_lines(['thanks'])

        self.control_process()

        self.assert_response_not_sent()

    def test_no_valid_command_no_response(self):
        """
        Tests that there is no response for a message which does not contain
        any valid commands.
        """
        self.set_input_lines(['Some text', 'Some more text'])

        self.control_process()

        self.assert_response_not_sent()

    def test_stop_after_five_garbage_lines(self):
        """
        Tests that processing stops after encountering five garbage lines.
        """
        self.set_input_lines(
            ['help'] + ['garbage'] * MAX_ALLOWED_ERRORS + ['#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_not_in_response('#command')

    def test_stop_on_thanks_or_quit(self):
        """
        Tests that processing stops after encountering the thanks or quit
        command.
        """
        self.set_input_lines(['thanks', '#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('thanks')
        self.assert_in_response("Stopping processing here.")
        self.assert_command_echo_not_in_response('#command')

    def test_blank_line_skip(self):
        """
        Tests that processing skips any blank lines in the message. They are
        not considered garbage.
        """
        self.set_input_lines(['help', ''] + ['   '] * 5 + ['#comment'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('#comment')

    def test_comment_line_skip(self):
        """
        Tests that processing skips commented lines and that they are not
        considered garbage.
        """
        self.set_input_lines(
            [self.make_comment(command)
             for command in ['comment'] * MAX_ALLOWED_ERRORS] + ['help']
        )

        self.control_process()

        self.assert_command_echo_in_response('help')

    def test_utf8_message(self):
        """
        Tests that the bot sends replies to utf-8 encoded messages.
        """
        lines = ['üšßč', '한글ᥡ╥ສए', 'help']
        self.set_input_lines(lines)
        self.message.set_charset('utf-8')

        self.control_process()

        self.assert_response_sent()
        for line in lines:
            self.assert_command_echo_in_response(line)

    def test_subject_command(self):
        """
        Tests that a command given in the subject of the message is executed.
        """
        self.set_header('Subject', 'help')
        self.set_input_lines([])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('# Message subject')
        self.assert_command_echo_in_response('help')

    def test_ensure_no_failure_with_multiline_subject(self):
        """Non-regression test for a failure with multi-line subjects"""
        self.set_header('Subject', '=?utf-8?B?UkU66L2m6Ze05Li75Lu75LiO54+t6ZW'
                        '/5Yiw5bqV5piv5LiN5piv55yf5q2j55qE6aKG5a+8?=\n\t'
                        '=?utf-8?B?Ow==?=')
        self.set_input_lines(['help'])

        self.control_process()

    def test_end_processing_on_signature_delimiter(self):
        """
        Tests that processing commands halts when the signature delimiter is
        reached (--)
        """
        self.set_input_lines(['help', '--', '# command'])

        self.control_process()

        self.assert_command_echo_not_in_response('# command')


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
        user_email = get_or_none(UserEmail, email=email_address)
        if not user_email:
            return False
        return user_email.emailsettings.is_subscribed_to(package=package_name)

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
            distro_tracker_render_to_string(
                'control/email-unsubscribeall-confirmation.txt'
            ),
            distro_tracker_render_to_string(
                'control/email-unsubscribe-confirmation.txt', {
                    'package': self.packages[1].name,
                }
            ),
            distro_tracker_render_to_string(
                'control/email-subscription-confirmation.txt', {
                    'package': self.packages[0].name,
                }
            )
        ]
        c = CommandConfirmation.objects.all()[0]
        self.assert_response_equal(
            distro_tracker_render_to_string(
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
            'unsubscribe ' + self.packages[1].name + ' ' +
            self.user_email_address,
        ])

        self.control_process()

        self.assert_response_sent(2)
        c = CommandConfirmation.objects.all()[0]
        expected = '\n'.join([
            'unsubscribeall ' + self.user_email_address,
            'subscribe ' + package.name + ' ' + self.user_email_address,
            'unsubscribe ' + self.packages[1].name + ' ' +
            self.user_email_address,
        ])
        self.assertEqual(expected, c.commands)

    def test_unknown_confirmation_key(self):
        """
        Tests the confirm command when an unknown key is given.
        """
        self.set_input_lines(['CONFIRM asdf'])

        self.control_process()

        self.assert_response_sent()
        self.assert_error_in_response('Confirmation failed: unknown key')


class HelpCommandTest(EmailControlTest):
    """
    Tests for the help command.
    """
    def get_all_help_command_descriptions(self):
        """
        Helper method returning the description of all commands.
        """
        return (cmd.META.get('description', '') for cmd in UNIQUE_COMMANDS)

    def test_help_command(self):
        """
        Tests that the help command returns all the available commands and
        their descriptions.
        """
        self.set_input_lines(['help'])

        self.control_process()

        self.assert_in_response(distro_tracker_render_to_string(
            'control/help.txt',
            {'descriptions': self.get_all_help_command_descriptions()}
        ))


class KeywordCommandHelperMixin(object):
    """
    Contains some methods which are used for testing all forms of the keyword
    command.
    """
    def assert_keywords_in_response(self, keywords):
        """
        Checks if the given keywords are found in the response.
        """
        for keyword in keywords:
            self.assert_list_item_in_response(keyword)

    def assert_keywords_not_in_response(self, keywords):
        """
        Checks that the given keywords are not found in the response.
        """
        for keyword in keywords:
            self.assert_list_item_not_in_response(keyword)


class KeywordCommandSubscriptionSpecificTest(EmailControlTest,
                                             KeywordCommandHelperMixin):
    """
    Tests for the keyword command when modifying subscription specific
    keywords.
    """
    def setUp(self):
        super(KeywordCommandSubscriptionSpecificTest, self).setUp()

        # Setup a subscription
        self.package = PackageName.objects.create(name='dummy-package')
        self.user = UserEmail.objects.create(email='user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_settings=self.email_settings
        )
        self.default_keywords = set(
            keyword.name
            for keyword in self.subscription.keywords.filter(default=True))

        self.commands = []
        self.set_header('From', self.user.email)

    def _to_command_string(self, command):
        """
        Helper method turning a tuple representing a keyword command into a
        string.
        """
        return ' '.join(
            command[:-1] + (', '.join(command[-1]),)
        )

    def add_keyword_command(self, package, operator, keywords, email=None,
                            use_tag=False):
        if email is None:
            email = ''

        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            package,
            email,
            operator,
            keywords,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def get_new_list_of_keywords_text(self, package, email):
        """
        Returns the status text which should precede a new list of keywords.
        """
        return (
            "Here's the new list of accepted keywords associated to package\n"
            "{package} for {address} :".format(package=package,
                                               address=self.user.email)
        )

    def assert_error_user_not_subscribed_in_response(self, email, package):
        """
        Checks whether an error saying the user is not subscribed to a package
        is in the response.
        """
        self.assert_error_in_response(
            '{email} is not subscribed to the package {package}'.format(
                email=email, package=package)
        )

    def assert_subscription_keywords_equal(self, keywords):
        """
        Asserts that the subscription of the test user to the test package is
        equal to the given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_settings=self.email_settings
        )
        all_keywords = self.subscription.keywords.all()
        self.assertEqual(all_keywords.count(), len(keywords))
        for keyword in all_keywords:
            self.assertIn(keyword.name, keywords)

    def assert_subscription_has_keywords(self, keywords):
        """
        Check if the subscription of the test user to the test package has the
        given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_settings=self.email_settings
        )
        all_keywords = self.subscription.keywords.all()
        for keyword in keywords:
            self.assertIn(Keyword.objects.get(name=keyword), all_keywords)

    def assert_subscription_not_has_keywords(self, keywords):
        """
        Assert that the subscription of the test user to the test package does
        not have the given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_settings=self.email_settings
        )
        all_keywords = self.subscription.keywords.all()
        for keyword in keywords:
            self.assertNotIn(Keyword.objects.get(name=keyword), all_keywords)

    def test_add_keyword_to_subscription(self):
        """
        Tests the keyword command version which should add a keyword to the
        subscription.
        """
        keywords = ['vcs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_keywords_in_response(keywords)
        self.assert_subscription_has_keywords(keywords)

    def test_remove_keyword_from_subscription(self):
        """
        Tests the keyword command version which should remove a keyword from a
        subscription.
        """
        keywords = ['bts']
        self.add_keyword_command(self.package.name,
                                 '-',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_keywords_not_in_response(keywords)
        self.assert_subscription_not_has_keywords(keywords)

    def test_set_keywords_for_subscription(self):
        """
        Tests the keyword command version which should set a new keyword list
        for a subscription.
        """
        keywords = ['vcs', 'bts']
        self.add_keyword_command(self.package.name,
                                 '=',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_subscription_keywords_equal(keywords)

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        self.add_keyword_command(self.package.name, '+', ['vcs'])

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(['vcs'])
        self.assert_subscription_has_keywords(['vcs'])

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when the given keyword does not exist.
        """
        self.add_keyword_command(self.package.name, '+', ['no-exist'])

        self.control_process()

        self.assert_warning_in_response('no-exist is not a valid keyword')
        # Subscription has not changed.
        self.assert_keywords_in_response(self.default_keywords)
        self.assert_subscription_keywords_equal(self.default_keywords)

    def test_keyword_add_subscription_not_confirmed(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription (it is pending).
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, '+', ['vcs'])

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(['vcs'])
        self.assert_subscription_has_keywords(['vcs'])

    def test_keyword_add_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('package-no-exist', '+', ['vcs'])

        self.control_process()

        self.assert_in_response('Package package-no-exist does not exist')
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))

    def test_keyword_user_not_subscribed(self):
        """
        Tests the keyword command when the user is not subscribed to the given
        package.
        """
        other_user = UserEmail.objects.create(email='other-user@domain.com')
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['vcs'],
                                 other_user.email)

        self.control_process()

        self.assert_error_user_not_subscribed_in_response(other_user.email,
                                                          self.package.name)
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, other_user.email))

    def test_keyword_user_doesnt_exist(self):
        """
        Tests the keyword command when the user is not subscribed to any
        package.
        """
        email = 'other-user@domain.com'
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['vcs'],
                                 email)

        self.control_process()

        self.assert_error_user_not_subscribed_in_response(email,
                                                          self.package.name)
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))

    def test_keyword_alias_tag(self):
        """
        Tests that tag works as an alias for keyword.
        """
        keywords = ['vcs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email,
                                 use_tag=True)

        self.control_process()

        self.assert_keywords_in_response(keywords)
        self.assert_subscription_has_keywords(keywords)


class KeywordCommandListSubscriptionSpecific(EmailControlTest,
                                             KeywordCommandHelperMixin):
    """
    Tests the keyword command when used to list keywords associated with a
    subscription.
    """
    def setUp(self):
        super(KeywordCommandListSubscriptionSpecific, self).setUp()

        # Setup a subscription
        self.package = PackageName.objects.create(name='dummy-package')
        self.user = UserEmail.objects.create(email='user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_settings=self.email_settings
        )

        self.commands = []
        self.set_header('From', self.user.email)

    def _to_command_string(self, command):
        return ' '.join(command)

    def add_keyword_command(self, package, email='', use_tag=False):
        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            package,
            email,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def get_list_of_keywords(self, package, email):
        return (
            "Here's the list of accepted keywords associated to package\n"
            "{package} for {user}".format(
                package=self.package.name, user=self.user.email)
        )

    def test_keyword_user_default(self):
        """
        Tests the keyword command when the subscription is using the user's
        default keywords.
        """
        self.email_settings.default_keywords.add(
            Keyword.objects.create(name='new-keyword'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_keyword_subscription_specific(self):
        """
        Tests the keyword command when the subscription has specific keywords
        associated with it.
        """
        self.subscription.keywords.add(Keyword.objects.get(name='vcs'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_keyword_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('no-exist', self.user.email)

        self.control_process()

        self.assert_error_in_response('Package no-exist does not exist')
        self.assert_not_in_response("Here's the list of accepted keywords")

    def test_keyword_subscription_not_active(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription to the given package.
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_keyword_user_not_subscribed(self):
        """
        Tests the keyword command when the given user is not subscribed to the
        given package.
        """
        self.subscription.delete()
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_response_sent()
        self.assert_error_in_response(
            '{email} is not subscribed to the package {pkg}'.format(
                email=self.user.email,
                pkg=self.package.name)
        )
        self.assert_not_in_response("Here's the list of accepted keywords")

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given in the command.
        """
        self.add_keyword_command(self.package.name)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_tag_same_as_keyword(self):
        """
        Tests that "tag" acts as an alias for "keyword"
        """
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())


class KeywordCommandModifyDefault(EmailControlTest, KeywordCommandHelperMixin):
    """
    Tests the keyword command version which modifies a user's list of default
    keywords.
    """
    def setUp(self):
        super(KeywordCommandModifyDefault, self).setUp()

        # Setup a subscription
        self.user = UserEmail.objects.create(email='user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)
        self.default_keywords = set([
            keyword.name
            for keyword in self.email_settings.default_keywords.all()
        ])
        self.commands = []
        self.set_header('From', self.user.email)

    def _to_command_string(self, command):
        """
        Helper method turning a tuple representing a keyword command into a
        string.
        """
        return ' '.join(
            command[:-1] + (', '.join(command[-1]),)
        )

    def get_new_default_list_output_message(self, email):
        """
        Returns the message which should precede the list of new default
        keywords.
        """
        return (
            "Here's the new default list of accepted "
            "keywords for {email} :".format(email=email)
        )

    def add_keyword_command(self, operator, keywords, email='', use_tag=False):
        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            email,
            operator,
            keywords,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def assert_keywords_in_user_default_list(self, keywords):
        """
        Asserts that the given keywords are found in the user's list of default
        keywords.
        """
        default_keywords = self.email_settings.default_keywords.all()
        for keyword in keywords:
            self.assertIn(Keyword.objects.get(name=keyword), default_keywords)

    def assert_keywords_not_in_user_default_list(self, keywords):
        """
        Asserts that the given keywords are not found in the user's list of
        default keywords.
        """
        default_keywords = self.email_settings.default_keywords.all()
        for keyword in keywords:
            self.assertNotIn(
                Keyword.objects.get(name=keyword), default_keywords)

    def assert_keywords_user_default_list_equal(self, keywords):
        """
        Asserts that the user's list of default keywords exactly matches the
        given keywords.
        """
        default_keywords = self.email_settings.default_keywords.all()
        self.assertEqual(default_keywords.count(), len(keywords))
        for keyword in default_keywords:
            self.assertIn(keyword.name, keywords)

    def test_keyword_add_default(self):
        """
        Tests that the keyword command adds a new keyword to the user's list of
        default keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:3]
        ]
        self.add_keyword_command('+', keywords, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_in_user_default_list(keywords)

    def test_keyword_remove_default(self):
        """
        Tests that the keyword command removes keywords from the user's list of
        default keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=True)[:3]
        ]
        self.add_keyword_command('-', keywords, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_not_in_response(keywords)
        self.assert_keywords_not_in_user_default_list(keywords)

    def test_keyword_set_default(self):
        """
        Tests that the keyword command sets a new list of the user's default
        keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:5]
        ]
        keywords.extend(
            keyword.name
            for keyword in Keyword.objects.filter(default=True)[:2]
        )
        self.add_keyword_command(' = ', keywords, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_user_default_list_equal(keywords)

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:3]
        ]
        self.add_keyword_command('   +', keywords)

        self.control_process()

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_in_user_default_list(keywords)

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when a nonexistant keyword is given.
        """
        self.add_keyword_command('+', ['no-exist'])

        self.control_process()

        self.assert_warning_in_response('no-exist is not a valid keyword')
        self.assert_keywords_not_in_response(['no-exist'])

    def test_user_doesnt_exist(self):
        """
        Tests adding a keyword to a user's default list of subscriptions when
        the given user is not subscribed to any packages (it does not exist yet)
        """
        all_default_keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=True)
        ]
        new_user = 'doesnt-exist@domain.com'
        keywords = [Keyword.objects.filter(default=False)[0].name]
        self.add_keyword_command('+', keywords, new_user)

        self.control_process()

        # User created
        self.assertEqual(UserEmail.objects.filter(email=new_user).count(), 1)
        self.assert_in_response(
            self.get_new_default_list_output_message(new_user))
        self.assert_keywords_in_response(keywords + all_default_keywords)


class KeywordCommandShowDefault(EmailControlTest, KeywordCommandHelperMixin):
    def setUp(self):
        super(KeywordCommandShowDefault, self).setUp()
        self.user = UserEmail.objects.create(email='user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)
        self.email_settings.default_keywords.add(
            Keyword.objects.filter(default=False)[0])
        self.set_header('From', self.user.email)

    def get_default_keywords_list_message(self, email):
        """
        Returns the message which should precede the list of all default
        keywords in the output of the command.
        """
        return (
            "Here's the default list of accepted keywords for {email}:".format(
                email=email)
        )

    def test_show_default_keywords(self):
        """
        Tests that the keyword command outputs all default keywords of a user.
        """
        self.set_input_lines(['keyword ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            self.email_settings.default_keywords.all()
        )

    def test_show_default_keywords_email_not_given(self):
        """
        Tests that the keyword command shows all default keywords of a user
        when the email is not given in the command.
        """
        self.set_input_lines(['keyword'])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            self.email_settings.default_keywords.all()
        )

    def test_show_default_keywords_email_no_subscriptions(self):
        """
        Tests that the keyword command returns a list of default keywords for
        users that are not subscribed to any packages.
        """
        email = 'no-exist@domain.com'
        self.set_input_lines(['keyword ' + email])

        self.control_process()

        # User created first...
        self.assertEqual(UserEmail.objects.filter(email=email).count(), 1)
        user = UserEmail.objects.get(email=email)
        self.assert_in_response(
            self.get_default_keywords_list_message(user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            user.emailsettings.default_keywords.all()
        )

    def test_tag_alias_for_keyword(self):
        """
        Tests that "tag" is an alias for "keyword"
        """
        self.set_input_lines(['tag ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            self.email_settings.default_keywords.all()
        )

    def test_tags_alias_for_keyword(self):
        """
        Tests that 'tags' is an alias for 'keyword'
        """
        self.set_input_lines(['tags ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            self.email_settings.default_keywords.all()
        )

    def test_keywords_alias_for_keyword(self):
        """
        Tests that 'keywords' is an alias for 'keyword'
        """
        self.set_input_lines(['keywords ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in
            self.email_settings.default_keywords.all()
        )


class SubscribeToPackageTest(EmailControlTest):
    """
    Tests for the subscribe to package story.
    """
    def setUp(self):
        super(SubscribeToPackageTest, self).setUp()
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        # Regular expression to extract the confirmation code from the body of
        # the response mail
        self.regexp = re.compile(r'^CONFIRM (.*)$', re.MULTILINE)
        self.package = PackageName.objects.create(
            source=True,
            name='dummy-package')

    def user_subscribed(self, email_address):
        """
        Helper method checks whether the given email is subscribed to the
        package.
        """
        u = get_or_none(UserEmail, email=email_address)
        if not u:
            return False
        return u.emailsettings.is_subscribed_to(package=self.package)

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

    def add_binary_package(self, source_package, binary_package):
        """
        Helper method which creates a binary package for the given source
        package.
        """
        binary_pkg = BinaryPackageName.objects.create(
            name=binary_package)
        src_pkg_name = SourcePackageName.objects.get(name=source_package.name)
        src_pkg, _ = SourcePackage.objects.get_or_create(
            source_package_name=src_pkg_name, version='1.0.0')
        src_pkg.binary_packages = [binary_pkg]
        src_pkg.save()

    def add_subscribe_command(self, package, email=None):
        """
        Helper method which adds a subscribe command to the command message.
        """
        if not email:
            email = ''
        payload = self.message.get_payload() or ''
        commands = payload.splitlines()
        commands.append('subscribe ' + package + ' ' + email)
        self.set_input_lines(commands)

    def get_not_source_nor_binary_warning(self, package_name):
        return (
            '{pkg} is neither a source package nor a binary package.'.format(
                pkg=package_name)
        )

    def test_subscribe_and_confirm_normal(self):
        """
        Tests that the user is subscribed to the pacakge after running
        subscribe and confirm.
        """
        package_name = self.package.name
        self.add_subscribe_command(package_name, self.user_email_address)

        self.control_process()

        self.assert_in_response(
            'A confirmation mail has been sent to {email}'.format(
                email=self.user_email_address))
        self.assert_confirmation_sent_to(self.user_email_address)
        # User still not actually subscribed
        self.assertFalse(self.user_subscribed(self.user_email_address))
        # Check that the confirmation mail contains the confirmation code
        match = self.regex_search_in_response(self.regexp)
        self.assertIsNotNone(match)

        # Extract the code and send a confirmation mail
        self.reset_message()
        self.reset_outbox()
        self.set_input_lines([match.group(0)])
        self.control_process()

        self.assert_in_response(
            '{email} has been subscribed to {package}'.format(
                email=self.user_email_address,
                package=package_name))
        self.assertTrue(self.user_subscribed(self.user_email_address))

    def test_subscribe_when_user_already_subscribed(self):
        """
        Tests the subscribe command in the case that the user is trying to
        subscribe to a package he is already subscribed to.
        """
        # Make sure the user is already subscribed.
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.user_email_address
        )
        # Try subscribing again
        self.add_subscribe_command(self.package.name, self.user_email_address)

        self.control_process()

        self.assert_warning_in_response(
            '{email} is already subscribed to {package}'.format(
                email=self.user_email_address,
                package=self.package.name))

    def test_subscribe_no_email_given(self):
        """
        Tests the subscribe command when there is no email address given.
        """
        self.add_subscribe_command(self.package.name)

        self.control_process()

        self.assert_confirmation_sent_to(self.user_email_address)

    def test_subscribe_email_different_than_from(self):
        """
        Tests the subscribe command when the given email address is different
        than the From address of the received message.
        """
        subscribe_email_address = 'another-user@domain.com'
        self.assertNotEqual(
            subscribe_email_address,
            self.user_email_address,
            'The test checks the case when <email> is different than From'
        )
        self.add_subscribe_command(self.package.name, subscribe_email_address)

        self.control_process()

        self.assert_cc_contains_address(subscribe_email_address)
        self.assert_confirmation_sent_to(subscribe_email_address)

    def test_subscribe_unexisting_source_package(self):
        """
        Tests the subscribe command when the given package is not an existing
        source package.
        """
        binary_package = 'binary-package'
        self.add_binary_package(self.package, binary_package)
        self.add_subscribe_command(binary_package)

        self.control_process()

        self.assert_warning_in_response(
            '{package} is not a source package.'.format(
                package=binary_package))
        self.assert_in_response(
            '{package} is the source package '
            'for the {binary} binary package'.format(
                package=self.package.name,
                binary=binary_package))
        self.assert_confirmation_sent_to(self.user_email_address)

    def test_subscribe_unexisting_package(self):
        """
        Tests the subscribe command when the given package is not an existing
        source, binary or pseudo package.
        """
        package_name = 'random-package-name'
        self.add_subscribe_command(package_name)

        self.control_process()

        self.assert_warning_in_response(
            self.get_not_source_nor_binary_warning(package_name))
        self.assert_warning_in_response(
            'Package {package} is not even a pseudo package'.format(
                package=package_name))
        self.assert_confirmation_sent_to(self.user_email_address)
        # A new package was created.
        self.assertIsNotNone(get_or_none(PackageName, name=package_name))

    def test_subscribe_subscription_only_package(self):
        """
        Tests that when subscribing to a subscription-only package the correct
        warning is displayed even when it already contains subscriptions.
        """
        package_name = 'random-package-name'
        Subscription.objects.create_for(
            email='user@domain.com', package_name=package_name)
        # Make sure the package actually exists before running the test
        pkg = get_or_none(PackageName, name=package_name)
        self.assertIsNotNone(pkg)
        self.assertFalse(pkg.binary)
        self.add_subscribe_command(package_name)

        self.control_process()

        self.assert_warning_in_response(
            self.get_not_source_nor_binary_warning(package_name))
        self.assert_warning_in_response(
            'Package {package} is not even a pseudo package'.format(
                package=package_name))
        self.assert_confirmation_sent_to(self.user_email_address)

    def test_subscribe_pseudo_package(self):
        """
        Tests the subscribe command when the given package is an existing
        pseudo-package.
        """
        pseudo_package = 'pseudo-package'
        PackageName.pseudo_packages.create(name=pseudo_package)
        self.add_subscribe_command(pseudo_package)

        self.control_process()

        self.assert_warning_in_response(
            self.get_not_source_nor_binary_warning(pseudo_package))
        self.assert_warning_in_response(
            'Package {package} is a pseudo package'.format(
                package=pseudo_package))
        self.assert_confirmation_sent_to(self.user_email_address)

    def test_subscribe_execute_once(self):
        """
        If the command message includes the same subscribe command multiple
        times, it is executed only once.
        """
        self.add_subscribe_command(self.package.name)
        self.add_subscribe_command(self.package.name, self.user_email_address)

        self.control_process()

        # Only one confirmation email required as the subscribe commands are
        # equivalent.
        self.assert_response_sent(2)

    def test_confirm_expired(self):
        """
        Tests that an expired confirmation does not subscribe the user.
        """
        # Set up an expired CommandConfirmation object.
        c = CommandConfirmation.objects.create_for_commands(
            ['subscribe {package} {user}'.format(user=self.user_email_address,
                                                 package=self.package.name)])
        delta = timedelta(
            days=settings.DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS + 1)
        c.date_created = c.date_created - delta
        c.save()
        self.set_input_lines(['confirm ' + c.confirmation_key])

        self.control_process()

        self.assert_error_in_response('Confirmation failed')

    def test_subscribe_to_invalid_package_name(self):
        self.set_input_lines(['subscribe /..abc'])
        self.control_process()
        self.assert_warning_in_response('Invalid package name: /..abc')

    def test_bug_user_without_emailsettings(self):
        """
        Non-regression test for a failure when UserEmail has no associated
        EmailSettings object.
        """
        user, _ = UserEmail.objects.get_or_create(email=self.user_email_address)
        with self.assertRaisesRegexp(Exception,
                                     'UserEmail has no emailsettings'):
            user.emailsettings
        self.add_subscribe_command(self.package.name, self.user_email_address)

        self.control_process()  # Must not raise anything


class UnsubscribeFromPackageTest(EmailControlTest):
    """
    Tests for the unsubscribe from package story.
    """
    def setUp(self):
        super(UnsubscribeFromPackageTest, self).setUp()
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        self.package = PackageName.objects.create(
            source=True,
            name='dummy-package')
        self.other_package = PackageName.objects.create(name='other-package')
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

    def assert_not_subscribed_error_in_response(self, email):
        self.assert_error_in_response(
            "{email} is not subscribed, you can't unsubscribe.".format(
                email=email))

    def add_binary_package(self, source_package, binary_package):
        """
        Helper method which creates a binary package for the given source
        package.
        """
        binary_pkg = BinaryPackageName.objects.create(
            name=binary_package)
        src_pkg_name = SourcePackageName.objects.get(name=source_package.name)
        src_pkg, _ = SourcePackage.objects.get_or_create(
            source_package_name=src_pkg_name, version='1.0.0')
        src_pkg.binary_packages = [binary_pkg]
        src_pkg.save()

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

        self.assert_in_response(
            'A confirmation mail has been sent to {email}'.format(
                email=self.user_email_address))
        self.assert_confirmation_sent_to(self.user_email_address)
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

        self.assert_not_subscribed_error_in_response(self.user_email_address)

    def test_unsubscribe_inactive_subscription(self):
        """
        Tests the unsubscribe command when the user's subscription is not
        active.
        """
        Subscription.objects.create_for(
            package_name=self.other_package.name,
            email=self.user_email_address,
            active=False)
        self.add_unsubscribe_command(self.other_package.name,
                                     self.user_email_address)

        self.control_process()

        self.assert_not_subscribed_error_in_response(self.user_email_address)

    def test_unsubscribe_no_email_given(self):
        """
        Tests the unsubscribe command when there is no email address given.
        """
        self.add_unsubscribe_command(self.package.name)

        self.control_process()

        self.assert_confirmation_sent_to(self.user_email_address)

    def test_unsubscribe_email_different_than_from(self):
        """
        Tests the unsubscribe command when the given email address is different
        than the From address of the received message.
        """
        self.add_unsubscribe_command(self.package.name,
                                     self.other_user)

        self.control_process()

        self.assert_cc_contains_address(self.other_user)
        self.assert_confirmation_sent_to(self.other_user)

    def test_unsubscribe_unexisting_source_package(self):
        """
        Tests the unsubscribe command when the given package is not an existing
        source package.
        """
        binary_package = 'binary-package'
        self.add_binary_package(self.package, binary_package)
        self.add_unsubscribe_command(binary_package)

        self.control_process()

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

        self.assert_warning_in_response(
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
        self.user = UserEmail.objects.get(email=self.user_email_address)

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
        old_subscriptions = [pkg.name for pkg
                             in self.user.emailsettings.packagename_set.all()]
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
                fqdn=settings.DISTRO_TRACKER_FQDN)
            for package in sorted(old_subscriptions)
        )

    def test_unsubscribeall_no_subscriptions(self):
        """
        Tests the unsubscribeall command when the user is not subscribed to any
        packages.
        """
        self.user.emailsettings.subscription_set.all().delete()
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


class WhichCommandTest(EmailControlTest):
    """
    Tests for the which command.
    """
    def setUp(self):
        super(WhichCommandTest, self).setUp()
        self.packages = [
            PackageName.objects.create(name='package' + str(i))
            for i in range(10)
        ]
        self.user = UserEmail.objects.create(email='user@domain.com')
        self.email_settings = EmailSettings.objects.create(user_email=self.user)

    def assert_no_subscriptions_in_response(self):
        self.assert_in_response('No subscriptions found')

    def test_list_packages_subscribed_to(self):
        """
        Tests that the which command lists the right packages.
        """
        subscriptions = [
            Subscription.objects.create(
                package=self.packages[i],
                email_settings=self.email_settings
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
                email_settings=self.email_settings
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
            email_settings=self.email_settings,
            active=False)
        self.set_input_lines(['which ' + self.user.email])

        self.control_process()

        self.assert_no_subscriptions_in_response()


class WhoCommandTest(EmailControlTest):
    """
    Tests for the who command.
    """
    def setUp(self):
        super(WhoCommandTest, self).setUp()
        self.package = PackageName.objects.create(name='dummy-package')
        self.users = [
            UserEmail.objects.create(email='user@domain.com'),
            UserEmail.objects.create(email='second-user@domain.com'),
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
            email_settings, _ = \
                EmailSettings.objects.get_or_create(user_email=user)
            Subscription.objects.create(email_settings=email_settings,
                                        package=self.package)
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


class TeamCommandsMixin(object):
    def setUp(self):
        super(TeamCommandsMixin, self).setUp()
        self.password = 'asdf'
        self.user = User.objects.create_user(
            main_email='user@domain.com', password=self.password,
            first_name='', last_name='')
        self.team = Team.objects.create_with_slug(
            owner=self.user, name="Team name")
        self.package = PackageName.objects.create(name='dummy')
        self.team.packages.add(self.package)
        self.team.add_members(self.user.emails.all()[:1])

    def get_confirmation_text(self, email):
        return 'A confirmation mail has been sent to {}'.format(email)

    def assert_confirmation_sent_to(self, email_address):
        """
        Asserts that a confirmation mail has been sent to the given email.
        """
        self.assertTrue(any(
            msg.message()['Subject'].startswith('CONFIRM') and
            email_address in msg.to
            for msg in mail.outbox
        ))


class JoinTeamCommandsTests(TeamCommandsMixin, EmailControlTest):
    """
    Tests for the join-team control command.
    """
    def setUp(self):
        super(JoinTeamCommandsTests, self).setUp()
        self.user_email = UserEmail.objects.create(email='other@domain.com')
        self.set_header('From', self.user_email.email)

    def get_join_command(self, team, email=''):
        return 'join-team {} {}'.format(team, email)

    def get_joined_message(self, team):
        return 'You have successfully joined the team "{}"'.format(team.name)

    def get_private_error(self, team):
        return (
            "The given team is not public. "
            "Please contact {} if you wish to join".format(
                team.owner.main_email)
        )

    def get_no_exist_error(self, team):
        return 'Team with the slug "{}" does not exist.'.format(team)

    def get_is_member_warning(self):
        return 'You are already a member of the team.'

    def test_join_public_team(self):
        """
        Tests that users can join a public team.
        """
        self.set_input_lines([self.get_join_command(self.team.slug)])

        self.control_process()

        # Confirmation mail sent
        self.assert_confirmation_sent_to(self.user_email.email)
        # The response to the original control message indicates that
        self.assert_in_response(
            self.get_confirmation_text(self.user_email.email))
        # The user isn't a member of the team yet
        self.assertNotIn(self.user_email, self.team.members.all())
        # A confirmation instance is created
        self.assertEqual(1, CommandConfirmation.objects.count())
        confirmation = CommandConfirmation.objects.all()[0]

        # Send the confirmation mail now
        self.reset_outbox()
        self.set_input_lines(['CONFIRM ' + confirmation.confirmation_key])

        self.control_process()

        # The response indicates that the user has joined the team
        self.assert_in_response(self.get_joined_message(self.team))
        # The user now really is in the team
        self.assertIn(self.user_email, self.team.members.all())

    def test_join_public_team_different_from(self):
        """
        Tests that a confirmation mail is sent to the user being added to the
        team, not the user who sent the control command.
        """
        self.set_input_lines([self.get_join_command(self.team.slug,
                                                    self.user_email)])
        self.set_header('From', 'different-user@domain.com')

        self.control_process()

        # The confirmation sent to the user being added to the team
        self.assert_confirmation_sent_to(self.user_email.email)

    def test_join_private_team(self):
        """
        Tests that trying to join a private team fails.
        """
        self.team.public = False
        self.team.save()
        self.set_input_lines([self.get_join_command(self.team.slug)])

        self.control_process()

        self.assert_error_in_response(self.get_private_error(self.team))

    def test_join_non_existing_team(self):
        """
        Tests that trying to join a non-existing team fails.
        """
        team_slug = 'team-does-not-exist'
        self.set_input_lines([self.get_join_command(team_slug)])

        self.control_process()

        self.assert_error_in_response(self.get_no_exist_error(team_slug))

    def test_join_team_already_member(self):
        """
        Tests that a user gets a warning when trying to join a team he is
        already a member of.
        """
        self.team.add_members([self.user_email])
        self.set_input_lines([self.get_join_command(self.team.slug,
                                                    self.user_email)])

        self.control_process()

        self.assert_warning_in_response(self.get_is_member_warning())


class LeaveTeamCommandTests(TeamCommandsMixin, EmailControlTest):
    def setUp(self):
        super(LeaveTeamCommandTests, self).setUp()
        self.user_email = UserEmail.objects.create(email='other@domain.com')
        self.team.add_members([self.user_email])
        self.set_header('From', self.user_email.email)

    def get_leave_command(self, team, email=''):
        return 'leave-team {} {}'.format(team, email)

    def get_left_team_message(self, team):
        return 'You have successfully left the team "{}" (slug: {})'.format(
            team,
            team.slug)

    def get_is_not_member_warning(self):
        return 'You are not a member of the team.'

    def get_no_exist_error(self, team):
            return 'Team with the slug "{}" does not exist.'.format(team)

    def test_leave_team(self):
        """
        Tests the normal situation where the user leaves a team he is a
        member of.
        """
        self.set_input_lines([self.get_leave_command(self.team.slug)])

        self.control_process()

        # A confirmation sent to the user
        self.assert_confirmation_sent_to(self.user_email.email)
        # Which is displayed in the response to the original message
        self.assert_in_response(
            self.get_confirmation_text(self.user_email.email))
        # The user is still a member of the team
        self.assertIn(self.user_email, self.team.members.all())
        # A confirmation is created
        self.assertEqual(1, CommandConfirmation.objects.count())
        confirmation = CommandConfirmation.objects.all()[0]

        # Now confirm the email
        self.reset_outbox()
        self.set_input_lines(['CONFIRM ' + confirmation.confirmation_key])

        self.control_process()

        # The user notified that he has left the team
        self.assert_in_response(self.get_left_team_message(self.team))
        # The user is no longer a member of the team
        self.assertNotIn(self.user_email, self.team.members.all())

    def test_leave_team_different_from(self):
        """
        Tests that a confirmation message is sent to the user being removed
        from the team, not the one that sent the control message.
        """
        self.set_input_lines(
            [self.get_leave_command(self.team.slug, self.user_email.email)])
        self.set_header('From', 'some-other-user@domain.com')

        self.control_process()

        # Confirmation sent to the user being removed from the team
        self.assert_confirmation_sent_to(self.user_email.email)

    def test_leave_team_not_member(self):
        """
        Tests that a warning is returned when the user tries to leave a team
        that he is not a member of.
        """
        self.team.remove_members([self.user_email])
        self.set_input_lines([self.get_leave_command(self.team.slug)])

        self.control_process()

        self.assert_warning_in_response(self.get_is_not_member_warning())

    def test_leave_team_does_not_exist(self):
        """
        Tests that an error is returned when the user tries to leave a team
        that does not even exist.
        """
        team_slug = 'this-does-not-exist'
        self.set_input_lines([self.get_leave_command(team_slug)])

        self.control_process()

        self.assert_error_in_response(self.get_no_exist_error(team_slug))


class ListTeamPackagesTests(TeamCommandsMixin, EmailControlTest):
    def setUp(self):
        super(ListTeamPackagesTests, self).setUp()
        # Add some more packages to the team
        self.team.packages.create(name='pkg1')
        self.team.packages.create(name='pkg2')

    def get_list_team_packages_command(self, team):
        return 'list-team-packages {}'.format(team)

    def get_private_error(self):
        return (
            "The team is private. "
            "Only team members can see its packages.")

    def test_get_public_team_packages(self):
        """
        Tests that a public team's packages can be obtained by any user.
        """
        self.set_input_lines([
            self.get_list_team_packages_command(self.team.slug)
        ])

        self.control_process()

        self.assert_list_in_response(
            package.name
            for package in self.team.packages.all().order_by('name'))

    def test_get_private_team_packages_non_member(self):
        """
        Tests that getting a private team's packages is not possible by a
        user that is not a member of the team.
        """
        self.team.public = False
        self.team.save()
        self.set_input_lines([
            self.get_list_team_packages_command(self.team.slug)
        ])

        self.control_process()

        self.assert_error_in_response(self.get_private_error())

    def test_get_private_team_packages_member(self):
        """
        Tests that getting a private team's packages is possible by a
        member of the team.
        """
        self.team.public = False
        self.team.save()
        # Add a member to the team
        user_email = UserEmail.objects.create(email='member@domain.com')
        self.team.add_members([user_email])
        # Set the from field so that the member sends the control email
        self.set_header('From', user_email.email)
        self.set_input_lines([
            self.get_list_team_packages_command(self.team.slug)
        ])

        self.control_process()

        # The packages are output in the response
        self.assert_list_in_response(
            package.name
            for package in self.team.packages.all().order_by('name'))


class WhichTeamsCommandTests(TeamCommandsMixin, EmailControlTest):
    def setUp(self):
        super(WhichTeamsCommandTests, self).setUp()
        # Set up more teams
        self.teams = [
            self.team,
            Team.objects.create_with_slug(name='Other team', owner=self.user),
            Team.objects.create_with_slug(name='Some team', owner=self.user),
        ]

        self.user_email = UserEmail.objects.create(email='other@domain.com')

    def get_which_teams_command(self, email=''):
        return 'which-teams {}'.format(email)

    def get_no_teams_warning(self, email):
        return '{} is not a member of any team.'.format(email)

    def test_user_member_of_teams(self):
        """
        Test that all the user's team memberships are output.
        """
        member_of = self.teams[:2]
        not_member_of = self.teams[2:]
        for team in member_of:
            team.add_members([self.user_email])
        self.set_input_lines([
            self.get_which_teams_command(self.user_email.email)
        ])

        self.control_process()

        # The teams that the user is subscribed too are output in the response
        self.assert_list_in_response([
            team.slug
            for team in self.user_email.teams.all().order_by('name')
        ])
        # The teams the user is not subscribed to are not found in the response
        for team in not_member_of:
            self.assert_list_item_not_in_response(team.slug)

    def test_user_not_member_of_any_team(self):
        """
        Tests the situation when the user is not a member of any teams.
        """
        self.set_input_lines([
            self.get_which_teams_command(self.user_email.email)
        ])

        self.control_process()

        self.assert_warning_in_response(
            self.get_no_teams_warning(self.user_email.email))
