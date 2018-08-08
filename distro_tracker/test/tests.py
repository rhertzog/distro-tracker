# -*- coding: utf-8 -*-

# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for test functionalities of Distro Tracker.
"""

import copy
import os.path

from django.conf import settings

from distro_tracker.core.models import PackageName, SourcePackage, Repository
from distro_tracker.test import (
    SimpleTestCase,
    TempDirsMixin,
    TestCase,
    TransactionTestCase
)

settings_copy = copy.deepcopy(settings)


class TempDirsTests(object):

    def setUp(self):
        self._settings_during_setup = {}
        for name in self.get_settings_names():
            self._settings_during_setup[name] = getattr(settings, name)

    def get_settings_names(self):
        """
        Return names of all settings that should point to temporary
        directories during tests.
        """
        return TempDirsMixin.DISTRO_TRACKER_PATH_SETTINGS.keys()

    def test_setup_has_same_settings(self):
        """ Test that .setUp() already has the overridden settings. """
        for name in self.get_settings_names():
            self.assertEqual(self._settings_during_setup[name],
                             getattr(settings, name))

    def test_temp_dirs_outside_of_base_path(self):
        """ Test that the settings no longer point inside the base path. """
        for name in self.get_settings_names():
            self.assertNotIn(getattr(settings, 'BASE_DIR'),
                             getattr(settings, name))

    def test_temp_dirs_in_data_path(self):
        """ Test that the settings point within DISTRO_TRACKER_DATA_PATH. """
        for name in self.get_settings_names():
            self.assertIn(getattr(settings, 'DISTRO_TRACKER_DATA_PATH'),
                          getattr(settings, name))

    def test_path_settings_changed(self):
        """
        Tests that the settings have changed (hopefully to point to temporary
        directories).
        """
        for name in self.get_settings_names():
            self.assertNotEqual(getattr(settings, name),
                                getattr(settings_copy, name))


class TestCaseHelpersTests(object):
    def test_get_test_data_path(self):
        self.assertEqual(self.get_test_data_path('myfile'),
                         os.path.join(os.path.dirname(__file__),
                                      'tests-data', 'myfile'))

    def test_add_test_template_dir(self):
        template_dir = self.get_test_data_path('tests-templates')
        self.assertNotIn(template_dir, settings.TEMPLATES[0]['DIRS'])

        self.add_test_template_dir()

        self.assertIn(template_dir, settings.TEMPLATES[0]['DIRS'])
        self.doCleanups()  # Ensure a cleanup function is added
        self.assertNotIn(template_dir, settings.TEMPLATES[0]['DIRS'])


class DatabaseMixinTests(object):
    def assert_fails(self, assert_function, *args):
        with self.assertRaises(AssertionError):
            assert_function(*args)

    def test_assert_does_not_exist(self):
        sample_object = PackageName.objects.create(name='dummy-package')
        self.assert_fails(self.assertDoesNotExist, sample_object)
        sample_object.delete()
        self.assertDoesNotExist(sample_object)

    def test_assert_does_exist(self):
        sample_object = PackageName.objects.create(name='dummy-package')
        self.assertDoesExist(sample_object)
        sample_object.delete()
        self.assert_fails(self.assertDoesExist, sample_object)

    def test_create_source_package_no_args(self):
        srcpkg = self.create_source_package()
        self.assertIsInstance(srcpkg, SourcePackage)
        self.assertEqual(srcpkg.name, 'test-package')
        self.assertEqual(srcpkg.version, '1')

    def test_create_source_package_is_saved(self):
        srcpkg = self.create_source_package()
        self.assertIsNotNone(srcpkg.id)

    def test_create_source_package_with_fields(self):
        srcpkg = self.create_source_package(
            name='dummy', version='2', directory='foo/bar',
            dsc_file_name='dummy_2.dsc'
        )
        self.assertEqual(srcpkg.name, 'dummy')
        self.assertEqual(srcpkg.version, '2')
        self.assertEqual(srcpkg.directory, 'foo/bar')
        self.assertEqual(srcpkg.dsc_file_name, 'dummy_2.dsc')

    def test_create_source_package_with_maintainer(self):
        maintainer = {
            'email': 'foo@example.net',
            'name': 'Foo Bar',
        }
        srcpkg = self.create_source_package(maintainer=maintainer)
        self.assertEqual(srcpkg.maintainer.contributor_email.email,
                         maintainer['email'])
        self.assertEqual(srcpkg.maintainer.name, maintainer['name'])

    def test_create_source_package_with_uploaders(self):
        uploaders = ['foo@example.net', 'bar@example.net']
        srcpkg = self.create_source_package(uploaders=uploaders)
        self.assertSetEqual(
            set(uploaders),
            set(srcpkg.uploaders.values_list('contributor_email__email',
                                             flat=True))
        )

    def test_create_source_package_with_architectures(self):
        architectures = ['amd64', 'i386']
        srcpkg = self.create_source_package(architectures=architectures)
        self.assertSetEqual(
            set(architectures),
            set(srcpkg.architectures.values_list('name', flat=True))
        )

    def test_create_source_package_with_binary_packages(self):
        binary_packages = ['pkg1', 'pkg2']
        srcpkg = self.create_source_package(binary_packages=binary_packages)
        self.assertSetEqual(
            set(binary_packages),
            set(srcpkg.binary_packages.values_list('name', flat=True))
        )

    def test_create_source_package_with_repositories(self):
        repositories = ['default', 'other']
        srcpkg = self.create_source_package(repositories=repositories)
        self.assertSetEqual(
            set(repositories),
            set(srcpkg.repository_entries.values_list('repository__shorthand',
                                                      flat=True))
        )

    def test_create_source_package_with_repository(self):
        srcpkg = self.create_source_package(repository='foo')
        srcpkg.repository_entries.get(repository__shorthand='foo')

    def test_create_source_package_with_repository_component_set_to_main(self):
        srcpkg = self.create_source_package(repository='foo')
        for entry in srcpkg.repository_entries.all():
            self.assertEqual(entry.component, 'main')

    def test_create_source_package_repository_default_values(self):
        self.create_source_package(repository='default')

        repository = Repository.objects.get(shorthand='default')
        self.assertListEqual(list(repository.components),
                             ['main', 'contrib', 'non-free'])
        self.assertEqual(repository.suite, 'default')
        self.assertEqual(repository.codename, 'default')
        self.assertTrue(repository.default)

    def test_create_source_package_repository_non_default_repository(self):
        self.create_source_package(repository='foobar')

        repository = Repository.objects.get(shorthand='foobar')
        self.assertFalse(repository.default)


class TempDirsOnSimpleTestCase(TempDirsTests, TestCaseHelpersTests,
                               SimpleTestCase):
    pass


class TempDirsOnTestCase(TempDirsTests, TestCaseHelpersTests,
                         DatabaseMixinTests, TestCase):
    pass


class TempDirsOnTransactionTestCase(TempDirsTests, TestCaseHelpersTests,
                                    DatabaseMixinTests, TransactionTestCase):
    pass
