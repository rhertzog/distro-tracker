# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

"""
This module contains the tests for the dispatch functionality of PTS.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.core import mail

from email.message import Message

from core.models import Package, Subscription
from core.utils import extract_email_address_from_header
from core.utils import get_or_none
import dispatch

from django.conf import settings
OWNER_EMAIL_ADDRESS = getattr(settings, 'OWNER_EMAIL_ADDRESS')
CONTROL_EMAIL_ADDRESS = getattr(settings, 'CONTROL_EMAIL_ADDRESS')


class DispatchBaseTest(TestCase):
    def setUp(self):
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.add_header('X-Loop', 'owner@bugs.debian.org')
        self.set_message_content('message content')

        self.package = Package.objects.create(name=self.package_name)

    def clear_message(self):
        self.message = Message()
        self.headers = []

    def set_package_name(self, package_name):
        self.package_name = package_name
        self.add_header('To', '{package}@packages.qa.debian.org'.format(
            package=self.package_name))

    def set_message_content(self, content):
        self.message.set_payload(content)

    def add_header(self, header_name, header_value):
        self.message.add_header(header_name, header_value)
        self.headers.append((header_name, header_value))

    def run_dispatch(self):
        dispatch.process(self.message.as_string())

    def subscribe_user_to_package(self, user_email, package):
        """
        Helper method which subscribes the given user to the given package.
        """
        Subscription.objects.create_for(
            package_name=package,
            email=user_email)

    def assert_all_old_headers_found(self):
        """
        Helper method checks if all the headers of the received message are
        found in all the forwarded messages and in the identical order.
        """
        for msg in mail.outbox:
            msg = msg.message()
            fwd_headers = msg.items()
            for original_header, fwd_header in zip(self.headers, fwd_headers):
                self.assertEqual(original_header, fwd_header)

    def assert_all_new_headers_found(self):
        """
        Helper method checks if all the necessary new headers are incldued in
        all the forwarded messages.
        """
        headers = [
            ('X-Loop', '{package}@packages.qa.debian.org'.format(
                package=self.package_name)),
            ('X-PTS-Package', self.package_name),
            ('X-Debian-Package', self.package_name),
            ('X-Debian', 'PTS'),
            ('Precedence', 'list'),
            ('List-Unsubscribe',
                '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                    control_email=CONTROL_EMAIL_ADDRESS,
                    package=self.package_name)),
        ]
        for msg in mail.outbox:
            msg = msg.message()
            for header_name, header_value in headers:
                self.assertIn(
                    header_value, msg.get_all(header_name),
                    '{header_name}: {header_value} not found in {all}'.format(
                        header_name=header_name,
                        header_value=header_value,
                        all=msg.get_all(header_name)))

    def assert_correct_forwards(self):
        """
        Helper method checks if the mail was forwarded to all users who are
        subscribed to the package.
        """
        package = get_or_none(Package, name=self.package_name)
        if not package:
            subscriptions = []
        else:
            subscriptions = package.subscriptions.all()
        self.assertEqual(
            len(mail.outbox), len(subscriptions))
        # Extract addresses from the sent mails envelope headers
        all_forwards = [
            extract_email_address_from_header(message.to[0])
            for message in mail.outbox
            if len(message.to) == 1
        ]
        for email_user in subscriptions:
            self.assertIn(
                email_user.email, all_forwards)

    def assert_correct_forward_content(self):
        """
        Helper method checks if the forwarded mails contain the same content
        as the original message.
        """
        original = self.message.get_payload(decode=True).decode('ascii')
        for msg in mail.outbox:
            fwd = msg.message().get_payload(decode=True).decode('ascii')
            self.assertEqual(original, fwd)

    def assert_correct_response(self):
        """
        Helper method checks the result of running the dispatch processor.
        """
        self.assert_correct_forwards()
        self.assert_all_old_headers_found()
        self.assert_all_new_headers_found()
        self.assert_correct_forward_content()

    def test_dispatch_package_exists(self):
        """
        Tests the dispatch functionality when the given package exists.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.subscribe_user_to_package('user2@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_correct_response()

    def test_dispatch_package_doesnt_exist(self):
        """
        Tests the dispatch functionality when the given package does not
        exist.
        """
        self.set_package_name('non-existent-package')

        self.run_dispatch()

        self.assert_correct_response()

    def test_dispatch_package_no_subscribers(self):
        """
        Tests the dispatch functionality when the given package does not have
        any subscribers.
        """
        self.run_dispatch()

        self.assert_correct_response()


from dispatch.custom_email_message import CustomEmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


class CustomEmailMessageTest(TestCase):
    """
    Tests the ``CustomEmailMessage`` class.
    """
    def create_multipart(self):
        """
        Helper method creates a multipart message.
        """
        msg = MIMEMultipart()
        msg.attach(self.prepare_part(b'data'))
        return msg

    def prepare_part(self, data):
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(data)
        encoders.encode_base64(part)
        return part

    def test_sent_message_same_as_original(self):
        """
        Tests that an ``email.message.Message`` instance sent by using the
        ``CustomEmailMessage`` class is the same as the original message.
        """
        msg = self.create_multipart()
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertEqual(msg.as_string(), mail.outbox[0].message().as_string())

    def test_attachment_included(self):
        """
        Tests that an attachment included in the ``CustomEmailMessage``
        instance is sent with the rest of the message.
        """
        msg = self.create_multipart()
        attachment = self.prepare_part(b'new_data')
        msg.attach(attachment)
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertIn(attachment, mail.outbox[0].message().get_payload())
