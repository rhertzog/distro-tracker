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
from django.core import mail
from django.utils.encoding import force_bytes

from email import encoders
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.utils import make_msgid

from pts.core.utils import extract_email_address_from_header

from pts import control

from django.conf import settings
PTS_CONTACT_EMAIL = settings.PTS_CONTACT_EMAIL
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL


class EmailControlTest(TestCase):
    def control_process(self):
        """
        Helper method. Passes the constructed control message to the control
        processor.
        """
        control.process(force_bytes(self.message.as_string(), 'utf-8'))

    def setUp(self):
        self.reset_message()

    def set_default_headers(self):
        """
        Helper method which adds the default headers for each test message.
        """
        self.message.add_header('From', 'John Doe <john.doe@unknown.com>')
        self.message.add_header('To', PTS_CONTROL_EMAIL)
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
