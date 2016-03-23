# -*- coding: utf-8 -*-

# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
This module contains the tests for the dispatch functionality
(:py:mod:`distro_tracker.mail.dispatch` module) of distro-tracker.
"""
from __future__ import unicode_literals
from email.message import Message
from datetime import timedelta
import logging

from django.core import mail
from django.conf import settings
from django.utils import timezone
from django.utils.six.moves import mock

from distro_tracker.accounts.models import UserEmail
from distro_tracker.accounts.models import User
from distro_tracker.core.models import PackageName, Subscription, Keyword
from distro_tracker.core.models import Team
from distro_tracker.core.utils import verp
from distro_tracker.core.utils import get_decoded_message_payload
from distro_tracker.core.utils import distro_tracker_render_to_string
from distro_tracker.core.utils.email_messages import (
    patch_message_for_django_compat)
from distro_tracker.mail import dispatch
from distro_tracker.mail.models import UserEmailBounceStats
from distro_tracker.test import TestCase

DISTRO_TRACKER_CONTROL_EMAIL = settings.DISTRO_TRACKER_CONTROL_EMAIL
DISTRO_TRACKER_FQDN = settings.DISTRO_TRACKER_FQDN

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
        patch_message_for_django_compat(self.message)
        self.headers = []

    def set_package_name(self, package_name):
        """
        Sets the name of the test package.

        :param package_name: The new name of the test package
        """
        self.package_name = package_name
        self.add_header('To', '{package}@{distro_tracker_fqdn}'.format(
            package=self.package_name,
            distro_tracker_fqdn=DISTRO_TRACKER_FQDN))

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

    def run_dispatch(self, package=None, keyword=None):
        """
        Starts the dispatch process.
        """
        dispatch.process(
            self.message,
            package=package or self.package_name,
            keyword=keyword,
        )

    def run_forward(self, package=None, keyword=None):
        """
        Starts the forward process.
        """
        dispatch.forward(
            self.message,
            package=package or self.package_name,
            keyword=keyword or "default",
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
        # Ensure we have some messages to check against
        self.assertTrue(len(mail.outbox) > 0)
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
        self.add_header('X-Distro-Tracker-Approved', '1')
        self.set_message_content('message content')

        self.package = PackageName.objects.create(name=self.package_name)

    def test_forward_mail_serialize_to_bytes(self):
        """
        Tests that the message instance to be sent to subscribers can be
        serialized to bytes with no errors when the body contains utf-8
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.set_message_content('üößšđžčć한글')
        self.message.set_charset('utf-8')

        self.run_forward()

        msg = mail.outbox[0]
        # No exception thrown trying to get the entire message as bytes
        content = msg.message().as_string()
        # self.assertIs(msg.message(), self.message)
        # The content is actually bytes
        self.assertIsInstance(content, bytes)

    def test_forward_to_subscribers(self):
        """
        Tests the forward functionality when there users subscribed to it.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.subscribe_user_to_package('user2@domain.com', self.package_name)

        self.run_forward()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_message_forwarded_to('user2@domain.com')

    def test_forward_all_old_headers(self):
        """
        Tests the forward functionality to check if all old headers are found
        in the forwarded message in the correct order.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_forward()

        for old_header, fwd_header in zip(self.message.items(),
                                          mail.outbox[0].message().items()):
            self.assertEqual(old_header, fwd_header)

    def test_envelope_from_address(self):
        """
        Tests that the envelope from address is created specially for each user
        in order to track their bounced messages.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_forward()

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

        self.run_forward()

        self.assert_forward_content_equal(original)

    def test_forward_all_new_headers(self):
        """
        Tests the forward functionality to check if all required new headers
        are found in the forwarded message.
        """
        headers = [
            ('X-Loop', 'dispatch@{}'.format(DISTRO_TRACKER_FQDN)),
            ('X-Distro-Tracker-Package', self.package_name),
            ('X-Distro-Tracker-Keyword', 'default'),
            ('Precedence', 'list'),
            ('List-Id', '<{}.{}>'.format(self.package_name,
                                         DISTRO_TRACKER_FQDN)),
            ('List-Unsubscribe',
                '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                    control_email=DISTRO_TRACKER_CONTROL_EMAIL,
                    package=self.package_name)),
        ]
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_forward()

        self.assert_all_headers_found(headers)

    def test_forward_package_doesnt_exist(self):
        """
        Tests the forward functionality when the given package does not
        exist.
        """
        self.set_package_name('non-existent-package')

        self.run_forward()

        self.assertEqual(len(mail.outbox), 0)

    def test_forward_package_no_subscribers(self):
        """
        Tests the forward functionality when the given package does not have
        any subscribers.
        """
        self.run_forward()

        self.assertEqual(len(mail.outbox), 0)

    def test_forward_inactive_subscription(self):
        """
        Tests the forward functionality when the subscriber's subscription
        is inactive.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name,
                                       active=False)

        self.run_forward()

        self.assertEqual(len(mail.outbox), 0)

    def test_utf8_message_forward(self):
        """
        Tests that a message is properly forwarded if it was utf-8 encoded.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        self.set_message_content('üößšđžčć한글')
        self.message.set_charset('utf-8')

        self.run_forward()

        self.assert_forward_content_equal('üößšđžčć한글')

    def test_forwarded_mail_recorded(self):
        """
        Tests that when a mail is forwarded it is logged in the user's bounce
        information structure.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)
        user = UserEmailBounceStats.objects.get(email='user@domain.com')

        self.run_forward()

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
        self.set_header('X-Loop', 'dispatch@' + DISTRO_TRACKER_FQDN)
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_forward()

        self.assertEqual(len(mail.outbox), 0)

    def test_forward_keyword_in_address(self):
        """
        Tests the forward functionality when the keyword of the message is
        given in the address the message was sent to (srcpackage_keyword)
        """
        self.subscribe_user_with_keyword('user@domain.com', 'vcs')

        self.run_forward(keyword='vcs')

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-Distro-Tracker-Keyword', 'vcs')

    def test_unknown_keyword(self):
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_forward(keyword='unknown')

        self.assertEqual(len(mail.outbox), 0)

    def patch_forward(self):
        patcher = mock.patch('distro_tracker.mail.dispatch.forward')
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def test_dispatch_calls_forward(self):
        mock_forward = self.patch_forward()
        self.run_dispatch('foo', 'bts')
        mock_forward.assert_called_with(self.message, 'foo', 'bts')

    def test_dispatch_does_not_call_forward_when_package_not_identified(self):
        mock_forward = self.patch_forward()
        self.package_name = None
        self.run_dispatch(None, None)
        self.assertFalse(mock_forward.called)

    @mock.patch('distro_tracker.mail.dispatch.classify_message')
    def test_dispatch_does_not_call_forward_when_classify_raises_exception(
            self, mock_classify):
        mock_forward = self.patch_forward()
        mock_classify.side_effect = dispatch.SkipMessage
        self.run_dispatch('foo', 'bts')
        self.assertFalse(mock_forward.called)

    def test_dispatch_calls_forward_with_multiple_packages(self):
        mock_forward = self.patch_forward()
        self.run_dispatch(['foo', 'bar', 'baz'], 'bts')
        mock_forward.assert_has_calls([
            mock.call(self.message, 'foo', 'bts'),
            mock.call(self.message, 'bar', 'bts'),
            mock.call(self.message, 'baz', 'bts')
        ])


class ClassifyMessageTests(TestCase):

    def setUp(self):
        self.message = Message()

    def run_classify(self, package=None, keyword=None):
        return dispatch.classify_message(self.message, package=package,
                                         keyword=keyword)

    def patch_vendor_call(self, return_value=None):
        patcher = mock.patch('distro_tracker.vendor.call')
        mocked = patcher.start()
        mocked.return_value = (return_value, return_value is not None)
        self.addCleanup(patcher.stop)
        return mocked

    def test_classify_calls_vendor_classify_message(self):
        mock_vendor_call = self.patch_vendor_call()
        self.run_classify()
        mock_vendor_call.assert_called_with('classify_message', self.message,
                                            package=None, keyword=None)

    def test_classify_returns_default_values_without_vendor_classify(self):
        self.patch_vendor_call()
        package, keyword = self.run_classify(package='abc', keyword='vcs')
        self.assertEqual(package, 'abc')
        self.assertEqual(keyword, 'vcs')

    def test_classify_return_vendor_values_when_available(self):
        self.patch_vendor_call(('vendorpkg', 'bugs'))
        package, keyword = self.run_classify(package='abc', keyword='vcs')
        self.assertEqual(package, 'vendorpkg')
        self.assertEqual(keyword, 'bugs')

    def test_classify_uses_default_keyword_when_unknown(self):
        self.patch_vendor_call(('vendorpkg', None))
        package, keyword = self.run_classify()
        self.assertEqual(package, 'vendorpkg')
        self.assertEqual(keyword, 'default')

    def test_classify_uses_values_supplied_in_headers(self):
        self.message['X-Distro-Tracker-Package'] = 'headerpkg'
        self.message['X-Distro-Tracker-Keyword'] = 'bugs'
        self.patch_vendor_call()
        package, keyword = self.run_classify()
        self.assertEqual(package, 'headerpkg')
        self.assertEqual(keyword, 'bugs')


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
        self.user = UserEmailBounceStats.objects.get(email='user@domain.com')

    def create_bounce_address(self, to):
        """
        Helper method creating a bounce address for the given destination email
        """
        bounce_address = 'bounces+{date}@{distro_tracker_fqdn}'.format(
            date=timezone.now().date().strftime('%Y%m%d'),
            distro_tracker_fqdn=DISTRO_TRACKER_FQDN)
        return verp.encode(bounce_address, to)

    def add_sent(self, user, date):
        """
        Adds a sent mail record for the given user.
        """
        UserEmailBounceStats.objects.add_sent_for_user(email=user.email,
                                                       date=date)

    def add_bounce(self, user, date):
        """
        Adds a bounced mail record for the given user.
        """
        UserEmailBounceStats.objects.add_bounce_for_user(email=user.email,
                                                         date=date)

    def test_bounce_recorded(self):
        """
        Tests that a received bounce is recorded.
        """
        # Make sure the user has no prior bounce stats
        self.assertEqual(self.user.bouncestats_set.count(), 0)

        dispatch.handle_bounces(self.create_bounce_address(self.user.email))

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_bounced, 1)
        self.assertEqual(self.user.emailsettings.subscription_set.count(), 1)

    def test_bounce_over_limit(self):
        """
        Tests that all the user's subscriptions are dropped when too many
        bounces are received.
        """
        # Set up some prior bounces - one each day.
        date = timezone.now().date()
        for days in range(1, settings.DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE):
            self.add_sent(self.user, date - timedelta(days=days))
            self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        packages_subscribed_to = [
            subscription.package.name
            for subscription in self.user.emailsettings.subscription_set.all()
        ]
        self.assertTrue(len(packages_subscribed_to) > 0)

        # Receive a bounce message.
        dispatch.handle_bounces(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have been dropped.
        self.assertEqual(self.user.emailsettings.subscription_set.count(), 0)
        # A notification was sent to the user.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)
        # Check that the content of the email is correct.
        self.assertEqual(mail.outbox[0].body, distro_tracker_render_to_string(
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
        for days in range(1,
                          settings.DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE - 1):
            self.add_sent(self.user, date - timedelta(days=days))
            self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        subscription_count = self.user.emailsettings.subscription_set.count()
        self.assertTrue(subscription_count > 0)

        # Receive a bounce message.
        dispatch.handle_bounces(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have not been dropped.
        self.assertEqual(self.user.emailsettings.subscription_set.count(),
                         subscription_count)

    def test_bounces_not_every_day(self):
        """
        Tests that the user's subscriptions are not dropped when there is a day
        which had more sent messages.
        """
        date = timezone.now().date()
        for days in range(1, settings.DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE):
            self.add_sent(self.user, date - timedelta(days=days))
            if days % 2 == 0:
                self.add_bounce(self.user, date - timedelta(days=days))
        # Set up a sent mail today.
        self.add_sent(self.user, date)
        # Make sure there were at least some subscriptions
        subscription_count = self.user.emailsettings.subscription_set.count()
        self.assertTrue(subscription_count > 0)

        # Receive a bounce message.
        dispatch.handle_bounces(self.create_bounce_address(self.user.email))

        # Assert that the user's subscriptions have not been dropped.
        self.assertEqual(self.user.emailsettings.subscription_set.count(),
                         subscription_count)

    def test_bounce_recorded_with_differing_case(self):
        self.subscribe_user_to_package('SomeOne@domain.com', 'dummy-package')
        self.user = UserEmailBounceStats.objects.get(email='SomeOne@domain.com')

        self.assertEqual(self.user.bouncestats_set.count(), 0)

        dispatch.handle_bounces(
            self.create_bounce_address('someone@domain.com'))

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_bounced, 1)

    def test_bounce_handler_with_unknown_user_email(self):
        # This should just not generate any exception...
        dispatch.handle_bounces(
            self.create_bounce_address('unknown-user@domain.com'))


class BounceStatsTest(TestCase):
    """
    Tests for the ``distro_tracker.mail.models`` handling users' bounce
    information.
    """
    def setUp(self):
        self.user = UserEmailBounceStats.objects.get(
            email=UserEmail.objects.create(email='user@domain.com'))
        self.package = PackageName.objects.create(name='dummy-package')

    def test_add_sent_message(self):
        """
        Tests that a new sent message record is correctly added.
        """
        date = timezone.now().date()
        UserEmailBounceStats.objects.add_sent_for_user(self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_sent, 1)

    def test_add_bounce_message(self):
        """
        Tests that a new bounced message record is correctly added.
        """
        date = timezone.now().date()
        UserEmailBounceStats.objects.add_bounce_for_user(self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        self.assertEqual(bounce_stats.count(), 1)
        self.assertEqual(bounce_stats[0].date, timezone.now().date())
        self.assertEqual(bounce_stats[0].mails_bounced, 1)

    def test_number_of_records_limited(self):
        """
        Tests that only as many records as the number of tolerated bounce days
        are kept.
        """
        days = settings.DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE
        current_date = timezone.now().date()
        dates = [
            current_date + timedelta(days=delta)
            for delta in range(1, days + 5)
        ]

        for date in dates:
            UserEmailBounceStats.objects.add_bounce_for_user(
                self.user.email, date)

        bounce_stats = self.user.bouncestats_set.all()
        # Limited number
        self.assertEqual(bounce_stats.count(),
                         settings.DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE)
        # Only the most recent dates are kept.
        bounce_stats_dates = [info.date for info in bounce_stats]
        for date in dates[-days:]:
            self.assertIn(date, bounce_stats_dates)


class DispatchToTeamsTests(DispatchTestHelperMixin, TestCase):
    def setUp(self):
        super(DispatchToTeamsTests, self).setUp()
        self.password = 'asdf'
        self.user = User.objects.create_user(
            main_email='user@domain.com', password=self.password,
            first_name='', last_name='')
        self.team = Team.objects.create_with_slug(
            owner=self.user, name="Team name")
        self.team.add_members([self.user.emails.all()[0]])
        self.package = PackageName.objects.create(name='dummy-package')
        self.team.packages.add(self.package)
        self.user_email = UserEmail.objects.create(email='other@domain.com')

        # Setup a message which will be sent to the package
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.add_header('X-Loop', 'owner@bugs.debian.org')
        self.add_header('X-Distro-Tracker-Approved', '1')
        self.set_message_content('message content')

    def test_team_muted(self):
        """
        Tests that a message is not forwarded to the user when he has muted
        the team.
        """
        email = self.user.main_email
        membership = self.team.team_membership_set.get(user_email__email=email)
        membership.set_keywords(self.package, ['default'])
        membership.muted = True
        membership.save()

        self.run_forward()

        self.assertEqual(0, len(mail.outbox))

    def test_message_forwarded(self):
        """
        Tests that the message is forwarded to a team member when he has the
        correct keyword.
        """
        email = self.user.main_email
        membership = self.team.team_membership_set.get(user_email__email=email)
        membership.set_keywords(self.package, ['default'])

        self.run_forward()

        self.assert_message_forwarded_to(email)

    def test_message_not_forwarded_no_keyword(self):
        """
        Tests that a message is not forwarded to a team member that does not
        have the messages keyword set.
        """
        email = self.user.main_email
        membership = self.team.team_membership_set.get(user_email__email=email)
        membership.set_keywords(
            self.package,
            [k.name for k in Keyword.objects.exclude(name='default')])

        self.run_forward()

        self.assertEqual(0, len(mail.outbox))

    def test_forwarded_message_correct_headers(self):
        """
        Tests that the headers of the forwarded message are correctly set.
        """
        email = self.user.main_email
        membership = self.team.team_membership_set.get(user_email__email=email)
        membership.set_keywords(self.package, ['default'])

        self.run_forward()

        self.assert_header_equal('X-Distro-Tracker-Keyword', 'default')
        self.assert_header_equal('X-Distro-Tracker-Team', self.team.slug)
        self.assert_header_equal('X-Distro-Tracker-Package', self.package.name)

    def test_forward_multiple_teams(self):
        """
        Tests that a user gets the same message multiple times when he is a
        member of two teams that both have the same package.
        """
        new_team = Team.objects.create_with_slug(
            owner=self.user, name="Other team")
        new_team.packages.add(self.package)
        new_team.add_members([self.user.emails.all()[0]])

        self.run_forward()

        self.assertEqual(2, len(mail.outbox))
        for message, team in zip(mail.outbox, Team.objects.all()):
            message = message.message()
            self.assertEqual(message['X-Distro-Tracker-Team'], team.slug)

    def test_package_muted(self):
        """
        Tests that when the team membership is not muted, but the package
        which is a part of the membership is, no message is forwarded.
        """
        email = self.user.main_email
        membership = self.team.team_membership_set.get(user_email__email=email)
        membership.set_keywords(self.package, ['default'])
        membership.mute_package(self.package)

        self.run_forward()

        self.assertEqual(0, len(mail.outbox))
