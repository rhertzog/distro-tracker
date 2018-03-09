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
from django.test.signals import setting_changed
from bs4 import BeautifulSoup as soup
from django_email_accounts.models import User


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
        'DISTRO_TRACKER_MAILDIR_DIRECTORY': 'maildir',
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
        tempdir = tempfile.mkdtemp(prefix='distro-tracker-tests-')
        self.addCleanup(shutil.rmtree, tempdir, ignore_errors=True)
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

    def add_test_template_dir(self, name='tests-templates'):
        template_dir = self.get_test_data_path(name)
        settings.TEMPLATES[0]['DIRS'].append(template_dir)
        setting_changed.send(sender=self.__class__, setting='TEMPLATES',
                             value=settings.TEMPLATES, enter=True)

        def cleanup_test_template_dir():
            settings.TEMPLATES[0]['DIRS'].remove(template_dir)
            setting_changed.send(sender=self.__class__, setting='TEMPLATES',
                                 value=settings.TEMPLATES, enter=False)

        self.addCleanup(cleanup_test_template_dir)

    def import_key_into_keyring(self, filename):
        """
        Imports a key from an ascii armored file located in tests-data/keys/
        into Distro Tracker's keyrings/.
        """
        import gpg

        old = os.environ.get('GNUPGHOME', None)
        os.environ['GNUPGHOME'] = settings.DISTRO_TRACKER_KEYRING_DIRECTORY

        file_path = self.get_test_data_path('keys/' + filename)
        keydata = gpg.Data()
        keydata.new_from_file(file_path)

        with gpg.Context() as ctx:
            ctx.op_import(keydata)

        if old:
            os.environ['GNUPGHOME'] = old


class DatabaseAssertionsMixin(object):
    """
    Database-related assertions injected into distro_tracker's *TestCase
    objects.
    """

    def assertDoesNotExist(self, obj):
        with self.assertRaises(obj.__class__.DoesNotExist):
            obj.__class__.objects.get(pk=obj.id)

    def assertDoesExist(self, obj):
        try:
            self.assertIsNotNone(obj.__class__.objects.get(pk=obj.id))
        except obj.__class__.DoesNotExist as error:
            raise AssertionError(error)


class SimpleTestCase(TempDirsMixin, TestCaseHelpersMixin,
                     django.test.SimpleTestCase):
    pass


class TestCase(TempDirsMixin, TestCaseHelpersMixin, DatabaseAssertionsMixin,
               django.test.TestCase):
    pass


class TransactionTestCase(TempDirsMixin, TestCaseHelpersMixin,
                          DatabaseAssertionsMixin,
                          django.test.TransactionTestCase):
    pass


class LiveServerTestCase(TempDirsMixin, TestCaseHelpersMixin,
                         DatabaseAssertionsMixin,
                         StaticLiveServerTestCase):
    pass


class TemplateTestsMixin(object):
    """Helper methods to tests templates"""

    @staticmethod
    def html_contains_link(text, link):
        html = soup(text, 'html.parser')
        for a_tag in html.findAll('a', {'href': True}):
            if a_tag['href'] == link:
                return True
        return False

    def assertLinkIsInResponse(self, response, link):
        self.assertTrue(self.html_contains_link(response.content, link))

    def assertLinkIsNotInResponse(self, response, link):
        self.assertFalse(self.html_contains_link(response.content, link))


class UserAuthMixin(object):
    """
    Helpers methods to manage user authentication.
    One may define additional USERS before call self.setup_users()
    in self.setUp()
    """
    USERS = {
        'john': {},
    }

    def setup_users(self, login=False):
        """
        Creates users defined in self.USERS and use the 'login' parameter as
        follows:
        * If False: no user login
        * If True: login with the only user defined
        * If a particular username: login with the user who owns the username
        """
        self.users = {}
        for username in self.USERS:
            user_data = self._get_user_data(username)
            self.users[username] = User.objects.create_user(**user_data)
        if login:
            username = None if login is True else login
            self.login(username)

    def login(self, username=None):
        """
        Login with the user that owns the 'username' or with the only available
        user in self.users. If multiple users are available, you must specify
        the username or you will trigger a ValueError exception.
        """
        if not username:
            if len(self.users) > 1:
                raise ValueError("multiple users but username not specified")
            username = list(self.users.keys())[0]
        user_data = self._get_user_data(username)
        self.client.login(
            username=user_data['main_email'],
            password=user_data['password'],
        )
        self.current_user = self.users[username]
        return self.current_user

    def get_user(self, username=None):
        if not username:
            return self.current_user
        return self.users[username]

    def _get_user_data(self, username):
        user_data = self.USERS[username].copy()
        user_data.setdefault('main_email', '{}@example.com'.format(username))
        user_data.setdefault('password', '{}password'.format(username))
        return user_data
