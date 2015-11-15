# -*- coding: utf-8 -*-

# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Distro Tracker test infrastructure.
"""

import shutil
import tempfile
import os
import os.path
import inspect

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
import django.test
from bs4 import BeautifulSoup as soup


class TempDirsMixin(object):
    """
    Diverts all distro-tracker path settings to make them point
    to temporary directories while testing.
    """

    DISTRO_TRACKER_PATH_SETTINGS = {
        'STATIC_ROOT': 'static',
        'MEDIA_ROOT': 'media',
        'DISTRO_TRACKER_CACHE_DIRECTORY': 'cache',
        'DISTRO_TRACKER_KEYRING_DIRECTORY': 'keyring',
        'DISTRO_TRACKER_TEMPLATE_DIRECTORY': 'templates',
        'DISTRO_TRACKER_LOG_DIRECTORY': 'logs',
    }

    def _backup_settings(self, name):
        self._settings_copy[name] = getattr(settings, name)

    def _restore_settings(self):
        for key, value in self._settings_copy.items():
            setattr(settings, key, value)

    def __call__(self, result=None):
        """
        Wrapper around __call__ to perform temporary directories setup.
        This means that user-defined Test Cases aren't required to
        include a call to super().setUp().
        """
        self._settings_copy = {}
        self.addCleanup(self._restore_settings)
        self._backup_settings('DISTRO_TRACKER_DATA_PATH')
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        setattr(settings, 'DISTRO_TRACKER_DATA_PATH', tempdir)
        for name, dirname in self.DISTRO_TRACKER_PATH_SETTINGS.items():
            self._backup_settings(name)
            dirname = os.path.join(tempdir, dirname)
            setattr(settings, name, dirname)
            os.mkdir(dirname)
        return super(TempDirsMixin, self).__call__(result)


class TestCaseHelpersMixin(object):
    """
    Helpers method injected into distro_tracker's *TestCase objects.
    """

    def get_test_data_path(self, name):
        """
        Returns an absolute path name of file within the tests-data
        subdirectory in the calling TestCase.
        """
        return os.path.join(os.path.dirname(inspect.getabsfile(self.__class__)),
                            'tests-data', name)

    def import_key_into_keyring(self, filename):
        """
        Imports a key from an ascii armored file located in tests-data/keys/
        into Distro Tracker's keyrings/.
        """
        import gpgme

        old = os.environ.get('GNUPGHOME', None)
        os.environ['GNUPGHOME'] = settings.DISTRO_TRACKER_KEYRING_DIRECTORY
        ctx = gpgme.Context()

        file_path = self.get_test_data_path('keys/' + filename)
        with open(file_path, 'rb') as key_file:
            ctx.import_(key_file)

        if old:
            os.environ['GNUPGHOME'] = old


class SimpleTestCase(TempDirsMixin, TestCaseHelpersMixin,
                     django.test.SimpleTestCase):
    pass


class TestCase(TempDirsMixin, TestCaseHelpersMixin,
               django.test.TestCase):
    pass


class TransactionTestCase(TempDirsMixin, TestCaseHelpersMixin,
                          django.test.TransactionTestCase):
    pass


class LiveServerTestCase(TempDirsMixin, TestCaseHelpersMixin,
                         StaticLiveServerTestCase):
    pass


class TemplateTestsMixin(object):
    """Helper methods to tests templates"""

    @staticmethod
    def html_contains_link(text, link):
        html = soup(text, 'lxml')
        for a_tag in html.findAll('a', {'href': True}):
            if a_tag['href'] == link:
                return True
        return False

    def assertLinkIsInResponse(self, response, link):
        self.assertTrue(self.html_contains_link(response.content, link))

    def assertLinkIsNotInResponse(self, response, link):
        self.assertFalse(self.html_contains_link(response.content, link))
