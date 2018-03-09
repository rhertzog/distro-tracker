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

from distro_tracker.test import SimpleTestCase, TestCase, TransactionTestCase
from distro_tracker.test import TempDirsMixin
from distro_tracker.core.models import PackageName
from django.conf import settings
import copy
import os.path

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


class DatabaseAssertionsMixinTests(object):
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


class TempDirsOnSimpleTestCase(TempDirsTests, TestCaseHelpersTests,
                               SimpleTestCase):
    pass


class TempDirsOnTestCase(TempDirsTests, TestCaseHelpersTests,
                         DatabaseAssertionsMixinTests, TestCase):
    pass


class TempDirsOnTransactionTestCase(TempDirsTests, TestCaseHelpersTests,
                                    DatabaseAssertionsMixinTests,
                                    TransactionTestCase):
    pass
