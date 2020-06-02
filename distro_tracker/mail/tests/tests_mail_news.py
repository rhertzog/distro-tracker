# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for the :mod:`distro_tracker.mail.mail_news` app.
"""

import io
from email.message import Message
from unittest import mock

from distro_tracker.core.models import News, SourcePackage, SourcePackageName
from distro_tracker.mail.mail_news import create_news
from distro_tracker.mail.management.commands.tracker_receive_news import \
    Command as MailNewsCommand
from distro_tracker.test import SimpleTestCase, TestCase


class BasicNewsGeneration(TestCase):
    def setUp(self):
        self.package_name = \
            SourcePackageName.objects.create(name='dummy-package')
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
        create_news(self.message, self.package_name)

    def test_create_news_from_email(self):
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


class MailNewsManagementCommandTest(SimpleTestCase):
    """
    Tests that the
    :mod:`distro_tracker.mail.management.commands.tracker_receive_news`
    management command calls the correct function.
    """
    @mock.patch(
        'distro_tracker.mail.management.commands.tracker_receive_news.'
        'classify_message')
    def test_calls_process(self, mock_classify):
        mock_classify.return_value = ('package', 'keyword')
        cmd = MailNewsCommand()
        cmd.input_file = io.TextIOWrapper(io.BytesIO(b'''From: test@example.net
Subject: foo

bla
                                    '''))
        cmd.handle()
        self.assertTrue(mock_classify.called)
