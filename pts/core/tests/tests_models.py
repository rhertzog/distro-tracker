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
Tests for the PTS core module's models.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.core.exceptions import ValidationError
from pts.core.models import Subscription, EmailUser, PackageName, BinaryPackageName
from pts.core.models import SourcePackageName
from pts.core.models import Keyword
from pts.core.models import PseudoPackageName
from pts.core.models import Repository
from pts.core.models import Developer, SourcePackage
from pts.core.models import MailingList


class SubscriptionManagerTest(TestCase):
    def setUp(self):
        self.package = PackageName.objects.create(name='dummy-package')
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
        p = PackageName.objects.create(name='temp')
        self.create_subscription(p.name, self.email_user.email)
        package_not_subscribed_to = PackageName.objects.create(name='qwer')
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
        self.package = PackageName.objects.create(name='dummy-package')
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
        self.package = PackageName.objects.create(name='dummy-package')
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
        self.package = PackageName.objects.create(name='dummy-package')
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
        self.package = PackageName.objects.create(name='dummy-package')

    def test_package_exists(self):
        self.assertTrue(PackageName.objects.exists_with_name(self.package.name))

    def test_package_exists_false(self):
        self.assertFalse(PackageName.objects.exists_with_name('unexisting'))

    def test_source_package_create(self):
        """
        Tests that the sources manager creates source packages.
        """
        p = PackageName.source_packages.create(name='source-package')

        self.assertEqual(p.package_type, PackageName.SOURCE_PACKAGE_TYPE)

    def test_pseudo_package_create(self):
        """
        Tests that the pseudo packages manager creates pseudo pacakges.
        """
        p = PackageName.pseudo_packages.create(name='pseudo-package')

        self.assertEqual(p.package_type, PackageName.PSEUDO_PACKAGE_TYPE)

    def test_subscription_only_package_create(self):
        """
        Tests that the subscription only packages manager creates
        subscription only packages.
        """
        p = PackageName.subscription_only_packages.create(name='package')

        self.assertEqual(p.package_type, PackageName.SUBSCRIPTION_ONLY_PACKAGE_TYPE)

    def test_manager_types_correct_objects(self):
        """
        Tests that the different manager types always return only their
        associated package type.
        """
        # Make sure there are no packages in the beginning
        PackageName.objects.all().delete()
        self.assertEqual(PackageName.objects.count(), 0)

        src_pkg = PackageName.source_packages.create(name='source-package')
        pseudo_pkg = PackageName.pseudo_packages.create(name='pseudo-package')
        sub_only_pkg = PackageName.subscription_only_packages.create(name='package')

        # objects manager returns all packages
        self.assertEqual(PackageName.objects.count(), 3)
        # specific pacakge type managers:
        self.assertEqual(PackageName.source_packages.count(), 1)
        self.assertIn(src_pkg, PackageName.source_packages.all())
        self.assertEqual(PackageName.pseudo_packages.count(), 1)
        self.assertIn(pseudo_pkg, PackageName.pseudo_packages.all())
        self.assertEqual(PackageName.subscription_only_packages.count(), 1)
        self.assertIn(sub_only_pkg, PackageName.subscription_only_packages.all())

    def test_all_with_subscriptions(self):
        """
        Tests the manager method which should return a QuerySet with all
        packages that have at least one subscriber.
        """
        pseudo_package = PseudoPackageName.objects.create(name='pseudo-package')
        sub_only_pkg = PackageName.subscription_only_packages.create(
            name='sub-only-pkg')
        PackageName.subscription_only_packages.create(name='sub-only-pkg-1')

        # When there are no subscriptions, it shouldn't return any results
        self.assertEqual(PackageName.objects.all_with_subscribers().count(), 0)
        self.assertEqual(
            PackageName.pseudo_packages.all_with_subscribers().count(),
            0)
        self.assertEqual(
            PackageName.source_packages.all_with_subscribers().count(),
            0)
        self.assertEqual(
            PackageName.subscription_only_packages.all_with_subscribers().count(),
            0)

        # When subscriptions are added, only the packages with subscriptions
        # are returned
        Subscription.objects.create_for(package_name=self.package.name,
                                        email='user@domain.com')
        Subscription.objects.create_for(package_name=sub_only_pkg.name,
                                        email='other-user@domain.com')
        Subscription.objects.create_for(package_name=pseudo_package.name,
                                        email='some-user@domain.com')

        self.assertEqual(PackageName.objects.all_with_subscribers().count(), 3)
        all_with_subscribers = [
            pkg.name
            for pkg in PackageName.objects.all_with_subscribers()
        ]
        self.assertIn(self.package.name, all_with_subscribers)
        self.assertIn(pseudo_package.name, all_with_subscribers)
        self.assertIn(sub_only_pkg.name, all_with_subscribers)
        # Specific managers...
        self.assertEqual(
            PackageName.pseudo_packages.all_with_subscribers().count(),
            1)
        self.assertEqual(
            PackageName.source_packages.all_with_subscribers().count(),
            1)
        self.assertEqual(
            PackageName.subscription_only_packages.all_with_subscribers().count(),
            1)


class BinaryPackageManagerTest(TestCase):
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.binary_package = BinaryPackageName.objects.create(
            name='binary-package',
            source_package=self.package)

    def test_package_exists(self):
        self.assertTrue(
            BinaryPackageName.objects.exists_with_name(self.binary_package.name))

    def test_package_exists_false(self):
        self.assertFalse(
            BinaryPackageName.objects.exists_with_name('unexisting'))

    def test_binary_and_source_same_name(self):
        """
        Tests that it is possible to create a binary and source package with
        the same name.
        """
        bin_pkg = BinaryPackageName.objects.create(name='package')
        src_pkg = SourcePackageName.objects.create(name='package')
        self.assertIn(bin_pkg, BinaryPackageName.objects.all())
        self.assertIn(src_pkg, SourcePackageName.objects.all())


class sourcepackageTests(TestCase):
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]

    def test_add_source_entry_to_repository(self):
        """
        Tests adding a source entry to a repository instance.
        """
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
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
        self.assertEqual(SourcePackage.objects.count(), 1)
        e = SourcePackage.objects.all()[0]
        self.assertEqual(e.source_package, src_pkg)
        # A developer instance is created on the fly
        self.assertEqual(Developer.objects.count(), 1)
        # Architectures are all found
        self.assertEqual(e.architectures.count(), len(architectures))

    def test_update_source_entry(self):
        """
        Tests updating a source entry.
        """
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
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

        self.assertEqual(SourcePackage.objects.count(), 1)
        e = SourcePackage.objects.all()[0]
        # Stil linked to the same source package.
        self.assertEqual(e.source_package, src_pkg)
        # The version number is bumped up
        e.version = '0.2'
        # New binary package created.
        self.assertEqual(BinaryPackageName.objects.count(), 1)
        self.assertEqual('bin-pkg', BinaryPackageName.objects.all()[0].name)

    def test_get_main_source_package_entry_default_repo(self):
        """
        Tests retrieving the main source package entry.

        The main entry is either the one from a default repository or
        the one which has the highest version number if the package can
        not be found in the default repository.
        """
        self.repository.default = True
        self.repository.save()
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })
        # Create a second repository.
        repo2 = Repository.objects.create(name='repo', shorthand='repo')
        # Add the package to it too.
        repo2.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        # The main entry is the one from the default repository.
        self.assertEqual(src_pkg.main_entry.repository, self.repository)
        self.assertEqual(src_pkg.main_entry.source_package, src_pkg)

    def test_get_main_source_package_entry_only_repo(self):
        """
        Tests retrieving the main source package entry.
        """
        # Make sure it is not default
        self.repository.default = False
        self.repository.save()

        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        self.assertEqual(src_pkg.main_entry.repository, self.repository)
        self.assertEqual(src_pkg.main_entry.source_package, src_pkg)

    def test_get_main_source_package_entry_no_default(self):
        """
        Tests retrieving a main entry when there is no default repository.
        """
        # Make sure it is not default
        self.repository.default = False
        self.repository.save()

        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })
        # Create a second repository.
        repo2 = Repository.objects.create(name='repo', shorthand='repo')
        # Add the package to it too.
        repo2.add_source_package(src_pkg, **{
            'version': '1.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        # The main entry is the one from the second repository since it has
        # a higher version.
        self.assertEqual(src_pkg.main_entry.repository, repo2)
        self.assertEqual(src_pkg.main_entry.source_package, src_pkg)

    def test_update_binary_source_mapping(self):
        """
        Tests updating the main binary-source mapping.
        This mapping determines to which source package users are redirected
        when they attempt to access this binary package.
        """
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'binary_packages': ['binary-package'],
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })
        src_pkg2 = SourcePackageName.objects.create(name='src-pkg')
        self.repository.add_source_package(src_pkg2, **{
            'binary_packages': ['binary-package'],
            'version': '0.2',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
        })

        # Sanity check - linked to the original source package
        bin_pkg = BinaryPackageName.objects.get(name='binary-package')
        self.assertEqual(bin_pkg.source_package, src_pkg)

        # Remove the original source package
        src_pkg.delete()
        bin_pkg.update_source_mapping()

        # The package is now mapped to the other source package.
        bin_pkg = BinaryPackageName.objects.get(name='binary-package')
        self.assertEqual(bin_pkg.source_package, src_pkg2)

    def test_get_directory_url(self):
        """
        Tests retrieving the URL of the package's directory from the entry.
        """
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'binary_packages': ['binary-package'],
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
            'directory': 'pool/path/to/dir',
        })

        e = SourcePackage.objects.all()[0]
        self.assertEqual(
            self.repository.uri + 'pool/path/to/dir',
            e.directory_url
        )

    def test_get_dsc_file_url(self):
        """
        Tests retrieving the URL of the package's .dsc file given in the entry.
        """
        src_pkg = SourcePackageName.objects.create(name='dummy-package')
        architectures = ['amd64', 'all']
        self.repository.add_source_package(src_pkg, **{
            'binary_packages': ['binary-package'],
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': architectures,
            'directory': 'pool/path/to/dir',
            'dsc_file_name': 'file.dsc',
        })

        e = SourcePackage.objects.all()[0]
        self.assertEqual(
            self.repository.uri + 'pool/path/to/dir/file.dsc',
            e.dsc_file_url
        )


class MailingListTest(TestCase):
    def test_validate_url_template(self):
        """
        Tests validation of the URL template field.
        """
        mailing_list = MailingList(name='list', domain='some.domain.com')
        mailing_list.archive_url_template = (
            'http://this.does/not/have/user/parameter')

        with self.assertRaises(ValidationError):
            mailing_list.full_clean()

        mailing_list.archive_url_template = (
            'http://this.does/have/{user}')
        mailing_list.full_clean()

    def test_get_archive_url(self):
        """
        Tests retrieving the archive URL from a MailingList instance.
        """
        mailing_list = MailingList(name='list', domain='some.domain.com')
        mailing_list.archive_url_template = (
            'http://some.domain.com/archive/{user}/')

        self.assertEqual(
            mailing_list.archive_url('this-is-a-user'),
            'http://some.domain.com/archive/this-is-a-user/'
        )

    def test_get_archive_url_for_email(self):
        """
        Test retrieving the archive URL from a MailingList instance when an
        email is given, instead of a user.
        """
        mailing_list = MailingList(name='list', domain='some.domain.com')
        mailing_list.archive_url_template = (
            'http://some.domain.com/archive/{user}/')

        self.assertEqual(
            mailing_list.archive_url_for_email(
                'this-is-a-user@some.domain.com'),
            'http://some.domain.com/archive/this-is-a-user/'
        )

        # Not given a valid email
        self.assertIsNone(
            mailing_list.archive_url_for_email('this-is-not-an-email'))

        # Not given an email in the correct domain
        self.assertIsNone(
            mailing_list.archive_url_for_email('email@other.domain.com'))

    def test_find_matching_mailing_list(self):
        """
        Tests finding a matching mailing list object when given an email.
        """
        expect = MailingList.objects.create(
            name='list', domain='some.domain.com')
        MailingList.objects.create(name='other', domain='other.com')
        MailingList.objects.create(name='domain', domain='domain.com')

        email = 'username@some.domain.com'
        self.assertEqual(MailingList.objects.get_by_email(email), expect)

        email = 'not-an-email'
        self.assertIsNone(MailingList.objects.get_by_email(email))

        email = 'user@no.registered.domain'
        self.assertIsNone(MailingList.objects.get_by_email(email))
