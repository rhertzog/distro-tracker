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
from pts.core.utils import verp
from pts.core.utils import message_from_bytes
from pts.dispatch.custom_email_message import CustomEmailMessage

import sys
if six.PY3:
    from unittest.mock import create_autospec
else:
    from mock import create_autospec


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


@override_settings(PTS_VENDOR_RULES='pts.core.tests')
class RetrievePseudoPackagesTest(TestCase):
    """
    Tests the get_pseudo_package_list data retrieval function.
    """
    def setUp(self):
        # Since the tests module is used to provide the vendor rules,
        # we dynamically add the needed function
        self.packages = ['package1', 'package2']
        self.mock_get_pseudo_package_list = create_autospec(
            lambda: None, return_value=self.packages)
        sys.modules[__name__].get_pseudo_package_list = (
            self.mock_get_pseudo_package_list
        )

    def tearDown(self):
        # The added function is removed after the tests
        delattr(sys.modules[__name__], 'get_pseudo_package_list')

    def get_pseudo_package_list(self):
        """
        Helper method runs the get_pseudo_package_list function.
        """
        # Update the return value
        self.mock_get_pseudo_package_list.return_value = self.packages
        from pts.core.retrieve_data import (
            get_pseudo_package_list as get_pseudo_package_list_test
        )
        get_pseudo_package_list_test()

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
        self.get_pseudo_package_list()

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

        self.get_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_pseudo_package_update(self):
        """
        Tests that when the vendor provided package list is updated, the
        get_pseudo_package_list function properly updates the database too.
        """
        self.populate_packages(self.packages)
        self.packages.append('package3')

        self.get_pseudo_package_list()

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
        self.packages = ['new-package']

        self.get_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )

    def test_management_command_called(self):
        """
        Tests that the management command for updating pseudo packages calls
        the correct function.
        """
        from pts.core.management.commands.pts_update_pseudo_packages import (
            Command as UpdatePseudoPackagesCommand
        )

        command = UpdatePseudoPackagesCommand()
        # Redirect the output to a string not to pollute the test output
        command.stdout = six.StringIO()
        command.handle()

        self.mock_get_pseudo_package_list.assert_called_with()
        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackage.objects.all()])
        )


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
