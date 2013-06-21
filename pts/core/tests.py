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
Tests for the PTS core module.
"""
from __future__ import unicode_literals
from django.test import TestCase, SimpleTestCase
from django.test.utils import override_settings
from django.utils import six
from pts.core.models import Subscription, EmailUser, Package, BinaryPackage
from pts.core.models import Keyword
from pts.core.utils import verp
from pts.core.utils import message_from_bytes
from pts.dispatch.custom_email_message import CustomEmailMessage


class SubscriptionManagerTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.email_user = EmailUser.objects.create(email='email@domain.com')

    def create_subscription(self, package, email, active=True):
        """
        Helper method which creates a subscription for the given user to the
        given package.
        """
        return Subscription.objects.create_for(
            package_name=package,
            email=email,
            active=active)

    def test_create_for_existing_email(self):
        subscription = self.create_subscription(
            self.package.name, self.email_user.email)

        self.assertEqual(subscription.email_user, self.email_user)
        self.assertEqual(subscription.package, self.package)
        self.assertIn(self.email_user, self.package.subscriptions.all())
        self.assertTrue(subscription.active)

    def test_create_for_existing_email_inactive(self):
        """
        Tests the create_for method when creating an inactive subscription.
        """
        subscription = self.create_subscription(
            self.package.name, self.email_user.email, active=False)

        self.assertEqual(subscription.email_user, self.email_user)
        self.assertEqual(subscription.package, self.package)
        self.assertIn(self.email_user, self.package.subscriptions.all())
        self.assertFalse(subscription.active)

    def test_create_for_unexisting_email(self):
        previous_count = EmailUser.objects.count()
        subscription = Subscription.objects.create_for(
            package_name=self.package.name,
            email='non-existing@email.com')

        self.assertEqual(EmailUser.objects.count(), previous_count + 1)
        self.assertEqual(subscription.package, self.package)
        self.assertTrue(subscription.active)

    def test_create_for_twice(self):
        """
        Tests that the create_for method creates only one Subscription for a
        user, package pair.
        """
        prev_cnt_subs = Subscription.objects.count()
        self.create_subscription(self.package.name, self.email_user.email)
        self.create_subscription(self.package.name, self.email_user.email)

        self.assertEqual(Subscription.objects.count(), prev_cnt_subs + 1)

    def test_get_for_email(self):
        """
        Tests the get_for_email method when the user is subscribed to multiple
        packages.
        """
        self.create_subscription(self.package.name, self.email_user.email)
        p = Package.objects.create(name='temp')
        self.create_subscription(p.name, self.email_user.email)
        package_not_subscribed_to = Package.objects.create(name='qwer')
        self.create_subscription(package_not_subscribed_to.name,
                                 self.email_user.email,
                                 active=False)

        l = Subscription.objects.get_for_email(self.email_user.email)
        l = [sub.package for sub in l]

        self.assertIn(self.package, l)
        self.assertIn(p, l)
        self.assertNotIn(package_not_subscribed_to, l)

    def test_get_for_email_no_subsriptions(self):
        """
        Tests the get_for_email method when the user is not subscribed to any
        packages.
        """
        l = Subscription.objects.get_for_email(self.email_user.email)

        self.assertEqual(len(l), 0)

    def test_all_active(self):
        active_subs = [
            self.create_subscription(self.package.name, self.email_user.email),
            self.create_subscription(self.package.name, 'email@d.com')
        ]
        inactive_subs = [
            self.create_subscription(self.package.name, 'email2@d.com', False),
            self.create_subscription(self.package.name, 'email3@d.com', False),
        ]

        for active in active_subs:
            self.assertIn(active, Subscription.objects.all_active())
        for inactive in inactive_subs:
            self.assertNotIn(inactive, Subscription.objects.all_active())

    def test_all_active_filter_keyword(self):
        """
        Tests the all_active method when it should filter based on a keyword
        """
        active_subs = [
            self.create_subscription(self.package.name, self.email_user.email),
            self.create_subscription(self.package.name, 'email1@a.com')
        ]
        sub_no_kw = self.create_subscription(self.package.name, 'email2@a.com')
        for active in active_subs:
            active.keywords.add(Keyword.objects.get_or_create(name='cvs')[0])
        sub_no_kw.keywords.remove(Keyword.objects.get(name='cvs'))
        inactive_subs = [
            self.create_subscription(self.package.name, 'email2@d.com', False),
            self.create_subscription(self.package.name, 'email3@d.com', False),
        ]

        for active in active_subs:
            self.assertIn(active, Subscription.objects.all_active('cvs'))
        self.assertNotIn(sub_no_kw, Subscription.objects.all_active('cvs'))
        for inactive in inactive_subs:
            self.assertNotIn(inactive, Subscription.objects.all_active('cvs'))


class KeywordsTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.email_user = EmailUser.objects.create(email='email@domain.com')
        Keyword.objects.all().delete()
        self.email_user.default_keywords.add(
            Keyword.objects.get_or_create(name='cvs')[0])
        self.email_user.default_keywords.add(
            Keyword.objects.get_or_create(name='bts')[0])
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_user=self.email_user)
        self.new_keyword = Keyword.objects.create(name='new')

    def test_keywords_add_to_subscription(self):
        """
        Test adding a new keyword to the subscription.
        """
        self.subscription.keywords.add(self.new_keyword)

        self.assertIn(self.new_keyword, self.subscription.keywords.all())
        self.assertNotIn(
            self.new_keyword, self.email_user.default_keywords.all())
        for keyword in self.email_user.default_keywords.all():
            self.assertIn(keyword, self.subscription.keywords.all())

    def test_keywords_remove_from_subscription(self):
        """
        Tests removing a keyword from the subscription.
        """
        keyword = self.email_user.default_keywords.all()[0]
        self.subscription.keywords.remove(keyword)

        self.assertNotIn(keyword, self.subscription.keywords.all())
        self.assertIn(keyword, self.email_user.default_keywords.all())

    def test_get_keywords_when_default(self):
        """
        Tests that the subscription uses the user's default keywords if none
        have explicitly been set for the subscription.
        """
        self.assertEqual(len(self.email_user.default_keywords.all()),
                         len(self.subscription.keywords.all()))
        self.assertEqual(self.email_user.default_keywords.count(),
                         self.subscription.keywords.count())
        for kw1, kw2 in zip(self.email_user.default_keywords.all(),
                            self.subscription.keywords.all()):
            self.assertEqual(kw1, kw2)


class EmailUserTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.email_user = EmailUser.objects.create(email='email@domain.com')

    def test_is_subscribed_to(self):
        """
        Tests that the is_subscribed_to method returns True when the user is
        subscribed to a package.
        """
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.email_user.email)
        self.assertTrue(self.email_user.is_subscribed_to(self.package))
        self.assertTrue(self.email_user.is_subscribed_to(self.package.name))

    def test_is_subscribed_to_false(self):
        """
        Tests that the ``is_subscribed_to`` method returns False when the user
        is not subscribed to the package.
        """
        self.assertFalse(self.email_user.is_subscribed_to(self.package))
        self.assertFalse(self.email_user.is_subscribed_to(self.package.name))

    def test_is_subscribed_to_false_inactive(self):
        """
        Tests that the ``is_subscribed_to`` method returns False when the user
        has not confirmed the subscription (the subscription is inactive)
        """
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.email_user.email,
            active=False)
        self.assertFalse(self.email_user.is_subscribed_to(self.package))

    def test_new_user_has_default_keywords(self):
        """
        Tests that newly created users always have all the default keywords.
        """
        all_default_keywords = Keyword.objects.filter(default=True)
        self.assertEqual(self.email_user.default_keywords.count(),
                         all_default_keywords.count())
        for keyword in self.email_user.default_keywords.all():
            self.assertIn(keyword, all_default_keywords)

    def test_unsubscribe_all(self):
        """
        Tests the unsubscribe all method.
        """
        Subscription.objects.create(email_user=self.email_user,
                                    package=self.package)

        self.email_user.unsubscribe_all()

        self.assertEqual(self.email_user.subscription_set.count(), 0)


class EmailUserManagerTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.email_user = EmailUser.objects.create(email='email@domain.com')

    def test_is_subscribed_to(self):
        """
        Tests that the is_user_subscribed_to method returns True when the
        user is subscribed to the given package.
        """
        Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.email_user.email)
        self.assertTrue(
            EmailUser.objects.is_user_subscribed_to(self.email_user.email,
                                                    self.package.name))

    def test_is_subscribed_to_false(self):
        """
        Tests that the is_user_subscribed_to method returns False when the
        user is not subscribed to the given package.
        """
        self.assertFalse(
            EmailUser.objects.is_user_subscribed_to(self.email_user.email,
                                                    self.package.name))

    def test_is_subscribed_to_user_doesnt_exist(self):
        """
        Tests that the is_user_subscribed_to method returns False when the
        given user does not exist.
        """
        self.assertFalse(
            EmailUser.objects.is_user_subscribed_to('unknown-user@foo.com',
                                                    self.package.name))

    def test_is_subscribed_to_package_doesnt_exist(self):
        """
        Tests that the is_user_subscribed_to method returns False when the
        given package does not exist.
        """
        self.assertFalse(
            EmailUser.objects.is_user_subscribed_to(self.email_user.email,
                                                    'unknown-package'))


class PackageManagerTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')

    def test_package_exists(self):
        self.assertTrue(Package.objects.exists_with_name(self.package.name))

    def test_package_exists_false(self):
        self.assertFalse(Package.objects.exists_with_name('unexisting'))


class BinaryPackageManagerTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package',
            source_package=self.package)

    def test_package_exists(self):
        self.assertTrue(
            BinaryPackage.objects.exists_with_name(self.binary_package.name))

    def test_package_exists_false(self):
        self.assertFalse(
            BinaryPackage.objects.exists_with_name('unexisting'))


class VerpModuleTest(SimpleTestCase):
    """
    Tests for the ``pts.core.utils.verp`` module.
    """
    def test_encode(self):
        """
        Tests for the encode method.
        """
        self.assertEqual(
            verp.encode('itny-out@domain.com', 'node42!ann@old.example.com'),
            'itny-out-node42+21ann=old.example.com@domain.com')

        self.assertEqual(
            verp.encode('itny-out@domain.com', 'tom@old.example.com'),
            'itny-out-tom=old.example.com@domain.com')

        self.assertEqual(
            verp.encode('itny-out@domain.com', 'dave+priority@new.example.com'),
            'itny-out-dave+2Bpriority=new.example.com@domain.com')

        self.assertEqual(
            verp.encode('bounce@dom.com', 'user+!%-:@[]+@other.com'),
            'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com')

    def test_decode(self):
        """
        Tests the decode method.
        """
        self.assertEqual(
            verp.decode('itny-out-dave+2Bpriority=new.example.com@domain.com'),
            ('itny-out@domain.com', 'dave+priority@new.example.com'))

        self.assertEqual(
            verp.decode('itny-out-node42+21ann=old.example.com@domain.com'),
            ('itny-out@domain.com', 'node42!ann@old.example.com'))

        self.assertEqual(
            verp.decode('bounce-addr+2B40=dom.com@asdf.com'),
            ('bounce@asdf.com', 'addr+40@dom.com'))

        self.assertEqual(
            verp.decode('bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com'),
            ('bounce@dom.com', 'user+!%-:@[]+@other.com'))

    def test_invariant_encode_decode(self):
        """
        Tests that decoding an encoded address returns the original pair.
        """
        from_email, to_email = 'bounce@domain.com', 'user@other.com'
        self.assertEqual(
            verp.decode(verp.encode(from_email, to_email)),
            (from_email, to_email))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
class CustomMessageFromBytesTest(TestCase):
    """
    Tests the ``pts.core.utils.message_from_bytes`` function.
    """
    def setUp(self):
        self.message_bytes = b"""MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Disposition: inline
Content-Transfer-Encoding: 8bit

"""
        self.body = "üßščć한글ᥡ╥ສए"
        self.message_bytes = self.message_bytes + self.body.encode('utf-8')

    def get_mock_connection(self):
        """
        Helper method returning a mock SMTP connection object.
        """
        if six.PY3:
            from unittest.mock import create_autospec
        else:
            from mock import create_autospec
        import smtplib
        return create_autospec(smtplib.SMTP('localhost'), return_value={})

    def test_as_string_returns_bytes(self):
        """
        Tests that the as_string message returns bytes.
        """
        message = message_from_bytes(self.message_bytes)

        self.assertEqual(self.message_bytes, message.as_string())
        self.assertTrue(isinstance(message.as_string(), six.binary_type))

    def test_get_payload_decode_idempotent(self):
        """
        Tests that the get_payload method returns bytes which can be decoded
        using the message's encoding and that they are identical to the
        ones given to the function in the first place.
        """
        message = message_from_bytes(self.message_bytes)

        self.assertEqual(self.body,
                         message.get_payload(decode=True).decode('utf-8'))

    def test_integrate_with_django(self):
        """
        Tests that the message obtained by the message_from_bytes function can
        be sent out using the Django email API.

        In the same time, this test makes sure that Django keeps using
        the as_string method as expected.
        """
        from django.core.mail import get_connection
        backend = get_connection()
        backend.open()
        # Replace the backend's SMTP connection with a mock.
        mock_connection = self.get_mock_connection()
        backend.connection.quit()
        backend.connection = mock_connection
        # Send the message over the backend
        message = message_from_bytes(self.message_bytes)
        custom_message = CustomEmailMessage(
            msg=message,
            from_email='from@domain.com',
            to=['to@domain.com'])

        backend.send_messages([custom_message])
        backend.close()

        # The backend sent the mail over SMTP & it is not corrupted
        mock_connection.sendmail.assert_called_with(
            'from@domain.com',
            ['to@domain.com'],
            message.as_string())
