# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for the :mod:`distro_tracker.mail.mail_news` app.
"""

from __future__ import unicode_literals
from distro_tracker.test import TestCase, SimpleTestCase
from django.utils import six
from django.utils.six.moves import mock
from django.utils.encoding import force_bytes
from distro_tracker.core.models import SourcePackageName, SourcePackage
from distro_tracker.core.models import News
from distro_tracker.mail.mail_news import process
from distro_tracker.mail.management.commands.tracker_receive_news import (
    Command as MailNewsCommand)

from email.message import Message


class BasicNewsGeneration(TestCase):
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')
        self.message = Message()

    def set_subject(self, subject):
        if 'Subject' in self.message:
           del self.message['Subject']
        self.message['Subject'] = subject

    def add_header(self, header_name, header_value):
        self.message[header_name] = header_value

    def set_message_content(self, content):
        self.message.set_payload(content)

    def process_mail(self):
        process(force_bytes(self.message.as_string(), 'utf-8'))

    def test_creates_news_from_email(self):
        """
        Tets that a news is created from an email with the correct header
        information.
        """
        subject = 'Some message'
        content = 'Some message content'
        self.set_subject(subject)
        self.add_header('X-Distro-Tracker-Package', self.package.name)
        self.set_message_content(content)

        self.process_mail()

        # A news item is created
        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        # The title of the news is set correctly.
        self.assertEqual(subject, news.title)
        self.assertIn(content, news.content.decode('utf-8'))
        # The content type is set to render email messages
        self.assertEqual(news.content_type, 'message/rfc822')

    def test_create_news_url_from_email(self):
        """
        Tests that when an X-Distro-Tracker-Url header is given the news content is the
        URL, not the email message.
        """
        subject = 'Some message'
        content = 'Some message content'
        self.set_subject(subject)
        self.add_header('X-Distro-Tracker-Package', self.package.name)
        url = 'http://some-url.com'
        self.add_header('X-Distro-Tracker-Url', url)
        self.set_message_content(content)

        self.process_mail()

        # A news item is created
        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        # The title of the news is set correctly.
        self.assertEqual(url, news.title)
        self.assertIn(url, news.content.strip())

    def test_create_news_package_does_not_exist(self):
        """
        Tests that when the package given in X-Distro-Tracker-Package does not exist, no
        news items are created.
        """
        subject = 'Some message'
        content = 'Some message content'
        self.set_subject(subject)
        self.add_header('X-Distro-Tracker-Package', 'no-exist')
        self.set_message_content(content)
        # Sanity check - there are no news at the beginning
        self.assertEqual(0, News.objects.count())

        self.process_mail()

        # There are still no news
        self.assertEqual(0, News.objects.count())

    @mock.patch('distro_tracker.mail.mail_news.vendor.call')
    def test_create_news_calls_vendor_function(self, mock_vendor_call):
        """
        Tests that the vendor-provided function is called during the processing
        of the news.
        """
        subject = 'Some message'
        content = 'Some message content'
        # Do not add any headers.
        self.set_subject(subject)
        self.set_message_content(content)
        # Make it look like the vendor does not implement the function
        mock_vendor_call.return_value = (None, False)

        self.process_mail()

        # The function was called?
        self.assertTrue(mock_vendor_call.called)
        # The correct vendor function was asked for?
        self.assertEqual(mock_vendor_call.call_args[0][0], 'create_news_from_email_message')


class MailNewsManagementCommandTest(SimpleTestCase):
    """
    Tests that the :mod:`distro_tracker.mail.management.commands.tracker_receive_news`
    management command calls the correct function.
    """
    @mock.patch('distro_tracker.mail.management.commands.tracker_receive_news.process')
    def test_calls_process(self, mock_process):
        cmd = MailNewsCommand()
        cmd.input_file = mock.create_autospec(six.BytesIO)

        mock_process.assert_called()
