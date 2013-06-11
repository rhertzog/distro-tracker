"""
Tests for the control module of the Debian PTS.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.core import mail

from django.template.loader import render_to_string

from email import encoders
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

from core.utils import extract_email_address_from_header
from core.models import Package, BinaryPackage
from core.models import Subscription
import control
import re

from django.conf import settings
OWNER_EMAIL_ADDRESS = getattr(settings, 'OWNER_EMAIL_ADDRESS')
CONTROL_EMAIL_ADDRESS = getattr(settings, 'CONTROL_EMAIL_ADDRESS')


class EmailControlTest(TestCase):
    def control_process(self):
        """
        Helper method. Passes the constructed control message to the control
        processor.
        """
        control.process(self.message.as_string())

    def setUp(self):
        self.reset_message()

    def set_default_headers(self):
        self.message.add_header('From', 'John Doe <john.doe@unknown.com>')
        self.message.add_header('To', CONTROL_EMAIL_ADDRESS)
        self.message.add_header('Subject', 'Commands')

    def set_header(self, header_name, header_value):
        if header_name in self.message:
            del self.message[header_name]
        self.message.add_header(header_name, header_value)

    def set_input_lines(self, lines):
        payload = '\n'.join(lines)
        if self.multipart:
            plain_text = MIMEText('plain')
            plain_text.set_payload(payload)
            self.message.attach(plain_text)
        else:
            self.message.set_payload(payload)

    def make_multipart(self, alternative=False):
        if alternative:
            self.message = MIMEMultipart('alternative')
        else:
            self.message = MIMEMultipart()
        self.set_default_headers()
        self.multipart = True

    def add_part(self, mime_type, subtype, data):
        part = MIMEBase(mime_type, subtype)
        part.set_payload(data)
        if mime_type != 'text':
            encoders.encode_base64(part)
        self.message.attach(part)

    def reset_message(self):
        self.message = Message()
        self.multipart = False
        self.set_default_headers()

    def assert_response_sent(self, number_of_responses=1):
        self.assertEqual(len(mail.outbox), number_of_responses)

    def assert_response_not_sent(self):
        self.assertEqual(len(mail.outbox), 0)

    def assert_in_response(self, text, response_number=-1):
        out_mail = mail.outbox[response_number]
        self.assertIn(text, out_mail.body)

    def assert_not_in_response(self, text, response_number=-1):
        out_mail = mail.outbox[response_number]
        self.assertNotIn(text, out_mail.body)

    def assert_response_equal(self, text, response_number=-1):
        out_mail = mail.outbox[response_number]
        self.assertEqual(text, out_mail.body)

    def assert_header_equal(self, header_name, header_value,
                            response_number=-1):
        out_mail = mail.outbox[response_number].message()
        self.assertEqual(out_mail[header_name], header_value)

    def assert_correct_response_headers(self):
        # The last message sent should always be the response
        self.assert_header_equal('X-Loop', CONTROL_EMAIL_ADDRESS)
        self.assert_header_equal('To', self.message['From'])
        self.assert_header_equal('From', OWNER_EMAIL_ADDRESS)
        if not self.message['Subject']:
            self.assert_header_equal('Subject', 'Re: Your mail')
        else:
            self.assert_header_equal('Subject',
                                     'Re: ' + self.message['Subject'])

    def reset_outbox(self):
        mail.outbox = []

    def regex_search_in_response(self, regexp, response_number=0):
        return regexp.search(mail.outbox[response_number].body)


class ControlBotBasic(EmailControlTest):
    def test_basic(self):
        """
        Tests if the proper headers are set for the reply message, that the
        output contains original lines prepended with '>'
        """
        input_lines = [
            "#command",
            "   thanks",
        ]
        self.set_input_lines(input_lines)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        for line in input_lines:
            self.assert_in_response('>' + line.strip())

    def test_not_plaintext(self):
        """
        Tests that the response to a non-plaintext message is a warning email.
        """
        self.make_multipart()
        self.add_part('application', 'octet-stream', b'asdf')

        self.control_process()

        self.assert_response_sent()
        self.assert_response_equal(render_to_string(
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
        self.assert_correct_response_headers()
        for line in input_lines:
            self.assert_in_response('>' + line.strip())

    def test_response_subject(self):
        """
        Tests that the subject of the response when there is no subject set in
        the request is correct.
        """
        self.set_input_lines(['#command', "thanks"])
        self.set_header('Subject', '')

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()

    def test_empty_no_response(self):
        """
        Tests that there is no response to an empty message.
        """
        self.control_process()

        self.assert_response_not_sent()

    def test_loop_no_response(self):
        """
        Tests that there is no response if the message's X-Loop is set to
       CONTROL_EMAIL_ADDRESS
        """
        self.set_header('X-Loop', CONTROL_EMAIL_ADDRESS)
        self.set_input_lines(['#command', 'thanks'])

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
        self.set_input_lines(['help'] + ['garbage'] * 5 + ['#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_not_in_response('>#command')

    def test_stop_on_thanks_or_quit(self):
        """
        Tests that processing stops after encountering the thanks or quit
        command.
        """
        self.set_input_lines(['thanks', '#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_not_in_response('>#command')


class SubscribeToPackageTest(EmailControlTest):
    """
    Tests for the subscribe to package story.
    """
    def setUp(self):
        EmailControlTest.setUp(self)
        # Regular expression to extract the confirmation code from the body of
        # the response mail
        self.user_email_address = 'dummy-user@domain.com'
        self.set_header('From',
                        'Dummy User <{user_email}>'.format(
                            user_email=self.user_email_address))
        self.regexp = re.compile(r'^CONFIRM (.*)$', re.MULTILINE)
        self.package = Package.objects.create(name='dummy-package')

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
        Helper method which checks that a subscribe command which came from
        ``from_email`` and subscribed ``subscribe_email`` has successfully
        executed.
        """
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

    def test_subscribe_and_confirm_normal(self):
        """
        Tests that the user is subscribed to the pacakge after running
        subscribe and confirm.
        """
        package_name = self.package.name
        self.add_subscribe_command(package_name, self.user_email_address)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)
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

        self.assert_response_sent()
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

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response(
            '{email} is already subscribed to {package}'.format(
                email=self.user_email_address,
                package=self.package.name))

    def test_subscribe_no_email_given(self):
        """
        Tests the subscribe command when there is no email address given.
        """
        self.add_subscribe_command(self.package.name)

        self.control_process()

        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)

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

        self.assert_correct_response_for_command(self.user_email_address,
                                                 subscribe_email_address)

    def test_subscribe_unexisting_source_package(self):
        """
        Tests the subscribe command when the given package is not an existing
        source package.
        """
        binary_package = 'binary-package'
        self.add_binary_package(self.package, binary_package)
        self.add_subscribe_command(binary_package)

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

    def test_subscribe_unexisting_source_or_binary_package(self):
        """
        Tests the subscribe command when the given package is neither an
        existing source nor an existing binary package.
        """
        binary_package = 'binary-package'
        self.add_subscribe_command(binary_package)

        self.control_process()

        self.assert_response_sent()
        self.assert_in_response(
            '{package} is neither a source package '
            'nor a binary package.'.format(package=binary_package))

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
        self.assert_correct_response_for_command(self.user_email_address,
                                                 self.user_email_address)
        self.assert_confirmation_sent_to(self.user_email_address)
