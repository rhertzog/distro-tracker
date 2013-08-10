# -*- coding: utf-8 -*-

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
This module contains the tests for the dispatch functionality
(:py:mod:`pts.mail.dispatch` module) of PTS.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.core import mail
from django.utils import timezone
from django.utils.encoding import force_bytes

from email.message import Message
from datetime import timedelta

from pts.core.models import PackageName, Subscription, Keyword
from pts.core.utils import verp
from pts.core.utils import get_decoded_message_payload
from pts.core.utils import pts_render_to_string
from pts.mail import dispatch

from pts.mail.models import EmailUserBounceStats


from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN

import logging
logging.disable(logging.CRITICAL)


class DispatchTestHelperMixin(object):
    """
    A mixin containing methods to assist testing dispatch functionality.
    """
    def clear_message(self):
        """
        Clears the test message being built.
        """
        self.message = Message()
        self.headers = []

    def set_package_name(self, package_name):
        """
        Sets the name of the test package.

        :param package_name: The new name of the test package
        """
        self.package_name = package_name
        self.add_header('To', '{package}@{pts_fqdn}'.format(
            package=self.package_name,
            pts_fqdn=PTS_FQDN))

    def set_message_content(self, content):
        """
        Sets the content of the test message.

        :param content: New content
        """
        self.message.set_payload(content)

    def add_header(self, header_name, header_value):
        """
        Adds a header to the test message.

        :param header_name: The name of the header which is to be added
        :param header_value: The value of the header which is to be added
        """
        self.message.add_header(header_name, header_value)
        self.headers.append((header_name, header_value))

    def set_header(self, header_name, header_value):
        """
        Sets a header of the test message to the given value.
        If the header previously existed in the message, it is overwritten.

        :param header_name: The name of the header to be set
        :param header_value: The new value of the header to be set.
        """
        if header_name in self.message:
            del self.message[header_name]
        self.add_header(header_name, header_value)

    def run_dispatch(self, sent_to_address=None):
        """
        Starts the dispatch process.
        """
        dispatch.process(
            force_bytes(self.message.as_string(), 'utf-8'),
            sent_to_address
        )

    def subscribe_user_with_keyword(self, email, keyword):
        """
        Creates a user subscribed to the package with the given keyword.
        """
        subscription = Subscription.objects.create_for(
            email=email,
            package_name=self.package.name
        )
        subscription.keywords.add(Keyword.objects.get(name=keyword))

    def subscribe_user_to_package(self, user_email, package, active=True):
        """
        Helper method which subscribes the given user to the given package.
        """
        Subscription.objects.create_for(
            package_name=package,
            email=user_email,
            active=active)

    def make_address_with_keyword(self, package, keyword):
        """
        Returns the address for the package which corresponds to the given
        keyword.
        """
        return '{package}_{keyword}@{pts_fqdn}'.format(
            package=package, keyword=keyword, pts_fqdn=PTS_FQDN)

    def assert_message_forwarded_to(self, email):
        """
        Asserts that the message was forwarded to the given email.
        """
        self.assertTrue(mail.outbox)
        self.assertIn(email, (message.to[0] for message in mail.outbox))

    def assert_forward_content_equal(self, content):
        """
        Asserts that the content of the forwarded message is equal to the given
        ``content``.
        """
        msg = mail.outbox[0].message()
        self.assertEqual(get_decoded_message_payload(msg), content)

    def assert_all_headers_found(self, headers):
        """
        Asserts that all the given headers are found in the forwarded messages.
        """
        for msg in mail.outbox:
            msg = msg.message()
            for header_name, header_value in headers:
                self.assertIn(header_name, msg)
                self.assertIn(
                    header_value, msg.get_all(header_name),
                    '{header_name}: {header_value} not found in {all}'.format(
                        header_name=header_name,
                        header_value=header_value,
                        all=msg.get_all(header_name)))

    def assert_header_equal(self, header_name, header_value):
        """
        Asserts that the header's value is equal to the given value.
        """
        for msg in mail.outbox:
            msg = msg.message()
            self.assertEqual(msg[header_name], header_value)


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

        self.package = PackageName.objects.create(name=self.package_name)

    def test_dispatched_mail_to_bytes(self):
        """
        Tests that the message instance to be sent to subscribers can be
        serialized to bytes with no errors when the body contains utf-8
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.set_message_content('üößšđžčć한글')
        self.message.set_charset('utf-8')

        self.run_dispatch()

        msg = mail.outbox[0]
        # No exception thrown trying to get the entire message's content as bytes
        content = msg.message().as_string()
        # The content is actually bytes
        self.assertTrue(isinstance(content, bytes))

    def test_dispatch_to_subscribers(self):
        """
        Tests the dispatch functionality when there users subscribed to it.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.subscribe_user_to_package('user2@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_message_forwarded_to('user2@domain.com')

    def test_dispatch_all_old_headers(self):
        """
        Tests the dispatch functionality to check if all old headers are found
        in the forwarded message in the correct order.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        for old_header, fwd_header in zip(self.message.items(),
                                          mail.outbox[0].message().items()):
            self.assertEqual(old_header, fwd_header)

    def test_envelope_from_address(self):
        """
        Tests that the envelope from address is created specially for each user
        in order to track their bounced messages.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        msg = mail.outbox[0]
        bounce_address, user_address = verp.decode(msg.from_email)
        self.assertTrue(bounce_address.startswith('bounces+'))
        self.assertEqual(user_address, msg.to[0])

    def test_correct_foward_content(self):
        """
        Tests that the content of the forwarded message is unchanged.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        original = 'Content of the message'
        self.set_message_content(original)

        self.run_dispatch()

        self.assert_forward_content_equal(original)

    def test_dispatch_all_new_headers(self):
        """
        Tests the dispatch functionality to check if all required new headers
        are found in the forwarded message.
        """
        headers = [
            ('X-Loop', '{package}@{pts_fqdn}'.format(
                package=self.package_name,
                pts_fqdn=PTS_FQDN)),
            ('X-PTS-Package', self.package_name),
            ('X-PTS-Keyword', 'default'),
            ('Precedence', 'list'),
            ('List-Unsubscribe',
                '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                    control_email=PTS_CONTROL_EMAIL,
                    package=self.package_name)),
        ]
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_all_headers_found(headers)

    def test_dispatch_package_doesnt_exist(self):
        """
        Tests the dispatch functionality when the given package does not
        exist.
        """
        self.set_package_name('non-existent-package')

        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 0)

    def test_dispatch_package_no_subscribers(self):
        """
        Tests the dispatch functionality when the given package does not have
        any subscribers.
        """
        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 0)

    def test_dispatch_inactive_subscription(self):
        """
        Tests the dispatch functionality when the subscriber's subscription
        is inactive.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name,
                                       active=False)

        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 0)

    def test_dispatch_package_email_in_environment(self):
        """
        Tests the dispatch functionality when the envelope to address differs
        from the message to header address.
        """
        self.set_header('To', 'Someone <someone@domain.com>')
        address = '{package}@{pts_fqdn}'.format(package=self.package_name,
                                                pts_fqdn=PTS_FQDN)
        self.add_header('Cc', address)
        # Make sure there is a user to forward the message to
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch(address)

        self.assert_message_forwarded_to('user@domain.com')

    def test_utf8_message_dispatch(self):
        """
        Tests that a message is properly dispatched if it was utf-8 encoded.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.set_message_content('üößšđžčć한글')
        self.message.set_charset('utf-8')

        self.run_dispatch()

        self.assert_forward_content_equal('üößšđžčć한글')

    def test_forwarded_mail_recorded(self):
        """
        Tests that when a mail is forwarded it is logged in the user's bounce
        information structure.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        user = EmailUserBounceStats.objects.get(email='user@domain.com')

        self.run_dispatch()

        bounce_stats = user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_sent, 1)

    def test_xloop_already_set(self):
        """
        Tests that the message is dropped when the X-Loop header is already
        set.
        """
        self.set_header('X-Loop', 'somevalue')
        self.set_header('X-Loop', self.package_name + '@' + PTS_FQDN)
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 0)

    def test_dispatch_keyword_in_address(self):
        """
        Tests the dispatch functionality when the keyword of the message is
        given in the address the message was sent to (srcpackage_keyword)
        """
        self.subscribe_user_with_keyword('user@domain.com', 'vcs')
        address = self.make_address_with_keyword(self.package_name, 'vcs')

        self.run_dispatch(address)

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'vcs')

    def test_unknown_keyword(self):
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        address = self.make_address_with_keyword(self.package_name, 'unknown')

        self.run_dispatch(address)

        self.assertEqual(len(mail.outbox), 0)


class BounceMessagesTest(TestCase, DispatchTestHelperMixin):
    """
    Tests the proper handling of bounced emails.
    """
    def setUp(self):
        super(BounceMessagesTest, self).setUp()
        self.message = Message()
        self.message.add_header('Subject', 'bounce')
        PackageName.objects.create(name='dummy-package')
        self.subscribe_user_to_package('user@domain.com', 'dummy-package')
        self.user = EmailUserBounceStats.objects.get(email='user@domain.com')

    def create_bounce_address(self, to):
        """
        Helper method creating a bounce address for the given destination email
        """
        bounce_address = 'bounces+{date}@{pts_fqdn}'.format(
            date=timezone.now().date().strftime('%Y%m%d'),
            pts_fqdn=PTS_FQDN)
        return verp.encode(bounce_address, to)

    def add_sent(self, user, date):
        """
        Adds a sent mail record for the given user.
        """
        EmailUserBounceStats.objects.add_sent_for_user(email=user.email,
                                                       date=date)

    def add_bounce(self, user, date):
        """
        Adds a bounced mail record for the given user.
        """
        EmailUserBounceStats.objects.add_bounce_for_user(email=user.email,
                                                         date=date)

    def test_bounce_recorded(self):
        """
        Tests that a received bounce is recorded.
        """
        # Make sure the user has no prior bounce stats
        self.assertEqual(self.user.bouncestats_set.count(), 0)

        self.run_dispatch(self.create_bounce_address(self.user.email))

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_bounced, 1)
        self.assertEqual(self.user.subscription_set.count(), 1)

    def test_bounce_over_limit(self):
        """
        Tests that all the user's subscriptions are dropped when too many
        bounces are received.
        """
        # Set up some prior bounces - one each day.
        date = timezone.now().date()
        for days in range(1, settings.PTS_MAX_DAYS_TOLERATE_BOUNCE):
            self.add_sent(self.user, date - timedelta(days=days))
            self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        packages_subscribed_to = [
            subscription.package.name
            for subscription in self.user.subscription_set.all()
        ]
        self.assertTrue(len(packages_subscribed_to) > 0)

        # Receive a bounce message.
        self.run_dispatch(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have been dropped.
        self.assertEqual(self.user.subscription_set.count(), 0)
        # A notification was sent to the user.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)
        # Check that the content of the email is correct.
        self.assertEqual(mail.outbox[0].body, pts_render_to_string(
            'dispatch/unsubscribed-due-to-bounces-email.txt', {
                'email': self.user.email,
                'packages': packages_subscribed_to
            }
        ))

    def test_bounce_under_limit(self):
        """
        Tests that the user's subscriptions are not dropped when there are
        too many bounces for less days than tolerated.
        """
        # Set up some prior bounces - one each day.
        date = timezone.now().date()
        for days in range(1, settings.PTS_MAX_DAYS_TOLERATE_BOUNCE - 1):
            self.add_sent(self.user, date - timedelta(days=days))
            self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        subscription_count = self.user.subscription_set.count()
        self.assertTrue(subscription_count > 0)

        # Receive a bounce message.
        self.run_dispatch(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have not been dropped.
        self.assertEqual(self.user.subscription_set.count(), subscription_count)

    def test_bounces_not_every_day(self):
        """
        Tests that the user's subscriptions are not dropped when there is a day
        which had more sent messages.
        """
        date = timezone.now().date()
        for days in range(1, settings.PTS_MAX_DAYS_TOLERATE_BOUNCE):
            self.add_sent(self.user, date - timedelta(days=days))
            if days % 2 == 0:
                self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        subscription_count = self.user.subscription_set.count()
        self.assertTrue(subscription_count > 0)

        # Receive a bounce message.
        self.run_dispatch(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have not been dropped.
        self.assertEqual(self.user.subscription_set.count(), subscription_count)


class BounceStatsTest(TestCase):
    """
    Tests for the ``pts.mail.models`` handling users' bounce information.
    """
    def setUp(self):
        self.user = EmailUserBounceStats.objects.create(email='user@domain.com')
        self.package = PackageName.objects.create(name='dummy-package')

    def test_add_sent_message(self):
        """
        Tests that a new sent message record is correctly added.
        """
        date = timezone.now().date()
        EmailUserBounceStats.objects.add_sent_for_user(self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_sent, 1)

    def test_add_bounce_message(self):
        """
        Tests that a new bounced message record is correctly added.
        """
        date = timezone.now().date()
        EmailUserBounceStats.objects.add_bounce_for_user(self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_bounced, 1)

    def test_number_of_records_limited(self):
        """
        Tests that only as many records as the number of tolerated bounce days
        are kept.
        """
        days = settings.PTS_MAX_DAYS_TOLERATE_BOUNCE
        current_date = timezone.now().date()
        dates = [
            current_date + timedelta(days=delta)
            for delta in range(1, days + 5)
        ]

        for date in dates:
            EmailUserBounceStats.objects.add_bounce_for_user(
                self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        # Limited number
        self.assertEqual(bounce_stats.count(),
                         settings.PTS_MAX_DAYS_TOLERATE_BOUNCE)
        # Only the most recent dates are kept.
        bounce_stats_dates = [info.date for info in bounce_stats]
        for date in dates[-days:]:
            self.assertIn(date, bounce_stats_dates)
