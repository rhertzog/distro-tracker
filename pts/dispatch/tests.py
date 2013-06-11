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
        found in all the forwarded messages.
        """
        for msg in mail.outbox:
            msg = msg.message()
            for header_name, header_value in self.headers:
                if header_name.lower() == 'to':
                    continue
                self.assertIn(
                    header_value, msg.get_all(header_name),
                    '{header_name}: {header_value} not found in {all}'.format(
                        header_name=header_name,
                        header_value=header_value,
                        all=msg.get_all(header_name)))

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
        all_forwards = [
            extract_email_address_from_header(msg.message()['To'])
            for msg in mail.outbox
        ]
        package = get_or_none(Package, name=self.package_name)
        if not package:
            subscriptions = []
        else:
            subscriptions = package.subscriptions.all()
        self.assertEqual(
            len(mail.outbox), len(subscriptions))
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
