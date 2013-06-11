"""
Tests for the PTS core module.
"""
from __future__ import unicode_literals
from django.test import TestCase
from core.models import Subscription, EmailUser, Package


class SubscriptionTest(TestCase):
    def setUp(self):
        self.package = Package.objects.create(name='dummy-package')
        self.email_user = EmailUser.objects.create(email='email@domain.com')

    def test_create_for_existing_email(self):
        subscription = Subscription.objects.create_for(
            package_name=self.package.name,
            email=self.email_user.email)

        self.assertEqual(subscription.email_user, self.email_user)
        self.assertEqual(subscription.package, self.package)
        self.assertIn(self.email_user, self.package.subscriptions.all())

    def test_create_for_unexisting_email(self):
        previous_count = EmailUser.objects.count()
        subscription = Subscription.objects.create_for(
            package_name=self.package.name,
            email='non-existing@email.com')

        self.assertEqual(EmailUser.objects.count(), previous_count + 1)
        self.assertEqual(subscription.package, self.package)


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
