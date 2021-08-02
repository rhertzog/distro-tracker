# -*- coding: utf-8 -*-

# Copyright 2014-2021 The Distro Tracker Developers
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

import gzip
import inspect
import json
import lzma
import os
import os.path
import re
import shutil
import tempfile

from bs4 import BeautifulSoup as soup

import django.test
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test.signals import setting_changed

import responses

from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import (
    Architecture,
    BinaryPackageName,
    ContributorName,
    PackageData,
    PackageName,
    Repository,
    SourcePackage,
    SourcePackageName,
)
from distro_tracker.core.utils.packages import package_hashdir

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
    Helpers method injected into distro_tracker's ``*TestCase`` objects.
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

    def get_temporary_directory(self, prefix=None, suffix=None):
        tempdir = tempfile.mkdtemp(prefix=prefix, suffix=suffix)
        self.addCleanup(shutil.rmtree, tempdir, ignore_errors=True)

        return tempdir

    def mock_http_request(self, **kwargs):
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

        if kwargs:
            self.set_http_get_response(**kwargs)

    @staticmethod
    def compress(data, compression='gzip'):
        if compression == 'gzip':
            return gzip.compress(data)
        elif compression == 'xz':
            return lzma.compress(data)
        else:
            raise NotImplementedError(
                'compress() does not support {} as '
                'compression method'.format(compression))

    def set_http_get_response(self, url=None, body=None, text='', content=None,
                              status_code=200, headers=None, json_data=None,
                              compress_with=None):
        # Default URL is the catch-all pattern
        if url is None:
            url = re.compile(".*")

        if headers is None:
            headers = {}

        if compress_with:
            if json_data is not None:
                body = self.compress(
                    json.dumps(json_data).encode('utf-8'),
                    compress_with,
                )
                # Don't forward parameter
                json_data = None
            elif body is not None:
                body = self.compress(body, compress_with)
            elif content is not None:
                body = self.compress(content, compress_with)
            elif text is not None:
                body = self.compress(text.encode('utf-8'), compress_with)
        else:
            if content is not None:
                body = content
            elif text is not None:
                body = text

        responses.remove(responses.GET, url)
        responses.add(
            method=responses.GET,
            url=url,
            body=body,
            json=json_data,
            status=status_code,
            headers=headers,
        )

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


class DatabaseMixin(object):
    """
    Database-related assertions injected into distro_tracker's ``*TestCase``
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

    def create_source_package(self, **kwargs):
        """
        Creates a source package and any related object requested through the
        keyword arguments. The following arguments are supported:
        - name
        - version
        - directory
        - dsc_file_name
        - maintainer (dict with 'name' and 'email')
        - uploaders (list of emails)
        - architectures (list of architectures)
        - binary_packages (list of package names)
        - repository (shorthand of a repository)
        - repositories (list of repositories' shorthand)
        - data (dict used to generate associated PackageData)

        If the shorthand of the requested repository is 'default', then
        its default field will be set to True.

        :return: the created source package
        :rtype: :class:`~distro_tracker.core.models.SourcePackage`
        """
        name = kwargs.get('name', 'test-package')
        version = kwargs.get('version', '1')

        fields = {}
        fields['source_package_name'] = \
            SourcePackageName.objects.get_or_create(name=name)[0]
        fields['version'] = version
        fields['dsc_file_name'] = kwargs.get('dsc_file_name',
                                             '%s_%s.dsc' % (name, version))
        fields['directory'] = kwargs.get(
            'directory', 'pool/main/%s/%s' % (package_hashdir(name), name))

        if 'maintainer' in kwargs:
            maintainer = kwargs['maintainer']
            maintainer_email = UserEmail.objects.get_or_create(
                email=maintainer['email'])[0]
            fields['maintainer'] = ContributorName.objects.get_or_create(
                contributor_email=maintainer_email,
                name=maintainer.get('name', ''))[0]

        srcpkg = SourcePackage.objects.create(**fields)

        for architecture in kwargs.get('architectures', []):
            srcpkg.architectures.add(
                Architecture.objects.get_or_create(name=architecture)[0])

        for uploader in kwargs.get('uploaders', []):
            contributor = ContributorName.objects.get_or_create(
                contributor_email=UserEmail.objects.get_or_create(
                    email=uploader)[0])[0]
            srcpkg.uploaders.add(contributor)

        for binary in kwargs.get('binary_packages', []):
            srcpkg.binary_packages.add(
                BinaryPackageName.objects.get_or_create(name=binary)[0])

        if 'repository' in kwargs:
            kwargs.setdefault('repositories', [kwargs['repository']])
        for repo_shorthand in kwargs.get('repositories', []):
            self.add_to_repository(srcpkg, repo_shorthand)

        if 'data' in kwargs:
            self.add_package_data(srcpkg.source_package_name, **kwargs['data'])

        srcpkg.save()
        return srcpkg

    def add_to_repository(self, srcpkg, shorthand='default'):
        """
        Add a source package to a repository. Creates the repository if it
        doesn't exist.

        If the shorthand of the requested repository is 'default', then
        its default field will be set to True.

        :param srcpkg: the source package to add to the repository
        :type srcpkg: :class:`~distro_tracker.core.models.SourcePackage`
        :param str shorthand: the shorthand of the repository

        :return: the repository entry that has been created
        :rtype:
            :class:`~distro_tracker.core.models.SourcePackageRepositoryEntry`
        """
        repository, _ = Repository.objects.get_or_create(
            shorthand=shorthand,
            defaults={
                'name': 'Test repository %s' % shorthand,
                'uri': 'http://localhost/debian',
                'suite': shorthand,
                'codename': shorthand,
                'components': ['main', 'contrib', 'non-free'],
                'default': True if shorthand == 'default' else False,
            }
        )
        return srcpkg.repository_entries.create(repository=repository,
                                                component='main')

    def remove_from_repository(self, srcpkg, shorthand='default'):
        """
        Remove a source package from a repository.

        :param srcpkg: the source package to add to the repository
        :type srcpkg: :class:`~distro_tracker.core.models.SourcePackage`
        :param str shorthand: the shorthand of the repository
        """
        return srcpkg.repository_entries.filter(
            repository__shorthand=shorthand).delete()[0]

    def add_package_data(self, pkgname, **kwargs):
        """
        Creates PackageData objects associated to the package indicated
        in pkgname. Each named parameter results in PackageData instance
        with the `key` being the name of the parameter and the `value`
        being the value of the named parameter.

        :param pkgname: the name of the package to which we want to associate
            data
        :type pkgname: `str` or :class:`~distro_tracker.core.models.PackageName`
        """
        if not isinstance(pkgname, PackageName):
            pkgname, _ = PackageName.objects.get_or_create(name=str(pkgname))
        for key, value in kwargs.items():
            PackageData.objects.create(package=pkgname, key=key, value=value)


class SimpleTestCase(TempDirsMixin, TestCaseHelpersMixin,
                     django.test.SimpleTestCase):
    pass


class TestCase(TempDirsMixin, TestCaseHelpersMixin, DatabaseMixin,
               django.test.TestCase):
    pass


@django.test.tag('transaction')
class TransactionTestCase(TempDirsMixin, TestCaseHelpersMixin,
                          DatabaseMixin, django.test.TransactionTestCase):
    pass


class LiveServerTestCase(TempDirsMixin, TestCaseHelpersMixin,
                         DatabaseMixin, StaticLiveServerTestCase):
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
