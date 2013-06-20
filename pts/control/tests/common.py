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

from email import encoders
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.utils import make_msgid

from pts import control

from django.conf import settings
PTS_OWNER_EMAIL = settings.PTS_OWNER_EMAIL
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL


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
        self.message.add_header('To', PTS_CONTROL_EMAIL)
        self.message.add_header('Subject', 'Commands')
        self.message.add_header('Message-ID', make_msgid())

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

    def get_list_item(self, item, bullet='>'):
        return bullet + ' ' + str(item)

    def assert_list_in_response(self, items, bullet='*'):
        self.assert_in_response('\n'.join(
            self.get_list_item(item, bullet)
            for item in items
        ))

    def assert_list_item_in_response(self, item, bullet='*'):
        self.assert_in_response(self.get_list_item(item, bullet))

    def assert_list_item_not_in_response(self, item, bullet='*'):
        self.assert_not_in_response(self.get_list_item(item, bullet))

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

    def assert_command_echo_in_response(self, command):
        self.assert_in_response('>' + command)

    def assert_command_echo_not_in_response(self, command):
        self.assert_not_in_response('>' + command)

    def assert_warning_in_response(self, text):
        self.assert_in_response("Warning: " + text)

    def assert_error_in_response(self, text):
        self.assert_in_response("Error: " + text)

    def assert_correct_response_headers(self):
        # The last message sent should always be the response
        self.assert_header_equal('X-Loop', PTS_CONTROL_EMAIL)
        self.assert_header_equal('To', self.message['From'])
        self.assert_header_equal('From', PTS_OWNER_EMAIL)
        self.assert_header_equal('In-Reply-To', self.message['Message-ID'])
        self.assert_header_equal(
            'References',
            ' '.join((self.message.get('References', ''),
                      self.message['Message-ID']))
        )
        if not self.message['Subject']:
            self.assert_header_equal('Subject', 'Re: Your mail')
        else:
            self.assert_header_equal('Subject',
                                     'Re: ' + self.message['Subject'])

    def reset_outbox(self):
        mail.outbox = []

    def regex_search_in_response(self, regexp, response_number=0):
        return regexp.search(mail.outbox[response_number].body)
