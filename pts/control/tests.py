"""
Tests for the control module of the Debian PTS.
"""
from django.test import TestCase
from django.core import mail

from email import encoders
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

import control


class ControlBotBasic(TestCase):
    def setUp(self):
        self.message = Message()
        self.message.add_header('From', 'John Doe <john.doe@unknown.com>')
        self.message.add_header('To', 'pts@qa.debian.org')
        self.message.add_header('Subject', 'Commands')

    def test_basic(self):
        """
        Tests if the proper headers are set for the reply message, that the
        output contains original lines prepended with '>'
        """
        payload = (
            """#command
            thanks""")
        self.message.set_payload(payload)

        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0].message()
        self.assertEquals(out_mail.get('Subject'),
                          'Re: ' + self.message.get('Subject'))
        self.assertEquals(out_mail['X-Loop'],
                          'pts@qa.debian.org')
        self.assertEquals(out_mail['To'],
                          self.message['From'])
        self.assertEquals(out_mail['From'],
                          'owner@packages.qa.debian.org')
        for line in payload.split('\n'):
            self.assertIn('>' + line.strip(),
                          out_mail.get_payload(decode=True))

    def test_not_plaintext(self):
        """
        Tests that the response to a non-plaintext message is a warning email.
        """
        msg = MIMEMultipart()
        msg.add_header('From', self.message['from'])
        msg.add_header('Subject', self.message['subject'])
        part1 = MIMEBase('application', 'octet-stream')
        part1.set_payload('asdf')
        encoders.encode_base64(part1)
        msg.attach(part1)

        control.process(msg.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0]
        self.assertIn('Try again with a simple plain-text message',
                       out_mail.body)

    def test_multipart_with_plaintext(self):
        """
        Tests that the response to a multipart message which contains a
        text/plain part is correct.
        """
        msg = MIMEMultipart('alternative')
        msg.add_header('From', self.message['from'])
        msg.add_header('Subject', self.message['subject'])
        payload = (
            """#command
            thanks""")
        text = MIMEText(payload, 'plain')
        html = MIMEText(payload, 'html')
        msg.attach(text)
        msg.attach(html)

        control.process(msg.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0].message()
        self.assertEquals(out_mail.get('Subject'),
                          'Re: ' + self.message.get('Subject'))
        self.assertEquals(out_mail['X-Loop'],
                          'pts@qa.debian.org')
        self.assertEquals(out_mail['To'],
                          self.message['From'])
        self.assertEquals(out_mail['From'],
                          'owner@packages.qa.debian.org')
        for line in payload.split('\n'):
            self.assertIn('>' + line.strip(),
                          out_mail.get_payload(decode=True))

    def test_response_subject(self):
        """
        Tests that the subject of the response when there is no subject set in
        the request is correct.
        """
        del self.message['Subject']
        payload = (
            """#command
            thanks""")
        self.message.set_payload(payload)

        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0]
        self.assertEquals(out_mail.subject,
                          'Re: Your mail')

    def test_empty_no_response(self):
        """
        Tests that there is no response to an empty message.
        """
        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 0)

    def test_loop_no_response(self):
        """
        Tests that there is no response if the message's X-Loop is set to
        pts@qa.debian.org.
        """
        self.message['X-Loop'] = 'pts@qa.debian.org'

        self.assertEquals(len(mail.outbox), 0)

    def test_no_valid_command_no_response(self):
        """
        Tests that there is no response for a message which does not contain
        any valid commands.
        """
        payload = "Some text\nSome more text"
        self.message.set_payload(payload)

        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 0)

    def test_stop_after_five_garbage_lines(self):
        """
        Tests that processing stops after encountering five garbage lines.
        """
        payload = (
            """help
            garbage1
            garbage2
            garbage3
            garbage4
            garbage5
            #command""")
        self.message.set_payload(payload)

        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0]
        self.assertNotIn('>#command', out_mail.body)

    def test_stop_on_thanks_or_quit(self):
        """
        Tests that processing stops after encountering the thanks or quit
        command.
        """
        payload = (
            """thanks
            #command""")
        self.message.set_payload(payload)

        control.process(self.message.as_string())

        self.assertEquals(len(mail.outbox), 1)
        out_mail = mail.outbox[0]
        self.assertNotIn('>#command', out_mail.body)
