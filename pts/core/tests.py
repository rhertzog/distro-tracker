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
from pts.core.models import SourcePackage
from pts.core.models import Keyword
from pts.core.models import PseudoPackage
from pts.core.models import Repository
from pts.core.utils import verp
from pts.core.utils import message_from_bytes
from pts.dispatch.custom_email_message import CustomEmailMessage
from pts.core.retrieve_data import retrieve_repository_info
import json

import sys
from django.utils.six.moves import mock


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

    def test_source_package_create(self):
        """
        Tests that the sources manager creates source packages.
        """
        p = Package.source_packages.create(name='source-package')

        self.assertEqual(p.package_type, Package.SOURCE_PACKAGE_TYPE)

    def test_pseudo_package_create(self):
        """
        Tests that the pseudo packages manager creates pseudo pacakges.
        """
        p = Package.pseudo_packages.create(name='pseudo-package')

        self.assertEqual(p.package_type, Package.PSEUDO_PACKAGE_TYPE)

    def test_subscription_only_package_create(self):
        """
        Tests that the subscription only packages manager creates
        subscription only packages.
        """
        p = Package.subscription_only_packages.create(name='package')

        self.assertEqual(p.package_type, Package.SUBSCRIPTION_ONLY_PACKAGE_TYPE)

    def test_manager_types_correct_objects(self):
        """
        Tests that the different manager types always return only their
        associated package type.
        """
        # Make sure there are no packages in the beginning
        Package.objects.all().delete()
        self.assertEqual(Package.objects.count(), 0)

        src_pkg = Package.source_packages.create(name='source-package')
        pseudo_pkg = Package.pseudo_packages.create(name='pseudo-package')
        sub_only_pkg = Package.subscription_only_packages.create(name='package')

        # objects manager returns all packages
        self.assertEqual(Package.objects.count(), 3)
        # specific pacakge type managers:
        self.assertEqual(Package.source_packages.count(), 1)
        self.assertIn(src_pkg, Package.source_packages.all())
        self.assertEqual(Package.pseudo_packages.count(), 1)
        self.assertIn(pseudo_pkg, Package.pseudo_packages.all())
        self.assertEqual(Package.subscription_only_packages.count(), 1)
        self.assertIn(sub_only_pkg, Package.subscription_only_packages.all())

    def test_all_with_subscriptions(self):
        """
        Tests the manager method which should return a QuerySet with all
        packages that have at least one subscriber.
        """
        pseudo_package = PseudoPackage.objects.create(name='pseudo-package')
        sub_only_pkg = Package.subscription_only_packages.create(
            name='sub-only-pkg')
        Package.subscription_only_packages.create(name='sub-only-pkg-1')

        # When there are no subscriptions, it shouldn't return any results
        self.assertEqual(Package.objects.all_with_subscribers().count(), 0)
        self.assertEqual(
            Package.pseudo_packages.all_with_subscribers().count(),
            0)
        self.assertEqual(
            Package.source_packages.all_with_subscribers().count(),
            0)
        self.assertEqual(
            Package.subscription_only_packages.all_with_subscribers().count(),
            0)

        # When subscriptions are added, only the packages with subscriptions
        # are returned
        Subscription.objects.create_for(package_name=self.package.name,
                                        email='user@domain.com')
        Subscription.objects.create_for(package_name=sub_only_pkg.name,
                                        email='other-user@domain.com')
        Subscription.objects.create_for(package_name=pseudo_package.name,
                                        email='some-user@domain.com')

        self.assertEqual(Package.objects.all_with_subscribers().count(), 3)
        all_with_subscribers = [
            pkg.name
            for pkg in Package.objects.all_with_subscribers()
        ]
        self.assertIn(self.package.name, all_with_subscribers)
        self.assertIn(pseudo_package.name, all_with_subscribers)
        self.assertIn(sub_only_pkg.name, all_with_subscribers)
        # Specific managers...
        self.assertEqual(
            Package.pseudo_packages.all_with_subscribers().count(),
            1)
        self.assertEqual(
            Package.source_packages.all_with_subscribers().count(),
            1)
        self.assertEqual(
            Package.subscription_only_packages.all_with_subscribers().count(),
            1)


class BinaryPackageManagerTest(TestCase):
    def setUp(self):
        self.package = SourcePackage.objects.create(name='dummy-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package',
            source_package=self.package)

    def test_package_exists(self):
        self.assertTrue(
            BinaryPackage.objects.exists_with_name(self.binary_package.name))

    def test_package_exists_false(self):
        self.assertFalse(
            BinaryPackage.objects.exists_with_name('unexisting'))

    def test_binary_and_source_same_name(self):
        """
        Tests that it is possible to create a binary and source package with
        the same name.
        """
        bin_pkg = BinaryPackage.objects.create(name='package')
        src_pkg = SourcePackage.objects.create(name='package')
        self.assertIn(bin_pkg, BinaryPackage.objects.all())
        self.assertIn(src_pkg, SourcePackage.objects.all())


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
        import smtplib
        return mock.create_autospec(smtplib.SMTP('localhost'), return_value={})

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
        # Replace the backend's SMTP connection with a mock.
        mock_connection = self.get_mock_connection()
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


from pts.core.utils.email_messages import (
    name_and_address_from_string,
    names_and_addresses_from_string)

class EmailUtilsTest(SimpleTestCase):
    def test_name_and_address_from_string(self):
        """
        Tests retrieving a name and address from a string which contains
        unquoted commas.
        """
        self.assertDictEqual(
            name_and_address_from_string(
                'John H. Robinson, IV <jaqque@debian.org>'),
            {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'}
        )

        self.assertDictEqual(
            name_and_address_from_string('email@domain.com'),
            {'name': '', 'email': 'email@domain.com'}
        )

        self.assertDictEqual(
            name_and_address_from_string('Name <email@domain.com>'),
            {'name': 'Name', 'email': 'email@domain.com'}
        )

        self.assertIsNone(name_and_address_from_string(''))

    def test_names_and_addresses_from_string(self):
        """
        Tests extracting names and emails from a string containing a list of
        them.
        """
        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'Name <email@domain.com>'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': 'Name', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'email@domain.com'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': '', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(names_and_addresses_from_string(''), [])


@override_settings(PTS_VENDOR_RULES='pts.core.tests')
class RetrievePseudoPackagesTest(TestCase):
    """
    Tests the update_pseudo_package_list data retrieval function.
    """
    def setUp(self):
        # Since the tests module is used to provide the vendor rules,
        # we dynamically add the needed function
        self.packages = ['package1', 'package2']
        self.mock_get_pseudo_package_list = mock.create_autospec(
            lambda: None, return_value=self.packages)
        sys.modules[__name__].get_pseudo_package_list = (
            self.mock_get_pseudo_package_list
        )

    def tearDown(self):
        # The added function is removed after the tests
        delattr(sys.modules[__name__], 'get_pseudo_package_list')

    def update_pseudo_package_list(self):
        """
        Helper method runs the get_pseudo_package_list function.
        """
        # Update the return value
        self.mock_get_pseudo_package_list.return_value = self.packages
        from pts.core.retrieve_data import update_pseudo_package_list
        update_pseudo_package_list()

    def populate_packages(self, packages):
        """
        Helper method adds the given packages to the database.
        """
        for package in packages:
            PseudoPackage.objects.create(name=package)

    def test_all_pseudo_packages_added(self):
        """
        Tests that all pseudo packages provided by the vendor are added to the
        database.
        """
        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_pseudo_package_exists(self):
        """
        Tests that when a pseudo package returned in the result already exists
        it is not added again and processing does not fail.
        """
        self.populate_packages(self.packages)

        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_pseudo_package_update(self):
        """
        Tests that when the vendor provided package list is updated, the
        database is correctly updated too.
        """
        self.populate_packages(self.packages)
        self.packages.append('package3')

        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_pseudo_package_update_remove(self):
        """
        Tests that when the vendor provided package list is updated to remove a
        package, the database is correctly updated.
        """
        self.populate_packages(self.packages)
        old_packages = self.packages
        self.packages = ['new-package']

        self.update_pseudo_package_list()

        # The list of pseudo packages is updated to contain only the new
        # package
        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )
        # Old pseudo packages are now demoted to subscription-only packages
        self.assertSequenceEqual(
            sorted(old_packages),
            sorted([
                pkg.name
                for pkg in Package.subscription_only_packages.all()
            ])
        )

    def test_no_changes_when_resource_unavailable(self):
        """
        Tests that no updates are made when the vendor-provided message does
        not provide a new list of pseudo packages due to an error in accessing
        the necessary resource.
        """
        self.populate_packages(self.packages)
        # Set up an exception in the vendor-provided function
        from pts.vendor.common import PluginProcessingError
        self.mock_get_pseudo_package_list.side_effect = PluginProcessingError()
        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_subscriptions_remain_after_update(self):
        """
        Tests that any user subscriptions to pseudo packages are retained after
        the update operation is ran.
        """
        self.populate_packages(self.packages)
        user_email = 'user@domain.com'
        Subscription.objects.create_for(package_name=self.packages[0],
                                        email=user_email)
        Subscription.objects.create_for(package_name=self.packages[1],
                                        email=user_email)
        # After the update, the first package is no longer to be considered a
        # pseudo package.
        removed_package = self.packages.pop(0)

        self.update_pseudo_package_list()

        user = EmailUser.objects.get(email=user_email)
        # Still subscribed to the demoted package
        self.assertTrue(user.is_subscribed_to(removed_package))
        # Still subscribed to the pseudo package
        self.assertTrue(user.is_subscribed_to(self.packages[0]))

    def test_all_pseudo_packages_demoted(self):
        """
        Tests that when the vendor-provided function returns an empty list, all
        pseudo packages are correctly demoted down to subscription-only
        packages.
        """
        self.populate_packages(self.packages)
        old_packages = self.packages
        self.packages = []
        # Sanity check: there were no subscription-only packages originaly
        self.assertEqual(Package.subscription_only_packages.count(),
                         0)

        self.update_pseudo_package_list()

        self.assertEqual(PseudoPackage.objects.count(), 0)
        self.assertEqual(Package.subscription_only_packages.count(),
                         len(old_packages))

    @mock.patch('pts.core.retrieve_data.update_pseudo_package_list')
    def test_management_command_called(self, mock_update_pseudo_package_list):
        """
        Tests that the management command for updating pseudo packages calls
        the correct function.
        """
        from django.core.management import call_command
        call_command('pts_update_pseudo_packages')

        mock_update_pseudo_package_list.assert_called_with()


from django.core.urlresolvers import reverse


class PackageViewTest(TestCase):
    """
    Tests for the package view.
    """
    def setUp(self):
        self.package = SourcePackage.objects.create(name='dummy-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package', source_package=self.package)
        self.pseudo_package = PseudoPackage.objects.create(name='pseudo-pkg')

    def get_package_url(self, package_name):
        """
        Helper method which returns the URL for the package with the given name
        """
        return reverse('pts-package-page', kwargs={
            'package_name': package_name
        })

    def test_source_package_page(self):
        """
        Tests that when visiting the package page for an existing package, a
        response based on the correct template is returned.
        """
        url = self.get_package_url(self.package.name)
        response = self.client.get(url)

        self.assertTemplateUsed(response, 'core/package.html')

    def test_binary_package_redirects_to_source(self):
        """
        Tests that when visited a binary package URL, the user is redirected
        to the corresponding source package page.
        """
        url = self.get_package_url(self.binary_package.name)
        response = self.client.get(url)

        self.assertRedirects(response, self.get_package_url(self.package.name))

    def test_pseudo_package_page(self):
        """
        Tests that when visiting a page for a pseudo package the correct
        template is used.
        """
        url = self.get_package_url(self.pseudo_package.name)
        response = self.client.get(url)

        self.assertTemplateUsed(response, 'core/package.html')

    def test_non_existent_package(self):
        """
        Tests that a 404 is returned when the given package does not exist.
        """
        url = self.get_package_url('no-exist')
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_subscriptions_only_package(self):
        """
        Tests that a 404 is returned when the given package is a "subscriptions
        only" package.
        """
        package_name = 'sub-only-pkg'
        # Make sure the package actually exists.
        Package.subscription_only_packages.create(name=package_name)

        url = self.get_package_url(package_name)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_legacy_url_redirects(self):
        """
        Tests that the old PTS style package URLs are correctly redirected.
        """
        url_template = '/{hash}/{package}.html'

        # Redirects for packages that do not start with "lib"
        url = url_template.format(hash=self.package.name[0],
                                  package=self.package.name)
        response = self.client.get(url)
        self.assertRedirects(response, self.get_package_url(self.package.name),
                             status_code=301)

        # No redirect when the hash does not match the package
        url = url_template.format(hash='q', package=self.package.name)
        self.assertEqual(self.client.get(url).status_code, 404)

        # Redirect when the package name starts with "lib"
        lib_package = 'libpackage'
        SourcePackage.objects.create(name=lib_package)
        url = url_template.format(hash='libp', package=lib_package)
        self.assertRedirects(self.client.get(url),
                             self.get_package_url(lib_package),
                             status_code=301)


class PackageSearchViewTest(TestCase):
    def setUp(self):
        self.pseudo_package = PseudoPackage.objects.create(name='pseudo-package')
        self.source_package = SourcePackage.objects.create(name='dummy-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package',
            source_package=self.source_package)

    def test_package_search_source_package(self):
        """
        Tests the package search when the given package is an existing source
        package.
        """
        response = self.client.get(reverse('pts-package-search'), {
            'package_name': self.source_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_search_pseudo_package(self):
        """
        Tests the package search when the given package is an existing pseudo
        package.
        """
        response = self.client.get(reverse('pts-package-search'), {
            'package_name': self.pseudo_package.name
        })

        self.assertRedirects(response, self.pseudo_package.get_absolute_url())

    def test_package_search_binary_package(self):
        """
        Tests the package search when the given package is an existing binary
        package.
        """
        response = self.client.get(reverse('pts-package-search'), {
            'package_name': self.binary_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_does_not_exist(self):
        """
        Tests the package search when the given package does not exist.
        """
        response = self.client.get(reverse('pts-package-search'), {
            'package_name': 'no-exist'
        })

        self.assertTemplateUsed('core/package_search.html')
        self.assertIn('package_name', response.context)
        self.assertEqual(response.context['package_name'], 'no-exist')


class IndexViewTest(TestCase):
    def test_index(self):
        """
        Tests that the correct template is rendered when the index page is
        accessed.
        """
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'core/index.html')


class PackageAutocompleteViewTest(TestCase):
    def setUp(self):
        SourcePackage.objects.create(name='dummy-package')
        SourcePackage.objects.create(name='d-package')
        SourcePackage.objects.create(name='package')
        PseudoPackage.objects.create(name='pseudo-package')
        PseudoPackage.objects.create(name='zzz')
        Package.subscription_only_packages.create(name='ppp')

    def test_source_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for source
        packages.
        """
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'package_type': 'source',
            'q': 'd',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertIn('dummy-package', response)
        self.assertIn('d-package', response)

        # No packages given when there are no matching source packages
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'package_type': 'source',
            'q': 'z',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 0)

    def test_pseudo_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for pseudo
        packages.
        """
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'package_type': 'pseudo',
            'q': 'p',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 1)
        self.assertIn('pseudo-package', response)

        # No packages given when there are no matching pseudo packages
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'package_type': 'source',
            'q': '-',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 0)

    def test_all_packages_autocomplete(self):
        """
        Tests the autocomplete functionality when the client does not specify
        the type of package.
        """
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'q': 'p',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertIn('package', response)
        self.assertIn('pseudo-package', response)

        # No packages given when there are no matching packages
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'q': '-',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 0)

    def test_no_query_given(self):
        """
        Tests the autocomplete when there is no query parameter given.
        """
        response = self.client.get(reverse('pts-api-package-autocomplete'), {
            'package_type': 'source',
        })

        self.assertEqual(response.status_code, 404)


class RepositoryTests(TestCase):
    def set_mock_response(self, mock_requests, text="", status_code=200):
        """
        Helper method which sets a mock response to the given mock_requests
        module.
        """
        mock_response = mock_requests.models.Response()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_requests.get.return_value = mock_response

    @mock.patch('pts.core.admin.requests')
    def test_sources_list_entry_validation(self, mock_requests):
        from pts.core.admin import validate_sources_list_entry
        from django.core.exceptions import ValidationError
        # Not enough parts in the entry is an exception
        with self.assertRaises(ValidationError):
            validate_sources_list_entry('texthere')
        # Enough parts, but it does not start with deb|deb-src
        with self.assertRaises(ValidationError):
            validate_sources_list_entry('part1 part2 part3 part4')
        # Starts with deb, but no URL given.
        with self.assertRaises(ValidationError):
            validate_sources_list_entry('deb thisisnotaurl part3 part4')
        ## Make sure requests returns 404
        self.set_mock_response(mock_requests, status_code=404)
        # There is no Release file at the given URL
        with self.assertRaises(ValidationError):
            validate_sources_list_entry('deb http://does-not-matter.com/ part3 part4')

    @mock.patch('pts.core.retrieve_data.requests')
    def test_retrieve_repository_info_correct(self, mock_requests):
        """
        Tests that the function returns correct data when it is all found in
        the Release file.
        """
        architectures = (
            'amd64 armel armhf i386 ia64 kfreebsd-amd64 '
            'kfreebsd-i386 mips mipsel powerpc s390 s390x sparc'.split()
        )
        components = ['main', 'contrib', 'non-free']
        mock_response_text = (
            'Suite: stable\n'
            'Codename: wheezy\n'
            'Architectures: ' + ' '.join(architectures) + '\n'
            'Components: ' + ' '.join(components) + '\n'
            'Version: 7.1\n'
            'Description: Debian 7.1 Released 15 June 2013\n'
        )
        self.set_mock_response(mock_requests, mock_response_text)

        repository_info = retrieve_repository_info(
            'deb http://repository.com/ stable')

        expected_info = {
            'uri': 'http://repository.com/',
            'architectures': architectures,
            'components': components,
            'binary': True,
            'source': False,
            'codename': 'wheezy',
            'suite': 'stable',
        }

        self.assertDictEqual(expected_info, repository_info)

    @mock.patch('pts.core.retrieve_data.requests')
    def test_retrieve_repository_info_missing_required(self, mock_requests):
        """
        Tests that the function raises an exception when some required keys are
        missing from the Release file.
        """
        mock_response_text = (
            'Suite: stable\n'
            'Codename: wheezy\n'
            'Architectures: amd64\n'
            'Version: 7.1\n'
            'Description: Debian 7.1 Released 15 June 2013\n'
        )
        self.set_mock_response(mock_requests, mock_response_text)

        from pts.core.retrieve_data import InvalidRepositoryException
        with self.assertRaises(InvalidRepositoryException):
            retrieve_repository_info('deb http://repository.com/ stable')

    @mock.patch('pts.core.retrieve_data.requests')
    def test_retrieve_repository_info_missing_non_required(self, mock_requests):
        """
        Tests the function when some non-required keys are missing from the
        Release file.
        """
        mock_response_text = (
            'Architectures: amd64\n'
            'components: main'
            'Version: 7.1\n'
            'Description: Debian 7.1 Released 15 June 2013\n'
        )
        self.set_mock_response(mock_requests, mock_response_text)

        repository_info = retrieve_repository_info(
            'deb http://repository.com/ stable')
        # It uses the suite name from the sources.list
        self.assertEqual(repository_info['suite'], 'stable')
        # Codename is not found
        self.assertIsNone(repository_info['codename'])


from pts.core.utils.datastructures import DAG, InvalidDAGException
class DAGTests(SimpleTestCase):
    """
    Tests for the `DAG` class.
    """
    def test_add_nodes(self):
        """
        Tests adding nodes to a DAG.
        """
        g = DAG()

        # A single node
        g.add_node(1)
        self.assertEqual(len(g.all_nodes), 1)
        self.assertEqual(g.all_nodes[0], 1)
        # Another one
        g.add_node(2)
        self.assertEqual(len(g.all_nodes), 2)
        self.assertIn(2, g.all_nodes)
        # When adding a same node again, nothing changes.
        g.add_node(1)
        self.assertEqual(len(g.all_nodes), 2)

    def test_add_edge(self):
        """
        Tests adding edges to a DAG.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)

        g.add_edge(1, 2)
        self.assertEqual(len(g.dependent_nodes(1)), 1)
        self.assertIn(2, g.dependent_nodes(1))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[1].id], 0)
        self.assertEqual(g.in_degree[g.nodes_map[2].id], 1)

        g.add_node(3)
        g.add_edge(1, 3)
        self.assertEqual(len(g.dependent_nodes(1)), 2)
        self.assertIn(3, g.dependent_nodes(1))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[1].id], 0)
        self.assertEqual(g.in_degree[g.nodes_map[3].id], 1)

        g.add_edge(2, 3)
        self.assertEqual(len(g.dependent_nodes(2)), 1)
        self.assertIn(3, g.dependent_nodes(2))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[3].id], 2)

        # Add a same edge again - nothing changed?
        g.add_edge(1, 3)
        self.assertEqual(len(g.dependent_nodes(1)), 2)

        # Add an edge resulting in a cycle
        with self.assertRaises(InvalidDAGException):
            g.add_edge(3, 1)

    def test_remove_node(self):
        """
        Tests removing a node from the graph.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(1, 3)
        g.add_edge(2, 3)

        g.remove_node(3)
        self.assertNotIn(3, g.all_nodes)
        self.assertEqual(len(g.dependent_nodes(1)), 1)
        self.assertIn(2, g.dependent_nodes(1))
        self.assertEqual(len(g.dependent_nodes(2)), 0)

        g.remove_node(1)
        self.assertEqual(g.in_degree[g.nodes_map[2].id], 0)

    def test_find_no_dependency_node(self):
        """
        Tests that the DAG correctly returns nodes with no dependencies.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        self.assertEqual(g._get_node_with_no_dependencies().original, 1)

        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(3, 2)
        g.add_edge(2, 1)
        self.assertEqual(g._get_node_with_no_dependencies().original, 3)

        g = DAG()
        g.add_node(1)
        self.assertEqual(g._get_node_with_no_dependencies().original, 1)

    def test_topsort_simple(self):
        """
        Tests the topological sort of the DAG class.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        topsort = list(g.topsort_nodes())

        self.assertSequenceEqual([1, 2, 3], topsort)

    def test_topsort_no_dependencies(self):
        """
        Tests the toplogical sort of the DAG class when the given DAG has no
        dependencies between the nodes.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)

        topsort = list(g.topsort_nodes())

        nodes = [1, 2, 3]
        # The order in this case cannot be mandated, only that all the nodes
        # are in the output
        for node in nodes:
            self.assertIn(node, topsort)

    def test_topsort_complex(self):
        """
        Tests the toplogical sort when a more complex graph is given.
        """
        g = DAG()
        nodes = list(range(13))
        for node in nodes:
            g.add_node(node)
        edges = (
            (0, 1),
            (0, 2),
            (0, 3),
            (0, 5),
            (0, 6),
            (2, 3),
            (3, 4),
            (3, 5),
            (4, 9),
            (6, 4),
            (6, 9),
            (7, 6),
            (8, 7),
            (9, 10),
            (9, 11),
            (9, 12),
            (11, 12),
        )
        for edge in edges:
            g.add_edge(*edge)

        topsort = list(g.topsort_nodes())
        # Make sure all nodes are found in the toplogical sort
        for node in nodes:
            self.assertIn(node, topsort)
        # Make sure that all dependent nodes are found after the nodes they
        # depend on.
        # Invariant: for each edge (n1, n2) position(n2) in the topological
        # sort must be strictly greater than the position(n1).
        for node1, node2 in edges:
            self.assertTrue(topsort.index(node2) > topsort.index(node1))

    def test_topsort_string_nodes(self):
        """
        Tests the toplogical sort when strings are used for node objects.
        """
        g = DAG()
        nodes = ['shirt', 'pants', 'tie', 'belt', 'shoes', 'socks', 'pants']
        for node in nodes:
            g.add_node(node)
        edges = (
            ('shirt', 'tie'),
            ('shirt', 'belt'),
            ('belt', 'tie'),
            ('pants', 'tie'),
            ('pants', 'belt'),
            ('pants', 'shoes'),
            ('pants', 'shirt'),
            ('socks', 'shoes'),
            ('socks', 'pants'),
        )
        for edge in edges:
            g.add_edge(*edge)

        topsort = list(g.topsort_nodes())
        for node in nodes:
            self.assertIn(node, topsort)
        for node1, node2 in edges:
            self.assertTrue(topsort.index(node2) > topsort.index(node1))

    def test_nodes_reachable_from(self):
        """
        Tests finding all nodes reachable from a single node.
        """
        # Simple situation first.
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        self.assertEqual(len(g.nodes_reachable_from(1)), 2)
        self.assertIn(2, g.nodes_reachable_from(1))
        self.assertIn(3, g.nodes_reachable_from(1))
        self.assertEqual(len(g.nodes_reachable_from(2)), 1)
        self.assertIn(3, g.nodes_reachable_from(1))

        # No nodes reachable from the given node
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(2, 3)

        self.assertEqual(len(g.nodes_reachable_from(1)), 0)

        # More complex graph
        g = DAG()

        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_node(4)
        g.add_node(5)
        g.add_edge(1, 3)
        g.add_edge(2, 4)
        g.add_edge(2, 5)
        g.add_edge(4, 5)
        g.add_edge(5, 3)

        self.assertEqual(len(g.nodes_reachable_from(2)), 3)
        for node in range(3, 6):
            self.assertIn(node, g.nodes_reachable_from(2))
        self.assertEqual(len(g.nodes_reachable_from(1)), 1)
        self.assertIn(3, g.nodes_reachable_from(1))


from pts.core.tasks import BaseTask

from pts.core.tasks import run_task, build_task_event_dependency_graph, build_full_task_dag
class JobTests(SimpleTestCase):
    def create_task_class(self, produces, depends_on, raises):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        exec_list = self.execution_list
        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on
            def execute(self):
                for event in raises:
                    self.raise_event(event)
                exec_list.append(self.__class__)
        return TestTask

    def assert_contains_all(self, items, container):
        """
        Asserts that all of the given items are found in the given container.
        """
        for item in items:
            self.assertIn(item, container)

    def setUp(self):
        #: Tasks which execute add themselves to this list.
        self.execution_list = []
        self.original_plugins = [
            plugin
            for plugin in BaseTask.plugins
        ]
        # Now ignore all original plugins.
        BaseTask.plugins = []

    def assert_executed_tasks_equal(self, expected_tasks):
        """
        Helper method which checks whether the given list of expected tasks
        matches the actual list of executed tasks.
        """
        self.assertEqual(len(expected_tasks), len(self.execution_list))
        self.assert_contains_all(expected_tasks, self.execution_list)

    def assert_task_dependency_preserved(self, task, dependent_tasks):
        """
        Helper method which cheks whether the given dependent tasks were
        executed after their dependency was satisifed.
        """
        task_index = self.execution_list.index(task)
        for task in dependent_tasks:
            self.assertTrue(self.execution_list.index(task) > task_index)

    def tearDown(self):
        # Remove any extra plugins which may have been created during a test run
        BaseTask.plugins = self.original_plugins

    def test_simple_dependency(self):
        """
        Tests creating a DAG of task dependencies when there is only one event
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        # Is the event dependency built correctly
        events = build_task_event_dependency_graph()
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events['a'][0]), 1)
        self.assertIn(A, events['a'][0])
        self.assertEqual(len(events['a'][1]), 1)
        self.assertIn(B, events['a'][1])

        # Is the DAG built correctly
        g = build_full_task_dag()
        self.assertEqual(len(g.all_nodes), 2)
        self.assertIn(A, g.all_nodes)
        self.assertIn(B, g.all_nodes)
        # B depends on A
        self.assertIn(B, g.dependent_nodes(A))

    def test_multiple_dependency(self):
        """
        Tests creating a DAG of tasks dependencies when there are multiple
        events.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('A',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        g = build_full_task_dag()
        self.assertEqual(len(g.dependent_nodes(T0)), 5)
        self.assert_contains_all([T1, T2, T3, T4, T7], g.dependent_nodes(T0))

        self.assertEqual(len(g.dependent_nodes(T1)), 2)
        self.assert_contains_all([T5, T7], g.dependent_nodes(T1))

        self.assertEqual(len(g.dependent_nodes(T2)), 1)
        self.assert_contains_all([T6], g.dependent_nodes(T2))

        self.assertEqual(len(g.dependent_nodes(T3)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T3))

        self.assertEqual(len(g.dependent_nodes(T4)), 0)

        self.assertEqual(len(g.dependent_nodes(T5)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T5))

        self.assertEqual(len(g.dependent_nodes(T6)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T6))

        self.assertEqual(len(g.dependent_nodes(T7)), 0)

        self.assertEqual(len(g.dependent_nodes(T8)), 0)

    def test_run_job_simple(self):
        """
        Tests running a job consisting of a simple dependency.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A, B])
        self.assert_task_dependency_preserved(A, [B])

    def test_run_job_no_dependency(self):
        """
        Tests running a job consisting of no dependencies.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class(('b',), (), ('b',))

        run_task(B)

        self.assert_executed_tasks_equal([B])

    def test_run_job_no_events_emitted(self):
        """
        Tests running a job consisting of a simple dependency, but the event is
        not emitted during execution.
        """
        A = self.create_task_class(('a',), (), ())
        B = self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A])

    def test_run_job_complex_1(self):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('A',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        # Make sure the tasks which didn't have the appropriate events raised
        # during execution were not executed. These are tasks T3 and T4 in this
        # instance.
        self.assert_executed_tasks_equal([T0, T1, T2, T5, T6, T7, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T1, T2, T7])
        ## Even though task T1 does not emit the event D1, it still needs to
        ## execute before task T7.
        self.assert_task_dependency_preserved(T1, [T5, T7])
        self.assert_task_dependency_preserved(T2, [T6])
        self.assert_task_dependency_preserved(T5, [T8])
        self.assert_task_dependency_preserved(T6, [T8])

    def test_run_job_complex_2(self):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        # In this test case, unlike test_run_job_complex_1, T0 emits event B so
        # no tasks depending on event A need to run.
        self.assert_executed_tasks_equal([T0, T3, T4, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T3, T4])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_3(self):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B', 'B1'), (), ('B', 'B1'))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A', 'B1'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        self.assert_executed_tasks_equal([T0, T3, T4, T7, T8])
        self.assert_task_dependency_preserved(T0, [T3, T4, T7])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_4(self):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8])

    def test_run_job_complex_5(self):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D', 'D1'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8, T7])

        self.assert_task_dependency_preserved(T1, [T7, T5])
        self.assert_task_dependency_preserved(T5, [T8])


from pts.core.utils import PrettyPrintList
class PrettyPrintListTest(SimpleTestCase):
    """
    Tests for the PrettyPrintList class.
    """
    def test_string_output(self):
        """
        Tests the output of a PrettyPrintList.
        """
        l = PrettyPrintList(['a', 'b', 'abe', 'q'])
        self.assertEqual(str(l), 'a b abe q')

        l = PrettyPrintList()
        self.assertEqual(str(l), '')

        l = PrettyPrintList([0, 'a', 1])
        self.assertEqual(str(l), '0 a 1')

    def test_list_methods_accessible(self):
        """
        Tests that list methods are accessible to the PrettyPrintList object.
        """
        l = PrettyPrintList()
        l.append('a')
        self.assertEqual(str(l), 'a')

        l.extend(['q', 'w'])
        self.assertEqual(str(l), 'a q w')

        l.pop()
        self.assertEqual(str(l), 'a q')

        # len works?
        self.assertEqual(len(l), 2)
        # Iterable?
        self.assertSequenceEqual(l, ['a', 'q'])
        # Indexable?
        self.assertEqual(l[0], 'a')
        # Comparable?
        l2 = PrettyPrintList(['a', 'q'])
        self.assertTrue(l == l2)
        l3 = PrettyPrintList()
        self.assertFalse(l == l3)
        # Comparable to plain lists?
        self.assertTrue(l == ['a', 'q'])
        self.assertFalse(l == ['a'])


from pts.core.utils import SpaceDelimitedTextField
class SpaceDelimitedTextFieldTest(SimpleTestCase):
    """
    Tests the SpaceDelimitedTextField class.
    """
    def setUp(self):
        self.field = SpaceDelimitedTextField()

    def test_list_to_field(self):
        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList(['a', 'b', 3])),
            'a b 3'
        )

        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList()),
            ''
        )

    def test_field_to_list(self):
        self.assertEqual(
            self.field.to_python('a b 3'),
            PrettyPrintList(['a', 'b', '3'])
        )

        self.assertEqual(
            self.field.to_python(''),
            PrettyPrintList()
        )

    def test_sane_inverse(self):
        l = PrettyPrintList(['a', 'b', 'c'])
        self.assertEqual(
            self.field.to_python(self.field.get_db_prep_value(l)),
            l
        )


from pts.core.utils.packages import extract_vcs_information
class PackageUtilsTests(SimpleTestCase):
    """
    Tests the pts.core.utils.packages utlity functions.
    """
    def test_get_vcs(self):
        browser_url = 'http://other-url.com'
        vcs_url = 'git://url.com'
        d = {
            'Vcs-Git': vcs_url,
            'Vcs-Browser': browser_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'browser': browser_url,
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Browser not found
        d = {
            'Vcs-Git': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # A VCS type longer than three letters
        d = {
            'Vcs-Darcs': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'darcs',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Empty dict
        self.assertDictEqual({}, extract_vcs_information({}))
        # No vcs information in the dict
        self.assertDictEqual({}, extract_vcs_information({
            'stuff': 'that does not',
            'have': 'anything to do',
            'with': 'vcs'
        }))


from pts.core.models import Developer, SourceRepositoryEntry

class SourceRepositoryEntryTests(TestCase):
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]

    def test_add_source_entry_to_repository(self):
        """
        Tests adding a source entry to a repository instance.
        """
        src_pkg = SourcePackage.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        # An entry is created.
        self.assertEqual(SourceRepositoryEntry.objects.count(), 1)
        e = SourceRepositoryEntry.objects.all()[0]
        self.assertEqual(e.source_package, src_pkg)
        # A developer instance is created on the fly
        self.assertEqual(Developer.objects.count(), 1)
        # Architectures are all found
        self.assertEqual(e.architectures.count(), len(architectures))

    def test_update_source_entry(self):
        """
        Tests updating a source entry.
        """
        src_pkg = SourcePackage.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        self.repository.update_source_package(src_pkg, **{
            'version': '0.2',
            'binary_packages': ['bin-pkg']
        })

        self.assertEqual(SourceRepositoryEntry.objects.count(), 1)
        e = SourceRepositoryEntry.objects.all()[0]
        # Stil linked to the same source package.
        self.assertEqual(e.source_package, src_pkg)
        # The version number is bumped up
        e.version = '0.2'
        # New binary package created.
        self.assertEqual(BinaryPackage.objects.count(), 1)
        self.assertEqual('bin-pkg', BinaryPackage.objects.all()[0].name)
