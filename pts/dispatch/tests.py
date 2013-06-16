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

from pts.core.models import Package, Subscription, Keyword
from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_or_none
from pts.core.utils import verp
from pts import dispatch

from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN


class DispatchTestHelperMixin(object):
    def clear_message(self):
        self.message = Message()
        self.headers = []

    def set_package_name(self, package_name):
        self.package_name = package_name
        self.add_header('To', '{package}@{pts_fqdn}'.format(
            package=self.package_name,
            pts_fqdn=PTS_FQDN))

    def set_message_content(self, content):
        self.message.set_payload(content)

    def add_header(self, header_name, header_value):
        self.message.add_header(header_name, header_value)
        self.headers.append((header_name, header_value))

    def set_header(self, header_name, header_value):
        if header_name in self.message:
            del self.message[header_name]
        self.add_header(header_name, header_value)

    def run_dispatch(self, sent_to_address=None):
        dispatch.process(self.message.as_string(), sent_to_address)

    def subscribe_user_to_package(self, user_email, package, active=True):
        """
        Helper method which subscribes the given user to the given package.
        """
        Subscription.objects.create_for(
            package_name=package,
            email=user_email,
            active=active)

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

    def assert_all_new_headers_found(self, keyword='default'):
        """
        Helper method checks if all the necessary new headers are incldued in
        all the forwarded messages.
        """
        headers = [
            ('X-Loop', '{package}@{pts_fqdn}'.format(
                package=self.package_name,
                pts_fqdn=PTS_FQDN)),
            ('X-PTS-Package', self.package_name),
            ('X-Debian-Package', self.package_name),
            ('X-PTS-Keyword', keyword),
            ('X-Debian', 'PTS'),
            ('Precedence', 'list'),
            ('List-Unsubscribe',
                '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                    control_email=PTS_CONTROL_EMAIL,
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

    def assert_correct_forwards(self, keyword='default'):
        """
        Helper method checks if the mail was forwarded to all users who are
        subscribed to the package.
        """
        package = get_or_none(Package, name=self.package_name)
        if not package:
            subscriptions = []
        else:
            subscriptions = package.subscription_set.all_active(keyword)
        self.assertEqual(
            len(mail.outbox), len(subscriptions))
        # Extract addresses from the sent mails envelope headers
        all_forwards = [
            extract_email_address_from_header(message.to[0])
            for message in mail.outbox
            if len(message.to) == 1
        ]
        for subscription in subscriptions:
            self.assertIn(
                subscription.email_user.email, all_forwards)

    def assert_correct_forward_content(self):
        """
        Helper method checks if the forwarded mails contain the same content
        as the original message.
        """
        original = self.message.get_payload(decode=True).decode('ascii')
        for msg in mail.outbox:
            fwd = msg.message().get_payload(decode=True).decode('ascii')
            self.assertEqual(original, fwd)

    def assert_correct_verp(self):
        """
        Helper method which checks that the VERP header is correctly set in all
        outgoing messages.
        """
        for msg in mail.outbox:
            bounce_address, user_address = verp.decode(msg.from_email)
            self.assertTrue(bounce_address.startswith('bounces+'))
            self.assertEqual(user_address, msg.to[0])

    def assert_correct_response(self, keyword='default'):
        """
        Helper method checks the result of running the dispatch processor.
        """
        self.assert_correct_forwards(keyword=keyword)
        self.assert_all_old_headers_found()
        self.assert_all_new_headers_found(keyword=keyword)
        self.assert_correct_forward_content()
        self.assert_correct_verp()


class DispatchBaseTest(TestCase, DispatchTestHelperMixin):
    def setUp(self):
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.add_header('X-Loop', 'owner@bugs.debian.org')
        self.add_header('X-PTS-Approved', '1')
        self.set_message_content('message content')

        self.package = Package.objects.create(name=self.package_name)

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

    def test_dispatch_inactive_subscription(self):
        """
        Tests the dispatch functionality when the subscriber's subscription
        is inactive.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name,
                                       active=False)
        self.subscribe_user_to_package('user2@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_correct_response()

    def test_dispatch_package_email_in_environment(self):
        """
        Tests the dispatch functionality when the envelope to address differs
        from the message to address.
        """
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.add_header('X-PTS-Approved', '1')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('To', 'Someone <someone@domain.com>')
        address = '{package}@{pts_fqdn}'.format(package=self.package_name,
                                                pts_fqdn=PTS_FQDN)
        self.add_header('Cc', address)
        self.add_header('Subject', 'Some subject')
        self.add_header('X-Loop', 'owner@bugs.debian.org')
        self.set_message_content('message content')

        self.run_dispatch(address)

        self.assert_correct_response()


class DispatchKeywordTest(TestCase, DispatchTestHelperMixin):
    def setUp(self):
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.set_message_content('message content')

        self.package = Package.objects.create(name=self.package_name)

    def run_dispatch(self, keyword=''):
        if keyword:
            local_part = self.package_name + '_' + keyword
        else:
            local_part = self.package_name
        DispatchTestHelperMixin.run_dispatch(
            self,
            '{package}@{fqdn}'.format(package=local_part,
                                      fqdn=PTS_FQDN))

    def subscribe_user_with_keyword(self, keyword):
        """
        Creates a user subscribed to the package with the given keyword.
        """
        subscription = Subscription.objects.create_for(
            email='some-user@asdf.com',
            package_name=self.package.name
        )
        subscription.keywords.add(Keyword.objects.get(name=keyword))
        subscription = Subscription.objects.create_for(
            email='some-user2@asdf.com',
            package_name=self.package.name
        )
        subscription.keywords.add(Keyword.objects.get(name=keyword))

    def test_dispatch_keyword_in_address(self):
        """
        Tests the dispatch functionality when the keyword of the message is
        given in the address the message was sent to (srcpackage_keyword)
        """
        self.subscribe_user_with_keyword('cvs')

        self.run_dispatch('cvs')

        self.assert_correct_response(keyword='cvs')

    def test_dispatch_bts_control(self):
        """
        Tests that the dispatch properly tags a message as bts-control
        """
        self.set_header('X-Debian-PR-Message', 'transcript of something')
        self.set_header('X-Loop', 'owner@bugs.debian.org')
        self.subscribe_user_with_keyword('bts-control')

        self.run_dispatch()

        self.assert_correct_response(keyword='bts-control')

    def test_dispatch_bts(self):
        """
        Tests that the dispatch properly tags a message as bts
        """
        self.set_header('X-Debian-PR-Message', '1')
        self.set_header('X-Loop', 'owner@bugs.debian.org')
        self.subscribe_user_with_keyword('bts')

        self.run_dispatch()

        self.assert_correct_response(keyword='bts')

    def test_dispatch_upload_source(self):
        self.clear_message()
        self.set_header('Subject', 'Accepted 0.1 in unstable')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('Files\nchecksum lib.dsc\ncheck lib2.dsc')
        self.subscribe_user_with_keyword('upload-source')

        self.run_dispatch()

        self.assert_correct_response(keyword='upload-source')

    def test_dispatch_upload_binary(self):
        self.clear_message()
        self.set_header('Subject', 'Accepted 0.1 in unstable')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('afgdfgdrterfg')
        self.subscribe_user_with_keyword('upload-binary')

        self.run_dispatch()

        self.assert_correct_response(keyword='upload-binary')

    def test_dispatch_katie_other(self):
        self.clear_message()
        self.set_header('Subject', 'Comments regarding some changes')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('afgdfgdrterfg')
        self.subscribe_user_with_keyword('katie-other')

        self.run_dispatch()

        self.assert_correct_response(keyword='katie-other')

    def test_unknown_keyword(self):
        self.run_dispatch('unknown-keyword')

        self.assert_correct_response(keyword='unknown-keyword')


from pts.dispatch.custom_email_message import CustomEmailMessage
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
