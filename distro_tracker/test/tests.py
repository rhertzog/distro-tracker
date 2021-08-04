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

"""Tests for test functionalities of Distro Tracker."""

import copy
import gzip
import json
import lzma
import os.path
from unittest import mock

from django.conf import settings

import requests

from distro_tracker.core.models import (
    PackageData,
    PackageName,
    Repository,
    SourcePackage
)
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
        """Test that .setUp() already has the overridden settings."""
        for name in self.get_settings_names():
            self.assertEqual(self._settings_during_setup[name],
                             getattr(settings, name))

    def test_temp_dirs_outside_of_base_path(self):
        """Test that the settings no longer point inside the base path."""
        for name in self.get_settings_names():
            self.assertNotIn(os.path.join(getattr(settings, 'BASE_DIR'), ''),
                             getattr(settings, name))

    def test_temp_dirs_in_data_path(self):
        """Test that the settings point within DISTRO_TRACKER_DATA_PATH."""
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

    def test_get_temporary_directory(self):
        tempdir = self.get_temporary_directory()

        self.assertTrue(os.path.isdir(tempdir))
        self.doCleanups()  # Ensure a cleanup function is added
        self.assertFalse(os.path.isdir(tempdir))

    def test_get_temporary_directory_with_prefix_suffix(self):
        tempdir = self.get_temporary_directory(prefix='foo', suffix='bar')

        dirname = os.path.basename(tempdir)
        self.assertTrue(dirname.startswith('foo'),
                        "%s does not start with foo" % dirname)
        self.assertTrue(dirname.endswith('bar'),
                        "%s does not end with bar" % dirname)


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

    def _call_requests_get(self, url='http://localhost'):
        return requests.get(url)

    def test_set_http_response_stores_answers_to_send(self):
        self.mock_http_request()
        sample_headers = {'foo': 'bar'}
        url = 'http://localhost'

        self.set_http_response(
            url, body='foobar', status_code=222, headers=sample_headers
        )
        response = self._call_requests_get(url)

        self.assertEqual(response.text, 'foobar')
        self.assertEqual(response.status_code, 222)
        self.assertEqual(response.headers["foo"], "bar")

    def test_set_http_response_default_answer_values(self):
        self.mock_http_request()
        self.set_http_response()

        response = self._call_requests_get()
        self.assertEqual(response.text, '')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers, {"Content-Type": "text/plain"})

    def test_set_http_response_json_data(self):
        self.mock_http_request()
        data = {'foo': 'bar'}
        self.set_http_response(json_data=data)

        response = self._call_requests_get()
        self.assertEqual(data, json.loads(response.text))

    def test_set_http_response_json_data_empty_list(self):
        self.mock_http_request()
        data = []
        self.set_http_response(json_data=data)

        response = self._call_requests_get()
        self.assertEqual(data, json.loads(response.text))

    def test_set_http_response_compressed_text_with_gzip(self):
        self.mock_http_request()
        text = 'Hello world!'
        self.set_http_response(body=text, compress_with='gzip')

        response = self._call_requests_get()
        self.assertEqual(gzip.decompress(response.content),
                         bytes(text, 'utf-8'))

    def test_set_http_response_compressed_bytes_with_gzip(self):
        self.mock_http_request()
        content = b'\x01\x02\x03'
        self.set_http_response(body=content, compress_with='gzip')

        response = self._call_requests_get()
        self.assertEqual(gzip.decompress(response.content), content)

    def test_set_http_response_compressed_json_with_gzip(self):
        self.mock_http_request()
        data = {'foo': 'bar'}
        self.set_http_response(json_data=data, compress_with='gzip')

        response = self._call_requests_get()
        json_text = gzip.decompress(response.content).decode('utf-8')
        self.assertEqual(json.loads(json_text), data)

    def test_set_http_response_compressed_text_with_xz(self):
        self.mock_http_request()
        text = 'Hello world!'
        self.set_http_response(body=text, compress_with='xz')

        response = self._call_requests_get()
        self.assertEqual(lzma.decompress(response.content),
                         bytes(text, 'utf-8'))

    def test_set_http_response_compress_with_invalid_method(self):
        self.mock_http_request()
        with self.assertRaises(NotImplementedError):
            self.set_http_response(body='Foobar', compress_with='bad')

    def test_set_http_post_request(self):
        self.mock_http_request()
        url = "http://localhost"
        self.set_http_response(url, method='POST', body=b'Post data')

        # A GET request fails on the POST url
        with self.assertRaises(requests.exceptions.ConnectionError):
            self._call_requests_get()

        response = requests.post(url)
        self.assertEqual(response.content, b'Post data')

    def test_mocked_requests_get_no_answer_set(self):
        self.mock_http_request()

        with self.assertRaises(requests.exceptions.ConnectionError):
            self._call_requests_get()

    def test_mocked_requests_get_response_has_all_attributes(self):
        self.mock_http_request()
        sample_headers = {'foo': 'bar'}
        self.set_http_response(
            body='This is\nthe answer', status_code=201, headers=sample_headers
        )

        response = self._call_requests_get()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.text, 'This is\nthe answer')
        self.assertEqual(response.content, b'This is\nthe answer')
        self.assertEqual(response.encoding, 'ISO-8859-1')
        self.assertEqual(response.ok, True)
        self.assertEqual(bool(response), True)
        self.assertEqual(response.headers['foo'], 'bar')
        self.assertEqual(
            list(response.iter_lines()),
            [b'This is', b'the answer']
        )

    def test_mocked_requests_announces_utf8_when_required(self):
        self.mock_http_request()
        self.set_http_response(body='With Unicode characters: € ±')

        response = self._call_requests_get()

        self.assertEqual(response.encoding, 'utf-8')

    def test_mocked_requests_get_binary_response(self):
        self.mock_http_request()
        binary_content = b'\x01\x02\x03'
        self.set_http_response(body=binary_content)

        response = self._call_requests_get()

        self.assertEqual(response.text, binary_content.decode('ISO-8859-1'))
        self.assertEqual(response.content, binary_content)
        self.assertEqual(response.encoding, 'ISO-8859-1')

    def test_mocked_requests_get_error_response(self):
        self.mock_http_request()
        self.set_http_response(status_code=403)

        response = self._call_requests_get()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.ok, False)
        self.assertEqual(bool(response), False)
        with self.assertRaises(requests.exceptions.HTTPError):
            response.raise_for_status()

    def test_mocked_requests_get_two_different_urls(self):
        """Ensure we get the answer corresponding to the requested URL"""
        self.mock_http_request()
        self.set_http_response(url='http://localhost/1', body='one')
        self.set_http_response(url='http://localhost/2', body='two')

        response = self._call_requests_get('http://localhost/2')
        self.assertEqual(response.text, 'two')

        response = self._call_requests_get('http://localhost/1')
        self.assertEqual(response.text, 'one')

    def test_mocked_requests_get_two_different_urls_with_default_answer(self):
        self.mock_http_request()
        self.set_http_response(body='default answer')

        response = self._call_requests_get('http://localhost/2')
        self.assertEqual(response.text, 'default answer')

        response = self._call_requests_get('http://localhost/1')
        self.assertEqual(response.text, 'default answer')

    def test_mock_http_request_can_set_response(self):
        with mock.patch.object(self, 'set_http_response') as mocked_set:
            self.mock_http_request(body='the answer')
            mocked_set.assert_called_with(body='the answer')


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
        self.assertEqual(srcpkg.dsc_file_name, 'test-package_1.dsc')
        self.assertEqual(srcpkg.directory, 'pool/main/t/test-package')

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

    def test_create_source_package_with_data(self):
        data = {
            'key1': {'sample': 'data'},
            'key2': ['sample', 'data']
        }

        srcpkg = self.create_source_package(data=data)

        pkgdata1 = PackageData.objects.get(package__name=srcpkg.name,
                                           key='key1')
        self.assertEqual(pkgdata1.value, data['key1'])
        pkgdata2 = PackageData.objects.get(package__name=srcpkg.name,
                                           key='key2')
        self.assertEqual(pkgdata2.value, data['key2'])

    def test_add_to_repository_creates_repository(self):
        srcpkg = self.create_source_package()

        self.add_to_repository(srcpkg, 'foobar')
        Repository.objects.get(shorthand='foobar')

    def test_add_to_repository_adds_the_package(self):
        srcpkg = self.create_source_package()

        entry = self.add_to_repository(srcpkg, 'foobar')

        # Retrieve the entry through the source package to ensure it has been
        # well associated and check it's the same than what was returned
        entry2 = srcpkg.repository_entries.get(repository__shorthand='foobar')
        self.assertEqual(entry, entry2)

    def test_remove_from_repository(self):
        srcpkg = self.create_source_package(repository='foobar')
        entry = srcpkg.repository_entries.get(repository__shorthand='foobar')

        result = self.remove_from_repository(srcpkg, 'foobar')

        self.assertDoesNotExist(entry)
        self.assertEqual(result, 1)

    def test_remove_from_repository_when_repository_does_not_exist(self):
        """remove_from_repository() should return 0 when nothing is removed"""
        srcpkg = self.create_source_package(repository='foobar')

        result = self.remove_from_repository(srcpkg, 'unknown')

        self.assertEqual(result, 0)

    def test_add_package_data_with_name(self):
        data1 = {'sample': 'data'}
        data2 = ['sample', 'data']

        self.add_package_data('dpkg', key1=data1, key2=data2)

        pkgdata1 = PackageData.objects.get(package__name='dpkg', key='key1')
        self.assertEqual(pkgdata1.value, data1)
        pkgdata2 = PackageData.objects.get(package__name='dpkg', key='key2')
        self.assertEqual(pkgdata2.value, data2)

    def test_add_package_data_with_PackageName(self):
        pkgname, _ = PackageName.objects.get_or_create(name='sample')
        data = ['foo']

        self.add_package_data(pkgname, key1=data)

        pkgdata = PackageData.objects.get(package=pkgname, key='key1')
        self.assertEqual(pkgdata.value, data)

    def test_create_repository_with_default_values(self):
        repo = self.create_repository()
        self.assertIsInstance(repo, Repository)
        self.assertEqual(repo.name, "Repository sid")
        self.assertEqual(repo.shorthand, "sid")
        self.assertEqual(repo.codename, "sid")
        self.assertEqual(repo.suite, "sid")
        self.assertEqual(repo.uri, "http://localhost/debian")
        self.assertEqual(repo.public_uri, "http://localhost/debian")
        self.assertEqual(repo.components, "main contrib non-free")
        self.assertEqual(repo.default, False)
        self.assertEqual(repo.optional, True)
        self.assertEqual(repo.binary, False)
        self.assertEqual(repo.source, True)
        self.assertEqual(set(["amd64", "i386"]),
                         set([a.name for a in repo.architectures.all()]))

    def test_create_repository_with_custom_values(self):
        repo = self.create_repository(
            codename="bullseye",
            name="Repo name",
            shorthand="shortname",
            uri="http://deb.debian.org/debian",
            suite="stable",
            components="core extra",
            default=True,
            optional=False,
            binary=True,
            source=False,
            architectures=["arm64", "armhf"],
        )
        self.assertEqual(repo.name, "Repo name")
        self.assertEqual(repo.shorthand, "shortname")
        self.assertEqual(repo.codename, "bullseye")
        self.assertEqual(repo.suite, "stable")
        self.assertEqual(repo.uri, "http://deb.debian.org/debian")
        self.assertEqual(repo.public_uri, "http://deb.debian.org/debian")
        self.assertEqual(repo.components, "core extra")
        self.assertEqual(repo.default, True)
        self.assertEqual(repo.optional, False)
        self.assertEqual(repo.binary, True)
        self.assertEqual(repo.source, False)
        self.assertEqual(set(["arm64", "armhf"]),
                         set([a.name for a in repo.architectures.all()]))


class TempDirsOnSimpleTestCase(TempDirsTests, TestCaseHelpersTests,
                               SimpleTestCase):
    pass


class TempDirsOnTestCase(TempDirsTests, TestCaseHelpersTests,
                         DatabaseMixinTests, TestCase):
    pass


class TempDirsOnTransactionTestCase(TempDirsTests, TestCaseHelpersTests,
                                    DatabaseMixinTests, TransactionTestCase):
    pass
