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
Tests for the Distro Tracker core data retrieval.
"""
from __future__ import unicode_literals
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils.six.moves import mock
from distro_tracker.core.tasks import run_task
from distro_tracker.core.tasks import Job
from distro_tracker.core.tasks import JobState
from distro_tracker.core.tasks import Event
from distro_tracker.core.models import Subscription, EmailSettings, PackageName, BinaryPackageName
from distro_tracker.core.models import SourcePackageName, SourcePackage
from distro_tracker.core.models import SourcePackageRepositoryEntry
from distro_tracker.core.models import PseudoPackageName
from distro_tracker.core.models import BinaryPackage
from distro_tracker.core.models import Repository
from distro_tracker.core.models import Architecture
from distro_tracker.core.models import Team
from distro_tracker.core.retrieve_data import UpdateRepositoriesTask
from distro_tracker.core.retrieve_data import UpdateTeamPackagesTask
from distro_tracker.core.retrieve_data import retrieve_repository_info
from distro_tracker.core.tests.common import set_mock_response
from distro_tracker.accounts.models import User, UserEmail

from distro_tracker.core.tasks import BaseTask
from .common import create_source_package

import os
import sys


@override_settings(DISTRO_TRACKER_VENDOR_RULES='distro_tracker.core.tests.tests_retrieve_data')
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
        from distro_tracker.core.retrieve_data import update_pseudo_package_list
        update_pseudo_package_list()

    def populate_packages(self, packages):
        """
        Helper method adds the given packages to the database.
        """
        for package in packages:
            PseudoPackageName.objects.create(name=package)

    def test_all_pseudo_packages_added(self):
        """
        Tests that all pseudo packages provided by the vendor are added to the
        database.
        """
        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackageName.objects.all()])
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
            sorted([package.name for package in PseudoPackageName.objects.all()])
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
            sorted([package.name for package in PseudoPackageName.objects.all()])
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
            sorted([package.name for package in PseudoPackageName.objects.all()])
        )
        # Old pseudo packages are now demoted to subscription-only packages
        self.assertSequenceEqual(
            sorted(old_packages),
            sorted([
                pkg.name
                for pkg in PackageName.objects.filter(pseudo=False, binary=False, source=False).all()
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
        from distro_tracker.vendor.common import PluginProcessingError
        self.mock_get_pseudo_package_list.side_effect = PluginProcessingError()
        self.update_pseudo_package_list()

        self.assertSequenceEqual(
            sorted(self.packages),
            sorted([package.name for package in PseudoPackageName.objects.all()])
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

        user_email = UserEmail.objects.get(email=user_email)
        # Still subscribed to the demoted package
        self.assertTrue(user_email.emailsettings.is_subscribed_to(removed_package))
        # Still subscribed to the pseudo package
        self.assertTrue(user_email.emailsettings.is_subscribed_to(self.packages[0]))

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
        self.assertEqual(PackageName.objects.filter(source=False, binary=False, pseudo=False).count(),
                         0)

        self.update_pseudo_package_list()

        self.assertEqual(PseudoPackageName.objects.count(), 0)
        self.assertEqual(PackageName.objects.filter(source=False, binary=False, pseudo=False).count(),
                         len(old_packages))

    @mock.patch('distro_tracker.core.retrieve_data.update_pseudo_package_list')
    def test_management_command_called(self, mock_update_pseudo_package_list):
        """
        Tests that the management command for updating pseudo packages calls
        the correct function.
        """
        from django.core.management import call_command
        call_command('tracker_update_pseudo_packages')

        mock_update_pseudo_package_list.assert_called_with()


class RetrieveRepositoryInfoTests(TestCase):
    @mock.patch('distro_tracker.core.admin.requests')
    def test_sources_list_entry_validation(self, mock_requests):
        from distro_tracker.core.admin import validate_sources_list_entry
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
        set_mock_response(mock_requests, status_code=404)
        # There is no Release file at the given URL
        with self.assertRaises(ValidationError):
            validate_sources_list_entry('deb http://does-not-matter.com/ part3 part4')

    @mock.patch('distro_tracker.core.retrieve_data.requests')
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
        set_mock_response(mock_requests, mock_response_text)

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

    @mock.patch('distro_tracker.core.retrieve_data.requests')
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
        set_mock_response(mock_requests, mock_response_text)

        from distro_tracker.core.retrieve_data import InvalidRepositoryException
        with self.assertRaises(InvalidRepositoryException):
            retrieve_repository_info('deb http://repository.com/ stable')

    @mock.patch('distro_tracker.core.retrieve_data.requests')
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
        set_mock_response(mock_requests, mock_response_text)

        repository_info = retrieve_repository_info(
            'deb http://repository.com/ stable')
        # It uses the suite name from the sources.list
        self.assertEqual(repository_info['suite'], 'stable')
        # Codename is not found
        self.assertIsNone(repository_info['codename'])


class RetrieveSourcesInformationTest(TestCase):
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]
        self.caught_events = []

        # A dummy task which simply receives all events that the update task
        # emits.
        self.intercept_events_task = self.create_task_class(
            (),
            UpdateRepositoriesTask.PRODUCES_EVENTS,
            ()
        )
        self._old_plugins = BaseTask.plugins
        BaseTask.plugins = [UpdateRepositoriesTask, self.intercept_events_task]

    def tearDown(self):
        # Return them as we found them.
        BaseTask.plugins = self._old_plugins

    def get_path_to(self, file_name):
        return os.path.join(os.path.dirname(__file__), 'tests-data', file_name)
        self.intercept_events_task.unregister_plugin()

    def run_update(self):
        run_task(UpdateRepositoriesTask)

    def create_task_class(self, produces, depends_on, raises):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        caught_events = self.caught_events
        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on

            def __init__(self, *args, **kwargs):
                super(TestTask, self).__init__(*args, **kwargs)

            def execute(self):
                for event in raises:
                    self.raise_event(event)
                caught_events.extend(list(self.get_all_events()))
        return TestTask

    def set_mock_sources(self, mock_update, file_name):
        old_return = mock_update.return_value
        if not isinstance(old_return, tuple):
            old_return = ([], [])

        sources, packages = old_return
        mock_update.return_value = ([
            (self.repository, self.get_path_to(file_name))
        ], packages)

    def set_mock_packages(self, mock_update, file_name):
        old_return = mock_update.return_value
        if not isinstance(old_return, tuple):
            old_return = ([], [])

        sources, packages = old_return
        mock_update.return_value = sources, [
            (self.repository, self.get_path_to(file_name))
        ]

    def clear_events(self):
        self.caught_events = []

    def assert_events_raised(self, events):
        """
        Asserts that the update task emited all the given events.
        """
        raised_event_names = [
            event.name
            for event in self.caught_events
        ]
        self.assertEqual(len(events), len(raised_event_names))

        for event_name in events:
            self.assertIn(event_name, raised_event_names)

    def assert_package_by_name_in(self, pkg_name, qs):
        self.assertIn(pkg_name, [pkg.name for pkg in qs])

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_repositories_creates_source(self, mock_update_repositories):
        """
        Tests that a new source package is created when a sources file is
        updated.
        """
        self.set_mock_sources(mock_update_repositories, 'Sources')

        self.run_update()

        self.assertEqual(SourcePackageName.objects.count(), 1)
        self.assertIn(
            'chromium-browser',
            [pkg.name for pkg in SourcePackageName.objects.all()]
        )
        self.assertEqual(BinaryPackageName.objects.count(), 8)
        self.assert_events_raised([
            'new-source-package',
            'new-source-package-in-repository',
            'new-source-package-version',
            'new-source-package-version-in-repository',
        ] + ['new-binary-package'] * 8)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_repositories_existing(self, mock_update_repositories):
        """
        Tests that when an existing source repository is changed in the newly
        retrieved data, it is updated in the database.
        """
        # The source package name exists, but is in no repository (no versions)
        SourcePackageName.objects.create(name='chromium-browser')
        # Sanity check - there were no binary packages
        self.assertEqual(BinaryPackageName.objects.count(), 0)
        self.set_mock_sources(mock_update_repositories, 'Sources')

        self.run_update()

        # Still one source package.
        self.assertEqual(SourcePackageName.objects.count(), 1)
        self.assert_package_by_name_in(
            'chromium-browser',
            SourcePackageName.objects.all()
        )
        self.assertEqual(BinaryPackageName.objects.count(), 8)
        self.assert_events_raised([
            'new-source-package-in-repository',
            'new-source-package-version',
            'new-source-package-version-in-repository',
        ] + ['new-binary-package'] * 8)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_repositories_no_changes(self, mock_update_repositories):
        """
        Tests that when an update is ran multiple times with no changes to the
        data, nothing changes in the database either.
        """
        self.set_mock_sources(mock_update_repositories, 'Sources')
        self.run_update()

        # Run it again.
        self.clear_events()
        self.run_update()

        self.assertEqual(SourcePackageName.objects.count(), 1)
        # No events emitted since nothing was done.
        self.assertEqual(len(self.caught_events), 0)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_changed_binary_mapping_1(self, mock_update):
        """
        Tests the scenario when new data changes the source package to which
        a particular binary package belongs.
        """
        self.set_mock_sources(mock_update, 'Sources-minimal-1')

        src_pkg = create_source_package({
            'name': 'dummy-package',
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
        })
        self.repository.add_source_package(src_pkg)

        src_pkg2 = create_source_package({
            'name': 'src-pkg',
            'binary_packages': ['dummy-package-binary', 'other-package'],
            'version': '2.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
        })
        self.repository.add_source_package(src_pkg2)
        # Sanity check: the binary package now exists
        self.assertEqual(BinaryPackageName.objects.count(), 2)
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )

        self.run_update()

        # Both source package names are still here
        self.assertEqual(SourcePackageName.objects.count(), 2)
        # Still only two source packages since the original ones were merely
        # updated.
        self.assertEqual(SourcePackage.objects.count(), 2)
        self.assertEqual(SourcePackageRepositoryEntry.objects.count(), 2)
        # The package names are unchanged
        self.assert_package_by_name_in(
            'dummy-package',
            SourcePackageName.objects.all()
        )
        self.assert_package_by_name_in(
            'src-pkg',
            SourcePackageName.objects.all()
        )
        src_pkg = SourcePackageName.objects.get(name='dummy-package')
        # Both binary packages are still here
        self.assertEqual(BinaryPackageName.objects.count(), 2)
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )
        # This binary package is now linked with a different source package
        bin_pkg = BinaryPackageName.objects.get(name='dummy-package-binary')
        self.assertEqual(
            bin_pkg.main_source_package_name,
            src_pkg
        )

        self.assert_events_raised(
            ['new-source-package-version'] * 2 +
            ['new-source-package-version-in-repository'] * 2 +
            ['lost-source-package-version-in-repository'] * 2 +
            ['lost-version-of-source-package'] * 2
        )

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_changed_binary_mapping_2(self, mock_update):
        """
        Tests the scenario when new data changes the source package to which
        a particular binary package belongs and the old source package is
        removed from the repository.
        """
        self.set_mock_sources(mock_update, 'Sources-minimal')

        src_pkg = create_source_package({
            'name': 'dummy-package',
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
        })
        self.repository.add_source_package(src_pkg)

        src_pkg2 = create_source_package({
            'name': 'src-pkg',
            'binary_packages': ['dummy-package-binary'],
            'version': '2.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
        })
        self.repository.add_source_package(src_pkg2)
        # Sanity check: the binary package now exists
        self.assertEqual(BinaryPackageName.objects.count(), 1)
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )

        self.run_update()

        # There is only one source package left
        self.assertEqual(SourcePackageName.objects.count(), 1)
        # And only one repository entry
        self.assertEqual(SourcePackageRepositoryEntry.objects.count(), 1)
        self.assert_package_by_name_in(
            'dummy-package',
            SourcePackageName.objects.all()
        )
        src_pkg = SourcePackageName.objects.get(name='dummy-package')
        # The binary package still exists
        self.assertEqual(BinaryPackageName.objects.count(), 1)
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )
        # The binary package is now linked with a different source package
        bin_pkg = BinaryPackageName.objects.get(name='dummy-package-binary')
        self.assertEqual(bin_pkg.main_source_package_name, src_pkg)

        self.assert_events_raised(
            ['new-source-package-version'] +
            ['new-source-package-version-in-repository'] +
            ['lost-version-of-source-package'] * 2 +
            ['lost-source-package-version-in-repository'] * 2 +
            ['lost-source-package']
        )

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_removed_binary_package(self, mock_update):
        """
        Test the scenario when new data removes an existing binary package.
        """
        self.set_mock_sources(mock_update, 'Sources-minimal')
        src_pkg = create_source_package({
            'name': 'dummy-package',
            'binary_packages': ['some-package'],
            'version': '0.1',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
        })
        self.repository.add_source_package(src_pkg)
        # Sanity check -- the binary package exists.
        self.assert_package_by_name_in(
            'some-package',
            BinaryPackageName.objects.all()
        )

        self.run_update()

        # The binary package should no longer exist, replaced by a different one
        self.assertEqual(BinaryPackageName.objects.count(), 1)
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )
        # The new binary package is now mapped to the existing source package
        bin_pkg = BinaryPackageName.objects.get(name='dummy-package-binary')
        self.assertEqual(
            bin_pkg.main_source_package_name,
            src_pkg.source_package_name)
        # All events?
        self.assert_events_raised(
            ['new-source-package-version',
             'new-source-package-version-in-repository'] +
            ['new-binary-package'] +
            ['lost-version-of-source-package',
             'lost-source-package-version-in-repository'] +
            ['lost-binary-package']
        )

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.get_sources_files_for_repository')
    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_multiple_sources_files(self,
                                           mock_update_repositories,
                                           mock_all_sources):
        """
        Tests the update scenario where only one of the Sources files is
        updated. For example, only the main component of a repository is
        updated whereas contrib and non-free were not.
        """
        src_pkg = create_source_package({
            'name': 'dummy-package',
            'binary_packages': ['dummy-package-binary'],
            'version': '1.0.0',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
            'dsc_file_name': 'file.dsc'
        })
        self.repository.add_source_package(src_pkg)
        # Updated sources - only 1 file
        self.set_mock_sources(mock_update_repositories, 'Sources')
        # All sources - 2 files
        mock_all_sources.return_value = [
            self.get_path_to('Sources'),
            self.get_path_to('Sources-minimal')
        ]
        # Sanity check - only 1 source package exists
        self.assertEqual(SourcePackageName.objects.count(), 1)

        self.run_update()

        # The package from the file which was not updated is still there
        self.assert_package_by_name_in(
            'dummy-package',
            SourcePackageName.objects.all()
        )
        # It is still in the repository
        self.assertEqual(
            1,
            SourcePackageRepositoryEntry.objects.filter(
                repository=self.repository,
                source_package__source_package_name__name='dummy-package').count(),
        )
        # The matching binary package is also there
        self.assert_package_by_name_in(
            'dummy-package-binary',
            BinaryPackageName.objects.all()
        )
        # The new package from the updated file is there
        self.assertEqual(SourcePackageName.objects.count(), 2)


    @mock.patch('distro_tracker.core.retrieve_data.AptCache.get_sources_files_for_repository')
    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_multiple_versions_in_source_file(self,
                                                     mock_update_repositories,
                                                     mock_all_sources):
        """
        Tests the update scenario where a Sources file that was not updated
        contains multiple source versions of the same source package.
        """
        src_name = 'dummy-package'
        versions = ['1.0.0', '2.0.0']

        src_pkgs = [
            create_source_package({
                'name': src_name,
                'binary_packages': ['dummy-package-binary'],
                'version': version,
                'maintainer': {
                    'name': 'Maintainer',
                    'email': 'maintainer@domain.com'
                },
                'architectures': ['amd64', 'all'],
                'dsc_file_name': 'file.dsc'
            })
            for version in versions
        ]
        for src_pkg in src_pkgs:
            self.repository.add_source_package(src_pkg)
        # Updated sources - only 1 file
        self.set_mock_sources(mock_update_repositories, 'Sources')
        # All sources - 2 files
        mock_all_sources.return_value = [
            self.get_path_to('Sources'),
            self.get_path_to('Sources-multiple-versions')
        ]
        # Sanity check: both versions exist
        self.assertEqual(2, SourcePackage.objects.count())

        self.run_update()

        # The package from the file which was not updated is still there
        self.assert_package_by_name_in(
            'dummy-package',
            SourcePackageName.objects.all()
        )
        # Both versions are still in the repository
        entries = SourcePackageRepositoryEntry.objects.filter(
                repository=self.repository,
                source_package__source_package_name__name='dummy-package')
        self.assertEqual(2, entries.count())
        for entry in entries:
            self.assertIn(entry.source_package.version, versions)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_binary_package_entry_created_1(self, mock_update_repositories):
        """
        Tests that a :class:`BinaryPackage <distro_tracker.core.models.BinaryPackage>`
        instance is added to a :class:`Repository <distro_tracker.core.models.Repository>`
        (a :class:`BinaryPackageRepositoryEntry <distro_tracker.core.models.BinaryPackageRepositoryEntry>`
        is created)
        """
        package_name = 'chromium-browser'
        self.set_mock_sources(mock_update_repositories, 'Sources')
        self.set_mock_packages(mock_update_repositories, 'Packages')

        self.run_update()

        # The source package is still correctly created
        self.assertEqual(SourcePackageName.objects.count(), 1)
        source_package = SourcePackageName.objects.all()[0]
        self.assertEqual(package_name, source_package.name)
        # All binary names related to the source package are created
        self.assertEqual(BinaryPackageName.objects.count(), 8)
        # The binary package is found in the repository
        self.assertEqual(1, self.repository.binary_package_entries.count())
        entry = self.repository.binary_package_entries.all()[0]
        self.assertEqual(
            package_name,
            entry.binary_package.binary_package_name.name)
        # Associated with the correct source package?
        self.assertEqual(
            package_name,
            entry.binary_package.source_package.name)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_binary_package_entry_created_2(self, mock_update_repositories):
        """
        Tests that a :class:`BinaryPackage <distro_tracker.core.models.BinaryPackage>`
        instance is added to a :class:`Repository <distro_tracker.core.models.Repository>`
        (a :class:`BinaryPackageRepositoryEntry <distro_tracker.core.models.BinaryPackageRepositoryEntry>`
        is created) when the name of the binary package is different than the
        name of the source package.
        """
        package_name = 'chromium-browser'
        binary_name = 'chromium-browser-dbg'
        self.set_mock_sources(mock_update_repositories, 'Sources')
        self.set_mock_packages(mock_update_repositories, 'Packages-1')

        self.run_update()

        # The source package is still correctly created
        self.assertEqual(SourcePackageName.objects.count(), 1)
        source_package = SourcePackageName.objects.all()[0]
        self.assertEqual(package_name, source_package.name)
        # All binary names related to the source package are created
        self.assertEqual(BinaryPackageName.objects.count(), 8)
        # The binary package is found in the repository
        self.assertEqual(1, self.repository.binary_package_entries.count())
        entry = self.repository.binary_package_entries.all()[0]
        self.assertEqual(
            binary_name,
            entry.binary_package.binary_package_name.name)
        # Associated with the correct source package?
        self.assertEqual(
            package_name,
            entry.binary_package.source_package.name)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_binary_package_entry_created_3(self, mock_update_repositories):
        """
        Tests that a :class:`BinaryPackage <distro_tracker.core.models.BinaryPackage>`
        instance is added to a :class:`Repository <distro_tracker.core.models.Repository>`
        (a :class:`BinaryPackageRepositoryEntry <distro_tracker.core.models.BinaryPackageRepositoryEntry>`
        is created) when both the name and the version of the binary package
        differ to the ones of the source package.
        """
        package_name = 'chromium-browser'
        binary_name = 'chromium-browser-dbg'
        binary_version = '27.0.1453.110-1~deb7u1+b1'
        self.set_mock_sources(mock_update_repositories, 'Sources')
        self.set_mock_packages(mock_update_repositories, 'Packages-2')

        self.run_update()

        # The source package is still correctly created
        self.assertEqual(SourcePackageName.objects.count(), 1)
        source_package = SourcePackageName.objects.all()[0]
        self.assertEqual(package_name, source_package.name)
        # All binary names related to the source package are created
        self.assertEqual(BinaryPackageName.objects.count(), 8)
        # The binary package is found in the repository
        self.assertEqual(1, self.repository.binary_package_entries.count())
        entry = self.repository.binary_package_entries.all()[0]
        self.assertEqual(
            binary_name,
            entry.binary_package.binary_package_name.name)
        # Associated with the correct source package?
        self.assertEqual(
            package_name,
            entry.binary_package.source_package.name)
        self.assertEqual(
            binary_version,
            entry.binary_package.version)

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_binary_package_entry_removed(self, mock_update_repositories):
        """
        Tests that an existing
        :class:`BinaryPackageRepositoryEntry <distro_tracker.core.models.BinaryPackageRepositoryEntry>`
        is removed if the updated ``Packages`` file no longer contains it.
        """
        binary_name = 'dummy-package-binary'
        source_package = create_source_package({
            'name': 'dummy-package',
            'binary_packages': [binary_name],
            'version': '1.0.0',
            'maintainer': {
                'name': 'Maintainer',
                'email': 'maintainer@domain.com'
            },
            'architectures': ['amd64', 'all'],
            'dsc_file_name': 'file.dsc'
        })
        # Add a binary package to the repository
        bin_name = BinaryPackageName.objects.all()[0]
        bin_pkg = BinaryPackage.objects.create(
            binary_package_name=bin_name,
            source_package=source_package,
            version='1.0.0')
        arch = Architecture.objects.all()[0]
        self.repository.add_binary_package(bin_pkg, architecture=arch)
        self.set_mock_sources(mock_update_repositories, 'Sources')
        # The existing binary package is no longer found in this Packages file
        self.set_mock_packages(mock_update_repositories, 'Packages-2')

        self.run_update()

        # The entry is removed from the repository
        bin_pkgs_in_repo = [
            entry.binary_package.name
            for entry in self.repository.binary_package_entries.all()
        ]
        self.assertNotIn(binary_name, bin_pkgs_in_repo)


class RetrieveSourcesFailureTest(TransactionTestCase):
    """
    Tests retrieving source package information from a repository when there is
    a failure in the process.

    A separate class is made since TransactionTestCase brings a significant
    overhead and there is no need for all tests to incur it.
    """
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]
        self.caught_events = []

        # A dummy task which simply receives all events that the update task
        # emits.
        self.intercept_events_task = self.create_task_class(
            (),
            UpdateRepositoriesTask.PRODUCES_EVENTS,
            ()
        )

    def get_path_to(self, file_name):
        return os.path.join(os.path.dirname(__file__), 'tests-data', file_name)
        self.intercept_events_task.unregister_plugin()

    def run_update(self):
        run_task(UpdateRepositoriesTask)

    def create_task_class(self, produces, depends_on, raises):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        caught_events = self.caught_events
        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on

            def __init__(self, *args, **kwargs):
                super(TestTask, self).__init__(*args, **kwargs)
                self.caught_events = []

            def process_event(self, event):
                caught_events.append(event)

            def execute(self):
                for event in raises:
                    self.raise_event(event)
        return TestTask

    def assert_events_raised(self, events):
        """
        Asserts that the update task emited all the given events.
        """
        raised_event_names = [
            event.name
            for event in self.caught_events
        ]
        self.assertEqual(len(events), len(raised_event_names))

        for event_name in events:
            self.assertIn(event_name, raised_event_names)

    def set_mock_sources(self, mock_update, file_name):
        mock_update.return_value = (
            [(self.repository, self.get_path_to(file_name))],
            []
        )

    @mock.patch('distro_tracker.core.retrieve_data.AptCache.update_repositories')
    def test_update_repositories_invalid(self, mock_update_repositories):
        """
        Tests updating the repositories when the repository's Sources file is
        invalid.
        """
        self.set_mock_sources(mock_update_repositories, 'Sources-invalid')

        # No exceptions propagated
        self.run_update()

        # Nothing was created
        self.assertEqual(SourcePackageName.objects.count(), 0)
        self.assertEqual(BinaryPackageName.objects.count(), 0)
        # No events raised
        self.assert_events_raised([])


class UpdateTeamPackagesTaskTests(TestCase):
    """
    Tests for the :class:`distro_tracker.core.retrieve_data.UpdateTeamPackagesTask` task.
    """
    def setUp(self):
        self.maintainer_email = 'maintainer@domain.com'
        self.uploaders = [
            'uploader1@domain.com',
            'uploader2@domain.com',
        ]
        self.package = create_source_package({
            'name': 'dummy-package',
            'version': '1.0.0',
            'maintainer': {
                'name': 'Maintainer',
                'email': self.maintainer_email,
            },
            'uploaders': self.uploaders,
        })
        self.repository = Repository.objects.create(
            name='repo', shorthand='repo', default=True)
        self.non_default_repository = Repository.objects.create(
            name='nondef', shorthand='nondef')

        self.password = 'asdf'
        self.user = User.objects.create_user(
            main_email='user@domain.com', password=self.password,
            first_name='', last_name='')
        self.team = Team.objects.create_with_slug(
            owner=self.user,
            name="Team",
            maintainer_email=self.maintainer_email)
        # Create a team for each of the uploaders and maintainers
        self.teams = [
            Team.objects.create_with_slug(owner=self.user, name="Team" + str(i))
            for i in range(5)
        ]

        self.job_state = mock.create_autospec(JobState)
        self.job_state.events_for_task.return_value = []
        self.job = mock.create_autospec(Job)
        self.job.job_state = self.job_state
        self.task = UpdateTeamPackagesTask()
        self.task.job = self.job

    def add_mock_events(self, name, arguments):
        """
        Helper method adding mock events which the news generation task will
        see when it runs.
        """
        self.job_state.events_for_task.return_value.append(
            Event(name=name, arguments=arguments)
        )

    def run_task(self):
        self.task.execute()

    def test_new_package_version_in_default_repo(self):
        """
        Tests the scenario where a new package version appears in the default
        repository.
        """
        self.repository.add_source_package(self.package)
        self.add_mock_events('new-source-package-version-in-repository', {
            'name': self.package.name,
            'version': self.package.version,
            'repository': self.repository.name,
        })
        # Sanity check: the team does not have any packages
        self.assertEqual(0, self.team.packages.count())

        self.run_task()

        # The team is now associated with a new package
        self.assertEqual(1, self.team.packages.count())
        self.assertEqual(self.package.name, self.team.packages.all()[0].name)

    def test_new_package_version_team_has_package(self):
        """
        Tests that there is no change to a team when a new package version
        shows up in the default repository when the team is already associated
        to the package.
        """
        self.team.packages.add(self.package.source_package_name)
        self.repository.add_source_package(self.package)
        self.add_mock_events('new-source-package-version-in-repository', {
            'name': self.package.name,
            'version': self.package.version,
            'repository': self.repository.name,
        })

        # Sanity check: the team is definitely already associated to the
        # package
        self.assertEqual(1, self.team.packages.count())

        self.run_task()

        # The team is now associated with a new package
        self.assertEqual(1, self.team.packages.count())
        self.assertEqual(self.package.name, self.team.packages.all()[0].name)

    def test_new_package_version_in_non_default_repo(self):
        """
        Tests that when a new version is added to a non-default repository,
        the teams' package associations are not changed.
        """
        self.repository.add_source_package(self.package)
        self.add_mock_events('new-source-package-version-in-repository', {
            'name': self.package.name,
            'version': self.package.version,
            'repository': self.non_default_repository.name,
        })
        # Sanity check: the team does not have any packages
        self.assertEqual(0, self.team.packages.count())

        self.run_task()

        # The team still has no packages
        self.assertEqual(0, self.team.packages.count())

    def test_new_package_version_adds_uploaders(self):
        """
        Tests that when a new package version appears in the default repository
        the package is added to team's associated with its uploaders.
        """
        # Create an uploader's team
        uploader_team = Team.objects.create_with_slug(
            owner=self.user,
            name='uploader-team',
            maintainer_email=self.uploaders[0])
        self.team.packages.add(self.package.source_package_name)
        self.repository.add_source_package(self.package)
        self.add_mock_events('new-source-package-version-in-repository', {
            'name': self.package.name,
            'version': self.package.version,
            'repository': self.repository.name,
        })
        # Sanity check the uploader's team does not have any packages
        self.assertEqual(0, uploader_team.packages.count())

        self.run_task()

        # The team is now associated with a new package
        self.assertEqual(1, uploader_team.packages.count())
        self.assertEqual(self.package.name, uploader_team.packages.all()[0].name)
        # The maintainer's team is updated in the same time?
        self.assertEqual(1, self.team.packages.count())

    def test_multiple_packages_added(self):
        """
        Tests that when multiple packages are added to the default repository,
        they are all correctly processed.
        """
        team_maintainer_packages = [
            self.package,
            create_source_package({
                'name': 'other-package',
                'version': '1.0.0',
                'maintainer': {
                    'name': 'Maintainer',
                    'email': self.maintainer_email,
                },
                'uploaders': self.uploaders,
            })
        ]
        unknown_maintainer = 'unknown@domain.com'
        unknown_maintainer_packages = [
            create_source_package({
                'name': 'last-package',
                'version': '1.0.0',
                'maintainer': {
                    'name': 'Maintainer',
                    'email': unknown_maintainer,
                },
                'uploaders': self.uploaders,
            })
        ]
        # Add them all to the default repository
        for source_package in team_maintainer_packages + unknown_maintainer_packages:
            self.repository.add_source_package(source_package)
            self.add_mock_events('new-source-package-version-in-repository', {
                'name': source_package.name,
                'version': source_package.version,
                'repository': self.repository.name,
            })
        # Sanity check: the maintainer's team does not have any packages
        self.assertEqual(0, self.team.packages.count())

        self.run_task()

        # The team is not related to the packages with an unknown maintainer
        self.assertEqual(len(team_maintainer_packages), self.team.packages.count())
        all_packages = [p.name for p in self.team.packages.all()]
        for source_package in team_maintainer_packages:
            self.assertIn(source_package.source_package_name.name, all_packages)
