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
Tests for the PTS core data retrieval.
"""
from __future__ import unicode_literals
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.core.files.base import ContentFile
from django.utils.six.moves import mock
from pts.core.tasks import run_task
from pts.core.models import Subscription, EmailUser, PackageName, BinaryPackageName
from pts.core.models import SourcePackageName, SourcePackage
from pts.core.models import SourcePackageRepositoryEntry
from pts.core.models import PseudoPackageName
from pts.core.models import Repository
from pts.core.models import ExtractedSourceFile
from pts.core.models import News
from pts.core.tasks import Job
from pts.core.tasks import JobState
from pts.core.tasks import Event
from pts.core.retrieve_data import GenerateNewsFromRepositoryUpdates
from pts.core.retrieve_data import UpdateRepositoriesTask
from pts.core.retrieve_data import retrieve_repository_info

from pts.core.tasks import BaseTask
from .common import create_source_package
from .common import make_temp_directory

import os
import sys


@override_settings(PTS_VENDOR_RULES='pts.core.tests.tests_retrieve_data')
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
                for pkg in PackageName.subscription_only_packages.all()
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
        self.assertEqual(PackageName.subscription_only_packages.count(),
                         0)

        self.update_pseudo_package_list()

        self.assertEqual(PseudoPackageName.objects.count(), 0)
        self.assertEqual(PackageName.subscription_only_packages.count(),
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


class RetrieveRepositoryInfoTests(TestCase):
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
        mock_update.return_value = (
            [(self.repository, self.get_path_to(file_name))],
            []
        )

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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.get_sources_files_for_repository')
    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
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


class GenerateNewsFromRepositoryUpdatesTest(TestCase):
    """
    Tests the news generated by various repository updates.
    """
    def setUp(self):
        self.job_state = mock.create_autospec(JobState)
        self.job_state.events_for_task.return_value = []
        self.job = mock.create_autospec(Job)
        self.job.job_state = self.job_state
        self.generate_news_task = GenerateNewsFromRepositoryUpdates()
        self.generate_news_task.job = self.job

    def add_mock_events(self, name, arguments):
        """
        Helper method adding mock events which the news generation task will
        see when it runs.
        """
        self.job_state.events_for_task.return_value.append(
            Event(name=name, arguments=arguments)
        )

    def run_task(self):
        self.generate_news_task.execute()

    def create_source_package(self, name, version, events=True):
        """
        Helper method which creates a new source package and makes sure all
        events that would have been raised on creating the package are
        passed to the news generation task if the ``events`` flag is set.

        :param name: The name of the source package to create
        :param version: The version of the source package which is created
        :param events: A flag indicating whether the corresponding events
            should be passed to the generation task when it runs.
        """
        # Make sure the source package name object exists
        src_pkg_name, _ = SourcePackageName.objects.get_or_create(name=name)
        src_pkg, _ = SourcePackage.objects.get_or_create(
            source_package_name=src_pkg_name, version=version)
        # Add all events for a newly created source package which the task will
        # receive.
        if events:
            self.add_mock_events('new-source-package-version', {
                'name': name,
                'version': version,
            })

        return src_pkg

    def add_source_package_to_repository(self, name, version, repository,
                                         events=True):
        """
        Helper method which adds a source package to the given repository
        and makes sure the corresponding events are received by the
        news generation task if the ``events`` flag is set.

        :param name: The name of the source package
        :param version: The version of the source package
        :param repository: The repository to which to add the source package
        :param events: A flag indicating whether the corresponding events
            should be passed to the generation task when it runs.
        """
        qs = Repository.objects.filter(name=repository)
        repo, _ = Repository.objects.get_or_create(name=repository, defaults={
            'shorthand': repository,
            'suite': 'suite',
            'components': ['component']
        })

        source_package = SourcePackage.objects.get(
            source_package_name__name=name,
            version=version)

        entry = SourcePackageRepositoryEntry(
            repository=repo,
            source_package=source_package)
        entry.save()

        if events:
            self.add_mock_events('new-source-package-version-in-repository', {
                'name': name,
                'version': version,
                'repository': repository,
            })

    def remove_source_package_from_repository(self, name, version, repository,
                                              events=True):
        """
        Helper method which removes the given source package version from the
        given repository. It makes sure the corresponding events are received
        by the news generation task if the ``events`` flag is set.
        """
        if events:
            self.add_mock_events('lost-source-package-version-in-repository', {
                'name': name,
                'version': version,
                'repository': repository,
            })

    def assert_correct_accepted_message(self, title,
                                        package_name, version, repository):
        self.assertEqual(
            'Accepted {pkg} version {ver} to {repo}'.format(
                pkg=package_name, ver=version, repo=repository),
            title
        )

    def assert_correct_migrated_message(self, title,
                                        package_name, version, repository):
        self.assertEqual(
            '{pkg} version {ver} MIGRATED to {repo}'.format(
                pkg=package_name, ver=version, repo=repository),
            title
        )

    def assert_correct_removed_message(self, title,
                                       package_name, version, repository):
        self.assertEqual(
            '{pkg} version {ver} REMOVED from {repo}'.format(
                pkg=package_name, ver=version, repo=repository),
            title
        )

    def test_new_source_package(self):
        """
        Tests the case when a completely new source package is created (it was
        not seen in any repository previously).
        """
        source_package_name = 'dummy-package'
        source_package_version = '1.0.0'
        repository_name = 'some-repository'
        self.create_source_package(source_package_name, source_package_version)
        self.add_source_package_to_repository(
            source_package_name, source_package_version, repository_name)

        self.run_task()

        # A news item was created
        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.package.name, source_package_name)
        self.assert_correct_accepted_message(
            news.title,
            source_package_name, source_package_version, repository_name)

    def test_new_source_package_version(self):
        """
        Tests the case when a new version of an already existing source package
        is created.
        """
        source_package_name = 'dummy-package'
        source_package_version = '1.1.0'
        repository_name = 'some-repository'
        # Create the package, but do not add those events to the task
        self.create_source_package(
            source_package_name, source_package_version, events=False)
        # Add the package to the repository
        self.add_source_package_to_repository(
            source_package_name, source_package_version, repository_name)

        self.run_task()

        # A news item was created
        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.package.name, source_package_name)
        self.assert_correct_migrated_message(
            news.title,
            source_package_name, source_package_version, repository_name)

    def test_new_source_package_version_replaces_old_one(self):
        """
        Tests the case when a new version of an already existing source
        package is created and added to the repository which contains
        the old package version.
        """
        source_package_name = 'dummy-package'
        old_version = '1.0.0'
        new_version = '1.1.0'
        repository = 'repo'
        # Create the old version and make sure it is already in the
        # repository
        self.create_source_package(
            source_package_name, old_version, events=False)
        self.add_source_package_to_repository(
            source_package_name, old_version, repository, events=False)
        # Now create the new version and make it replace the old version
        # in the repository
        self.create_source_package(source_package_name, new_version)
        self.add_source_package_to_repository(
            source_package_name, new_version, repository)
        self.remove_source_package_from_repository(
            source_package_name, old_version, repository)

        self.run_task()

        # Only one news item is created
        self.assertEqual(1, News.objects.count())

    def test_multiple_new_versions_same_repo(self):
        """
        Tests the case when there are multiple new versions in a repository.
        """
        source_package_name = 'dummy-package'
        versions = ['1.0.0', '1.1.0']
        repository_name = 'some-repository'
        # Create the package versions
        for version in versions:
            self.create_source_package(source_package_name, version)
            self.add_source_package_to_repository(
                source_package_name, version, repository_name)

        self.run_task()

        # Two news items exist
        self.assertEqual(2, News.objects.count())
        titles = [news.title for news in News.objects.all()]
        ## This is actually a sort by version found in the title
        titles.sort()
        for title, version in zip(titles, versions):
            self.assert_correct_accepted_message(
                title,
                source_package_name, version, repository_name
            )

    def test_multiple_new_versions_different_repos(self):
        """
        Tests the case when there are mutliple new versions of a source package
        each in a different repository.
        """
        source_package_name = 'dummy-package'
        versions = ['1.0.0', '1.1.0']
        repositories = ['repo1', 'repo2']
        # Create these versions
        for version, repository in zip(versions, repositories):
            self.create_source_package(source_package_name, version)
            self.add_source_package_to_repository(
                source_package_name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        titles = [news.title for news in News.objects.all()]
        ## This is actually a sort by version found in the title
        titles.sort()
        for title, version, repository_name in zip(titles, versions, repositories):
            self.assert_correct_accepted_message(
                title,
                source_package_name, version, repository_name
            )

    def test_package_version_add_different_repos(self):
        """
        Tests the case where a single existing package version is added to two
        repositories.
        """
        source_package_name = 'dummy-package'
        version = '1.1.0'
        repositories = ['repo1', 'repo2']
        self.create_source_package(source_package_name, version, events=False)
        for repository in repositories:
            self.add_source_package_to_repository(
                source_package_name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        ## This is a sort by repository name
        titles = [news.title for news in News.objects.all()]
        for title, repository_name in zip(titles, repositories):
            self.assert_correct_migrated_message(
                title,
                source_package_name, version, repository_name
            )

    def test_package_version_updates_different_repos(self):
        """
        Tests the case where a single existing package version is added to two
        repositories replacing the versions previously found in those
        repositories.
        """
        source_package_name = 'dummy-package'
        old_version = '1.0.0'
        version = '1.1.0'
        repositories = ['repo1', 'repo2']
        self.create_source_package(source_package_name, version, events=False)
        self.create_source_package(
            source_package_name, old_version, events=False)
        for repository in repositories:
            # Old version
            self.add_source_package_to_repository(
                source_package_name, old_version, repository, events=False)
            # Replace the old version with the new one
            self.remove_source_package_from_repository(
                source_package_name, old_version, repository)
            self.add_source_package_to_repository(
                source_package_name, version, repository)

        self.run_task()

        # Only two news messages.
        self.assertEqual(2, News.objects.count())
        ## This is a sort by repository name
        titles = [news.title for news in News.objects.all()]
        for title, repository_name in zip(titles, repositories):
            self.assert_correct_migrated_message(
                title,
                source_package_name, version, repository_name
            )

    def test_multiple_package_updates_different_repos(self):
        """
        Tests the case where different repositories get different new package
        versions when they already previously had another version of the
        package.
        """
        source_package_name = 'dummy-package'
        versions = ['1.1.0', '1.2.0']
        old_version = '1.0.0'
        repositories = ['repo1', 'repo2']
        for repository in repositories:
            self.create_source_package(
                source_package_name, old_version, events=False)
            self.add_source_package_to_repository(
                source_package_name, old_version, repository, events=False)
        # Add the new package version to each repository
        for version, repository in zip(versions, repositories):
            self.create_source_package(source_package_name, version)
            self.add_source_package_to_repository(
                source_package_name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        titles = [news.title for news in News.objects.all()]
        titles.sort()
        for title, version, repository in zip(titles, versions, repositories):
            self.assert_correct_accepted_message(
                title,
                source_package_name, version, repository)

    def test_source_package_removed(self):
        """
        Tests the case where a single source package version is removed
        from a repository.
        """
        source_package_name = 'dummy-package'
        version = '1.0.0'
        repository = 'repo'
        self.create_source_package(source_package_name, version, events=False)
        self.remove_source_package_from_repository(
            source_package_name, version, repository)

        self.run_task()

        # A news item is created.
        self.assertEqual(1, News.objects.count())
        self.assert_correct_removed_message(
            News.objects.all()[0].title,
            source_package_name, version, repository
        )

    def test_multiple_versions_removed_same_repo(self):
        """
        Tests the case where multiple versions of the same package are removed
        from the same repository.
        """
        source_package_name = 'dummy-package'
        versions = ['1.0.0', '1.1.0']
        repository = 'repo'
        for version in versions:
            self.create_source_package(
                source_package_name, version, events=False)
            self.remove_source_package_from_repository(
                source_package_name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        titles = [news.title for news in News.objects.all()]
        ## This sorts the titles by version number
        titles.sort()
        for title, version in zip(titles, versions):
            self.assert_correct_removed_message(
                title,
                source_package_name, version, repository
            )

    def test_migrate_and_remove(self):
        """
        Tests the case where a single package version is simultaneously
        added to one repository and removed from another.
        """
        source_package_name = 'dummy-package'
        version = '1.0.0'
        repositories = ['repo1', 'repo2']

        self.create_source_package(
            source_package_name, version, events=False)
        self.add_source_package_to_repository(
            source_package_name, version, repositories[0], events=False)
        # Add the version to one repository
        self.add_source_package_to_repository(
            source_package_name, version, repositories[1])
        # Remove it from the one that already had it
        self.remove_source_package_from_repository(
            source_package_name, version, repositories[0])

        self.run_task()

        # Two news items - removed from one repositories, migrated to another
        self.assertEqual(2, News.objects.count())
        self.assert_correct_removed_message(
            News.objects.all()[0].title,
            source_package_name, version, repositories[0])
        self.assert_correct_migrated_message(
            News.objects.all()[1].title,
            source_package_name, version, repositories[1])

    def test_multiple_packages_added_same_repo(self):
        """
        Tests the case where multiple new packages are added to the same
        repository.
        """
        names = ['package1', 'package2']
        version = '1.0.0'
        repository = 'repo1'
        for name in names:
            self.create_source_package(name, version)
            self.add_source_package_to_repository(name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        all_news = sorted(News.objects.all(), key=lambda x: x.title)
        for name, news in zip(names, all_news):
            self.assert_correct_accepted_message(
                news.title,
                name, version, repository)
            # The news is linked with the correct package
            self.assertEqual(news.package.name, name)

    def test_multiple_packages_removed_different_repos(self):
        """
        Tests the case where multiple packages are removed from different
        repositories.
        """
        names = ['package1', 'package2']
        version = '1.0.0'
        repositories = ['repo1', 'repo2']
        for name, repository in zip(names, repositories):
            self.create_source_package(name, version, events=False)
            self.add_source_package_to_repository(name, version, repository,
                                                  events=False)
            # Remove the source package from the repository
            self.remove_source_package_from_repository(
                name, version, repository)

        self.run_task()

        self.assertEqual(2, News.objects.count())
        all_news = sorted(News.objects.all(), key=lambda x: x.title)
        for name, news, repository in zip(names, all_news, repositories):
            self.assert_correct_removed_message(
                news.title,
                name, version, repository)
            # The news is linked with the correct package
            self.assertEqual(news.package.name, name)

    @mock.patch('pts.core.retrieve_data.get_resource_content')
    def test_dsc_file_in_news_content(self, mock_get_resource_content):
        """
        Tests that the dsc file is found in the content of a news item created
        when a new package version appears.
        """
        name = 'package'
        version = '1.0.0'
        repository = 'repo'
        self.create_source_package(name, version)
        self.add_source_package_to_repository(name, version, repository)
        expected_content = 'This is fake content'
        mock_get_resource_content.return_value = expected_content.encode('utf-8')

        self.run_task()

        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.content, expected_content)

    def test_changelog_entry_in_news_content(self):
        """
        Tests that the news item created for new source package versions
        contains the changelog entry for the version.
        """
        name = 'package'
        version = '1.0.0'
        repository = 'repo'
        src_pkg = self.create_source_package(name, version)
        self.add_source_package_to_repository(name, version, repository)
        changelog_entry = (
            "package (1.0.0) suite; urgency=high\n\n"
            "  * New stable release:\n"
            "    - Feature 1\n"
            "    - Feature 2\n\n"
            " -- Maintaner <email@domain.com> Mon, 1 July 2013 09:00:00 +0000"
        )
        with make_temp_directory('-pts-media') as temp_media_dir:
            ExtractedSourceFile.objects.create(
                source_package=src_pkg,
                extracted_file=ContentFile(changelog_entry, name='changelog'),
                name='changelog')

            self.run_task()

            self.assertEqual(News.objects.count(), 1)
            news = News.objects.all()[0]
            self.assertIn(changelog_entry, news.content)
