# -*- coding: utf-8 -*-

# Copyright 2013-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core utils.
"""
import datetime
import io
import os
import tempfile
import time
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from functools import partial
from unittest import mock

from debian import deb822

from django.core import mail
from django.http.response import HttpResponseRedirectBase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.http import http_date

from requests.exceptions import HTTPError

from distro_tracker.core.models import PackageName, Repository
from distro_tracker.core.utils import (
    PrettyPrintList,
    SpaceDelimitedTextField,
    message_from_bytes,
    now,
    verify_signature,
    verp
)
from distro_tracker.core.utils.compression import (
    get_uncompressed_stream,
    guess_compression_method
)
from distro_tracker.core.utils.email_messages import (
    CustomEmailMessage,
    decode_header,
    extract_email_address_from_header,
    name_and_address_from_string,
    names_and_addresses_from_string,
    unfold_header
)
from distro_tracker.core.utils.http import (
    HttpCache,
    get_resource_content,
    get_resource_text,
    safe_redirect
)
from distro_tracker.core.utils.linkify import (
    LinkifyCVELinks,
    LinkifyDebianBugLinks,
    LinkifyHttpLinks,
    LinkifyUbuntuBugLinks,
    linkify
)
from distro_tracker.core.utils.misc import (
    call_methods_with_prefix,
    get_data_checksum,
)
from distro_tracker.core.utils.packages import (
    AptCache,
    extract_dsc_file_name,
    extract_vcs_information,
    html_package_list,
    package_hashdir,
    package_url
)
from distro_tracker.test import SimpleTestCase, TestCase


class VerpModuleTest(SimpleTestCase):
    """
    Tests for the ``distro_tracker.core.utils.verp`` module.
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
            verp.decode(
                'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com'),
            ('bounce@dom.com', 'user+!%-:@[]+@other.com'))

    def test_decode_lowercase_code(self):
        """Encoding of special characters with lowercase should work"""
        self.assertEqual(
            verp.decode(
                'bounce-user+2b+2d+3a=other.com@dom.com'),
            ('bounce@dom.com', 'user+-:@other.com'))

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
    Tests the ``distro_tracker.core.utils.message_from_bytes`` function.
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
        return mock.create_autospec(smtplib.SMTP, return_value={})

    def test_as_string_returns_bytes(self):
        """
        Tests that the as_string message returns bytes.
        """
        message = message_from_bytes(self.message_bytes)

        self.assertEqual(self.message_bytes, message.as_string())
        self.assertTrue(isinstance(message.as_string(), bytes))

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
            mock.ANY)
        self.assertEqual(
            mock_connection.sendmail.call_args[0][2].replace(b"\r\n", b"\n"),
            message.as_string())


class EmailUtilsTest(SimpleTestCase):
    def test_name_and_address_from_string(self):
        """
        Tests retrieving a name and address from a string which contains
        unquoted commas.
        """
        self.assertDictEqual(
            name_and_address_from_string(
                'John H. Robinson, IV <jaqque@debian.org>'),
            {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'}
        )

        self.assertDictEqual(
            name_and_address_from_string('email@domain.com'),
            {'name': '', 'email': 'email@domain.com'}
        )

        self.assertDictEqual(
            name_and_address_from_string('Name <email@domain.com>'),
            {'name': 'Name', 'email': 'email@domain.com'}
        )

        self.assertIsNone(name_and_address_from_string(''))

    def test_names_and_addresses_from_string(self):
        """
        Tests extracting names and emails from a string containing a list of
        them.
        """
        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'Name <email@domain.com>'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': 'Name', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'email@domain.com'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': '', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(names_and_addresses_from_string(''), [])

    def test_unfold_header(self):
        """
        Ensure unfold_header() respect the unfolding rules.
        """
        test_values = {
            'a\n b': 'a b',
            'a\r\n b': 'a b',
            'a\n\tb': 'a\tb',
            'a\r\n\tb\n c\n\td': 'a\tb c\td',
            'a\n\t bc\n  d': 'a\t bc  d',
        }
        for folded, unfolded in test_values.items():
            self.assertEqual(unfold_header(folded), unfolded)

    def test_unfold_header_with_none_value(self):
        self.assertIsNone(unfold_header(None))

    def test_extract_email_address_from_header_with_angle_brackets(self):
        email = extract_email_address_from_header('Real Name <foo@domain.com>')
        self.assertEqual(email, 'foo@domain.com')

    def test_extract_email_address_from_header_with_parenthesis(self):
        email = extract_email_address_from_header('foo@domain.com (Real Name)')
        self.assertEqual(email, 'foo@domain.com')

    def test_extract_email_address_from_header_with_header_object(self):
        """
        Ensure the function can deal with an Header object representing
        the value of the field.
        """
        header = Header("Raphaël Hertzog <foo@domain.com>")
        email = extract_email_address_from_header(header)
        self.assertEqual(email, 'foo@domain.com')


class CustomEmailMessageTest(TestCase):
    """
    Tests the ``CustomEmailMessage`` class.
    """
    def create_multipart(self):
        """
        Helper method creates a multipart message.
        """
        msg = MIMEMultipart()
        msg.attach(self.prepare_part(b'data'))
        return msg

    def prepare_part(self, data):
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(data)
        encoders.encode_base64(part)
        return part

    def test_sent_message_same_as_original(self):
        """
        Tests that an ``email.message.Message`` instance sent by using the
        ``CustomEmailMessage`` class is the same as the original message.
        """
        msg = self.create_multipart()
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertEqual(msg.as_string(), mail.outbox[0].message().as_string())

    def test_attachment_included(self):
        """
        Tests that an attachment included in the ``CustomEmailMessage``
        instance is sent with the rest of the message.
        """
        msg = self.create_multipart()
        attachment = self.prepare_part(b'new_data')
        msg.attach(attachment)
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertIn(attachment, mail.outbox[0].message().get_payload())


class PrettyPrintListTest(SimpleTestCase):
    """
    Tests for the PrettyPrintList class.
    """
    def test_string_output(self):
        """
        Tests the output of a PrettyPrintList.
        """
        pp_list = PrettyPrintList(['a', 'b', 'abe', 'q'])
        self.assertEqual(str(pp_list), 'a b abe q')

        pp_list = PrettyPrintList()
        self.assertEqual(str(pp_list), '')

        pp_list = PrettyPrintList([0, 'a', 1])
        self.assertEqual(str(pp_list), '0 a 1')

    def test_list_methods_accessible(self):
        """
        Tests that list methods are accessible to the PrettyPrintList object.
        """
        pp_list = PrettyPrintList()
        pp_list.append('a')
        self.assertEqual(str(pp_list), 'a')

        pp_list.extend(['q', 'w'])
        self.assertEqual(str(pp_list), 'a q w')

        pp_list.pop()
        self.assertEqual(str(pp_list), 'a q')

        # len works?
        self.assertEqual(len(pp_list), 2)
        # Iterable?
        self.assertSequenceEqual(pp_list, ['a', 'q'])
        # Indexable?
        self.assertEqual(pp_list[0], 'a')
        # Comparable?
        pp_list2 = PrettyPrintList(['a', 'q'])
        self.assertTrue(pp_list == pp_list2)
        pp_list3 = PrettyPrintList()
        self.assertFalse(pp_list == pp_list3)
        # Comparable to plain lists?
        self.assertTrue(pp_list == ['a', 'q'])
        self.assertFalse(pp_list == ['a'])


class SpaceDelimitedTextFieldTest(SimpleTestCase):
    """
    Tests the SpaceDelimitedTextField class.
    """
    def setUp(self):
        self.field = SpaceDelimitedTextField()

    def test_list_to_field(self):
        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList(['a', 'b', 3])),
            'a b 3'
        )

        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList()),
            ''
        )

    def test_field_to_list(self):
        self.assertEqual(
            self.field.to_python('a b 3'),
            PrettyPrintList(['a', 'b', '3'])
        )

        self.assertEqual(
            self.field.to_python(''),
            PrettyPrintList()
        )

    def test_sane_inverse(self):
        pp_list = PrettyPrintList(['a', 'b', 'c'])
        self.assertEqual(
            self.field.to_python(self.field.get_db_prep_value(pp_list)),
            pp_list
        )


class PackageUtilsTests(SimpleTestCase):
    """
    Tests the distro_tracker.core.utils.packages utlity functions.
    """
    def test_get_vcs(self):
        browser_url = 'http://other-url.com'
        vcs_url = 'git://url.com'
        d = {
            'Vcs-Git': vcs_url,
            'Vcs-Browser': browser_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'browser': browser_url,
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Browser not found
        d = {
            'Vcs-Git': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # A VCS type longer than three letters
        d = {
            'Vcs-Darcs': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'darcs',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Git with branch info
        d = {
            'Vcs-Git': vcs_url + ' -b some-branch'
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'url': vcs_url,
                'branch': 'some-branch',
            },
            extract_vcs_information(d)
        )

        # Empty dict
        self.assertDictEqual({}, extract_vcs_information({}))
        # No vcs information in the dict
        self.assertDictEqual({}, extract_vcs_information({
            'stuff': 'that does not',
            'have': 'anything to do',
            'with': 'vcs'
        }))

    def test_package_hash_dir(self):
        self.assertEqual(package_hashdir("dpkg"), "d")
        self.assertEqual(package_hashdir("lua"), "l")
        self.assertEqual(package_hashdir("lib"), "lib")
        self.assertEqual(package_hashdir("libc6"), "libc")
        self.assertEqual(package_hashdir("lib+fancy"), "lib+")
        self.assertEqual(package_hashdir(""), "")
        self.assertEqual(package_hashdir(None), None)

    def test_package_url_with_string(self):
        self.assertEqual(
            package_url('dpkg'),
            reverse('dtracker-package-page',
                    kwargs={'package_name': 'dpkg'})
        )

    def test_package_url_with_package_name_model(self):
        obj = PackageName(name='dpkg')
        self.assertEqual(
            package_url(obj),
            reverse('dtracker-package-page',
                    kwargs={'package_name': obj.name})
        )

    def test_package_url_with_none(self):
        self.assertEqual(package_url(None), None)

    def test_html_package_list(self):
        """Tests the output of html_package_list function"""

        list_of_packages = [
            'dummy-package',
            'other-dummy-package',
            'last-dummy-package/amd64',
        ]

        output = html_package_list(list_of_packages)

        first_url = '<a href="%s">%s</a>' % (
            package_url('dummy-package'),
            'dummy-package',
        )

        second_url = '<a href="%s">%s</a>' % (
            package_url('other-dummy-package'),
            'other-dummy-package',
        )

        third_url = '<a href="%s">%s</a>/amd64' % (
            package_url('last-dummy-package'),
            'last-dummy-package',
        )

        self.assertEqual(
            output,
            "%s, %s, %s" % (
                first_url,
                second_url,
                third_url,
            ),
        )

    def test_extract_dsc_file_name(self):

        stanza = deb822.Sources(
            """Package: curl
Binary: curl
Version: 7.26.0
Maintainer: Maintainer <maintainer@domain.com>
Architecture: any
Standards-Version: 3.9.3
Format: 3.0 (quilt)
Files:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Checksums-Sha1:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Checksums-Sha256:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Directory: pool/updates/main/c/curl
Priority: source
Section: libs
""".format(
    '602b2a11624744e2e92353f5e76ad7e6',  # noqa
    '3fa4d5236f2a36ca5c3af6715e837691',  # noqa
    '2972826d5b1ebadace83f236e946b33f',  # noqa
    '50fd8c0de138e80903443927365565151291338c',  # noqa
    '66e1fd0312f62374b96fe02e644f66202fd6324b',  # noqa
    'a0f16b381d3ac3e02de307dced481eaf01b3ead1',  # noqa
    'daf4c6c8ad485f98cc6ad684b5de30d7d07e45e521a1a6caf148406f7c9993cd',  # noqa
    '79ccce9edb8aee17d20ad4d75e1f83a789f8c2e71e68f468e1bf8abf8933193f',  # noqa
    '335bf9f847e68df71dc0b9bd14863c6a8951198af3ac19fc67b8817835fd0e17',  # noqa
))  # noqa

        self.assertEqual(
            'dummy-package_7.26.0.dsc',
            extract_dsc_file_name(stanza)
        )

        # No input given
        self.assertIsNone(extract_dsc_file_name({}))
        # No files entry...
        self.assertIsNone(extract_dsc_file_name({
            'package': 'name',
            'version': 'version'
        }))


class HttpCacheTest(SimpleTestCase):
    """Tests for the HttpCache utility"""

    #
    # Tests constructors
    #
    def setUp(self):
        self.cache_directory = self.get_temporary_directory(suffix='test-cache')
        self.response_content = 'Simple response'.encode('utf-8')
        self.url = 'http://some.url.com'
        self.cache = HttpCache(self.cache_directory)

    #
    # Tests helper functions, to avoid code redundancy
    #
    def get_mock_of_http_cache(self, get_content=b"Some content"):
        """
        Common setup function for the get_resource function tests
        to avoid code redundancy.
        """
        mock_cache = mock.create_autospec(HttpCache)
        self.response_content = get_content
        mock_cache.get_content.return_value = self.response_content

        return mock_cache

    #
    # Proper tests - Headers functionalities
    #
    def test_parse_cache_control_header(self):
        """
        Tests the utility function for parsing a Cache-Control header into a
        dict.
        """
        from distro_tracker.core.utils.http import parse_cache_control_header
        header = 'must-revalidate, max-age=3600'
        d = parse_cache_control_header(header)
        self.assertIn('must-revalidate', d)
        self.assertIn('max-age', d)
        self.assertEqual(d['max-age'], '3600')

        header = 'max-age=0, private'
        d = parse_cache_control_header(header)
        self.assertIn('private', d)
        self.assertIn('max-age', d)
        self.assertEqual(d['max-age'], '0')

    def test_url_to_cache_path_simple_url_without_args(self):
        path = self.cache.url_to_cache_path('http://localhost/foo/bar.txt')
        self.assertEqual(path, 'localhost/foo/bar.txt')

        path = self.cache.url_to_cache_path('https://localhost/foo/bar.txt')
        self.assertEqual(path, 'localhost/foo/bar.txt')

    def test_url_to_cache_path_normalizes_path(self):
        path = self.cache.url_to_cache_path('https://localhost//foo///bar.txt?')
        self.assertEqual(path, 'localhost/foo/bar.txt')

        path = self.cache.url_to_cache_path('https://localhost/foo//')
        self.assertEqual(path, 'localhost/foo')

    def test_url_to_cache_path_url_with_args(self):
        path = self.cache.url_to_cache_path('http://localhost/foo?foobar')
        self.assertEqual(path,
                         'localhost/foo?/3858f62230ac3c915f300c664312c63f')

        # Ensure we split only on first question mark
        path = self.cache.url_to_cache_path('http://localhost/foo?foo?bar')
        self.assertEqual(path,
                         'localhost/foo?/1a361f6f00e5f0864ce353da93da2c08')

    def test_url_to_cache_path_with_conflicting_directory(self):
        """
        Ensure we can store a cache entry even with a conflicting directory.

        When an already fetched URL created a directory in the place where
        we want to store something, we consider that we have a directory
        index and we store it in the special path ending '<path>?/index'.
        This is the same directory structure as the URL with GET arguments
        except that it doesn't use any md5sum and thus avoids any conflict
        with that case.
        """
        os.makedirs(os.path.join(self.cache_directory, 'localhost/foo'))
        path = self.cache.url_to_cache_path('http://localhost/foo')
        self.assertEqual(path, 'localhost/foo?/index')

    def test_url_to_cache_path_can_be_overriden(self):
        mock_url_to_cache_path = mock.MagicMock()
        mock_url_to_cache_path.return_value = mock.sentinel.cache_path

        cache = HttpCache(self.cache_directory,
                          url_to_cache_path=mock_url_to_cache_path)
        answer = cache.url_to_cache_path('http://localhost/foo')

        self.assertEqual(answer, mock.sentinel.cache_path)
        mock_url_to_cache_path.assert_called_with('http://localhost/foo')

    def test_update_clears_conflicting_files(self):
        """
        Ensure that a file is replaced by a directory when needed.

        When a previous resource created a file that now needs to be
        a directory, we want the file to leave its place for the directory.
        The file is kept as a directory index.
        """
        conflicting_path = os.path.join(self.cache_directory, 'localhost/foo')
        new_path = os.path.join(self.cache_directory, 'localhost/foo?/index')
        # Fetch a first file
        self.mock_http_request(text='Some content')
        self.cache.update('http://localhost/foo')
        self.assertTrue(os.path.isfile(conflicting_path))
        self.assertFalse(os.path.isdir(conflicting_path))
        self.assertFalse(os.path.isfile(new_path))
        # Fetch a resource that conflicts with the previous file
        self.cache.update('http://localhost/foo/bar')
        self.assertTrue(os.path.isdir(conflicting_path))
        self.assertFalse(os.path.isfile(conflicting_path))
        self.assertTrue(os.path.isfile(new_path))
        self.assertTrue(os.path.isfile(new_path + '?headers'))

    def test_update_cache_new_item(self):
        """
        Tests the simple case of updating the cache with a new URL's response.
        """
        headers = {
            'Connection': 'Keep-Alive',
            'Content-Type': 'text/plain',
        }
        self.mock_http_request(text='Some content', headers=headers)
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        # The URL cannot be found in the cache at this point
        self.assertFalse(url in cache)

        response, updated = cache.update(url)

        # The returned response is correct
        self.assertEqual(b'Some content', response.content)
        self.assertEqual(200, response.status_code)
        # The return value indicates the cache has been updated
        self.assertTrue(updated)
        # The URL is now found in the cache
        self.assertTrue(url in cache)
        # The content is accessible through the cache
        self.assertEqual(b'Some content', cache.get_content(url))
        # The returned headers are accessible through the cache
        cached_headers = cache.get_headers(url)
        for key, value in headers.items():
            self.assertIn(key, cached_headers)
            self.assertEqual(value, cached_headers[key])

    def test_cache_not_expired(self):
        """
        Tests that the cache knows a response is not expired based on its
        Cache-Control header.
        """
        self.mock_http_request(headers={
            'Cache-Control': 'must-revalidate, max-age=3600',
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertTrue(url in cache)
        self.assertFalse(cache.is_expired(url))

    def test_cache_expired(self):
        """
        Tests that the cache knows when an entry with a stale Cache-Control
        header is expired.
        """
        self.mock_http_request(headers={
            'Cache-Control': 'must-revalidate, max-age=0',
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertTrue(url in cache)
        self.assertTrue(cache.is_expired(url))

    def test_cache_conditional_get_last_modified(self):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with a Last-Modified header.
        """
        last_modified = http_date(time.time())
        self.mock_http_request(headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.set_http_get_response(text='', status_code=304)
        # Run the update again
        response, updated = cache.update(url)

        self.assertFalse(updated)
        self._mocked_requests.get.assert_called_with(
            url, verify=mock.ANY, allow_redirects=True,
            headers={'If-Modified-Since': last_modified})
        # The actual server's response is returned
        self.assertEqual(response.status_code, 304)

    def test_cache_conditional_get_last_modified_expired(self):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with a Last-Modified header, which has
        since expired.
        """
        last_modified = http_date(time.time() - 3600)
        self.mock_http_request(headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Set a new Last-Modified and content value
        new_last_modified = http_date(time.time())
        self.mock_http_request(text='Response', headers={
            'Last-Modified': new_last_modified
        })

        # Run the update again
        response, updated = cache.update(url)

        self.assertTrue(updated)
        self.assertEqual(200, response.status_code)
        # The new content is found in the cache
        self.assertEqual(b'Response', cache.get_content(url))
        # The new Last-Modified is found in the headers cache
        self.assertEqual(
            new_last_modified,
            cache.get_headers(url)['Last-Modified']
        )

    def test_cache_expires_header(self):
        """
        Tests that the cache knows that a cached response is not expired based
        on its Expires header.
        """
        expires = http_date(time.time() + 3600)
        self.mock_http_request(headers={
            'Expires': expires
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertFalse(cache.is_expired(url))

    def test_cache_expires_header_expired(self):
        """
        Tests that the cache knows that a cached response is expired based
        on its Expires header.
        """
        expires = http_date(time.time() - 3600)
        self.mock_http_request(headers={
            'Expires': expires
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.assertTrue(cache.is_expired(url))

    #
    # Proper tests - Caching behaviour
    #
    def test_cache_remove_url(self):
        """
        Tests removing a cached response.
        """
        self.mock_http_request(text='Some content')
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Sanity check - the url is cached
        self.assertTrue(url in cache)

        cache.remove(url)

        self.assertFalse(url in cache)

    #
    # Proper tests - ETags
    #
    def test_conditional_get_etag(self):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with an ETag header
        """
        etag = '"466010a-11bf9-4e17efa8afb81"'
        self.mock_http_request(headers={
            'ETag': etag,
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.mock_http_request(status_code=304)
        # Run the update again
        response, updated = cache.update(url)

        self.assertFalse(updated)
        self._mocked_requests.get.assert_called_with(
            url, verify=mock.ANY, allow_redirects=True,
            headers={'If-None-Match': etag, })
        # The actual server's response is returned
        self.assertEqual(response.status_code, 304)

    def test_conditional_get_etag_expired(self):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with an ETag header, which has since
        expired.
        """
        etag = '"466010a-11bf9-4e17efa8afb81"'
        self.mock_http_request(headers={
            'ETag': etag,
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Set a new ETag and content value
        new_etag = '"57ngfhty11bf9-9t831116kn1qw1'
        self.mock_http_request(text='Response', headers={
            'ETag': new_etag
        })

        # Run the update again
        response, updated = cache.update(url)

        self.assertTrue(updated)
        self.assertEqual(200, response.status_code)
        # The new content is found in the cache
        self.assertEqual(b'Response', cache.get_content(url))
        # The new Last-Modified is found in the headers cache
        self.assertEqual(
            new_etag,
            cache.get_headers(url)['ETag']
        )

    def test_conditional_force_unconditional_get(self):
        """
        Tests that the users can force the cache to perform an unconditional
        GET when updating a cached resource.
        """
        last_modified = http_date(time.time())
        self.mock_http_request(headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        # Run the update again
        response, updated = cache.update(url, force=True)

        # Make sure that we ask for a non-cached version
        self._mocked_requests.get.assert_called_with(
            url, verify=mock.ANY, allow_redirects=True,
            headers={'Cache-Control': 'no-cache'})
        self.assertTrue(updated)

    #
    # Proper tests - Compression utilities
    #
    def test_get_content_detects_compression(self):
        """
        Ensures cache.get_content() detects compression out of the
        file extension embedded in the URL.
        """
        self.mock_http_request(
            content=b"\x1f\x8b\x08\x08\xca\xaa\x14Z\x00\x03helloworld\x00\xf3H"
                    b"\xcd\xc9\xc9W(\xcf/\xcaIQ\x04\x00\x95\x19\x85\x1b\x0c\x00"
                    b"\x00\x00"
        )
        cache = HttpCache(self.cache_directory)
        url = "http://example.com/foo.gz"
        cache.update(url)
        content = cache.get_content(url)
        self.assertEqual(content, b"Hello world!")

    def test_get_content_with_compression_parameter(self):
        """
        Ensures the compression parameter passed to cache.get_content()
        is used and overrides whatever can be detected in the URL.
        """
        self.mock_http_request(text="Hello world!")
        cache = HttpCache(self.cache_directory)
        url = "http://example.com/foo.gz"
        cache.update(url)
        content = cache.get_content(url, compression=None)
        self.assertEqual(content, b"Hello world!")

    def test_get_resource_content_ignore_network_failures(self):
        """
        Simulate a network failure and ensures it doen't trickle up
        but that we get no data either.
        """
        mock_cache = self.get_mock_of_http_cache()
        mock_cache.update.side_effect = IOError("Connection failure")

        content = get_resource_content(self.url, cache=mock_cache,
                                       ignore_network_failures=True)

        self.assertIsNone(content)
        self.assertFalse(mock_cache.get_content.called)

    def test_get_resource_content_no_ignore_network_failures(self):
        """
        Simulate a network failure and ensures it trickles up
        in some form by default.
        """
        mock_cache = self.get_mock_of_http_cache()
        mock_cache.update.side_effect = IOError("Connection failure")

        with self.assertRaises(IOError):
            get_resource_content(self.url, cache=mock_cache,
                                 ignore_network_failures=False)

    def test_get_resource_content_with_http_error(self):
        """
        Ensures that an HTTP error trickles up.
        """
        self.mock_http_request(status_code=404)

        with self.assertRaises(HTTPError):
            get_resource_content(self.url)

    def test_get_resource_content_ignore_http_error(self):
        """
        Ensures that we can ignore a specific HTTP error code.
        """
        self.mock_http_request(status_code=404)

        content = get_resource_content(self.url, ignore_http_error=404)

        self.assertIsNone(content)

    def test_get_resource_content_utility_function_cached(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function when the resource is cached in the given cache
        instance.
        """

        mock_cache = self.get_mock_of_http_cache()

        # In this test, the cached data is still valid, thus is_expired()
        # returns False.
        mock_cache.is_expired.return_value = False

        content = get_resource_content(self.url, cache=mock_cache)

        # The expected content is retrieved and no update request is made
        self.assertEqual(content, self.response_content)
        self.assertFalse(mock_cache.update.called)

    def test_get_resource_content_utility_function_not_cached(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function when the resource is not cached in the given cache
        instance.
        """

        mock_cache = self.get_mock_of_http_cache()

        # In this test, the cache is expired, and hence update has
        # to be called.
        mock_cache.is_expired.return_value = True
        mock_cache.update.return_value = (mock.MagicMock(), True)

        content = get_resource_content(self.url, mock_cache)

        # The update request has been made and returned new data
        mock_cache.update.assert_called_once_with(self.url, force=False)
        self.assertEqual(content, self.response_content)

    def test_get_resource_content_utility_function_force_update(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function when the force_update keyword argument is passed.
        """

        mock_cache = self.get_mock_of_http_cache()

        # In this test, the cache is expired, and hence update has
        # to be called.
        mock_cache.is_expired.return_value = False
        mock_cache.update.return_value = (mock.MagicMock(), True)

        get_resource_content(self.url, mock_cache, force_update=True)

        # The update request has been made with the force=True
        mock_cache.update.assert_called_once_with(self.url, force=True)

    def test_get_resource_content_with_only_arg_and_cache_expired(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function with the only_if_updated argument and an expired
        cache.
        """

        mock_cache = self.get_mock_of_http_cache()

        # Cache expired and update request returns new data
        mock_cache.is_expired.return_value = True
        mock_cache.update.return_value = (mock.MagicMock(), True)

        content = get_resource_content(self.url, cache=mock_cache,
                                       only_if_updated=True)

        self.assertEqual(content, self.response_content)

        # The function updated the cache
        mock_cache.update.assert_called_once_with(self.url, force=False)

    def test_get_resource_content_with_only_arg_and_cache_not_expired(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function with the only_if_updated argument and a not expired
        cache.
        """

        mock_cache = self.get_mock_of_http_cache()

        # The cache is not expired.
        mock_cache.is_expired.return_value = False

        content = get_resource_content(self.url, cache=mock_cache,
                                       only_if_updated=True)

        # We have valid data in the cache, no update request has been made
        self.assertIsNone(content)
        self.assertFalse(mock_cache.update.called)

    def test_get_resource_content_with_only_arg_cache_expired_no_update(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function with the only_if_updated argument, an expired cache
        but no real update done.
        """

        mock_cache = self.get_mock_of_http_cache()

        # Cache expired but the update request does not provide new data
        mock_cache.is_expired.return_value = True
        mock_cache.update.return_value = (None, False)

        content = get_resource_content(self.url, mock_cache,
                                       only_if_updated=True)

        # Nothing returned because the update request resulted in no new data
        self.assertIsNone(content)
        mock_cache.update.assert_called_once_with(self.url, force=False)

    @mock.patch('distro_tracker.core.utils.http.get_resource_content')
    def test_get_resource_text(self, mock_get_resource_content):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_text`
        utility function.
        """
        mock_get_resource_content.return_value = b"Some content"

        content = get_resource_text("http://some.url.com/")

        # The expected content is now decoded in a string
        self.assertEqual(content, "Some content")

    def test_get_resource_text_with_encoding(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_text`
        utility function with an explicit encoding argument.
        """
        content = "Raphaël".encode('latin1')
        mock_cache = self.get_mock_of_http_cache(get_content=content)
        mock_cache.is_expired.return_value = False

        content = get_resource_text("http://some.url.com/", cache=mock_cache,
                                    encoding='latin1')

        # The expected content is now decoded in a string
        self.assertEqual(content, "Raphaël")


class VerifySignatureTest(SimpleTestCase):
    """
    Tests the :func:`distro_tracker.core.utils.verify_signature` function.
    """

    def test_verify_signature_none(self):
        """
        Ensure the function does not fail when it's passed None as data
        to analyze.
        """
        self.assertIsNone(verify_signature(None))

    def test_signed_message(self):
        """
        Tests extracting the signature from a correctly signed message when the
        signer is found in the keyring.
        """
        self.import_key_into_keyring('key1.pub')
        file_path = self.get_test_data_path('signed-message')
        expected = [
            ('PTS Tests', 'fake-address@domain.com')
        ]

        with open(file_path, 'rb') as f:
            self.assertEqual(expected, verify_signature(f.read()))

    def test_signed_message_unknown_key(self):
        """
        Tests extracting the signature from a correctly signed message when the
        signer is not found in the keyring.
        """
        file_path = self.get_test_data_path('signed-message')

        with open(file_path, 'rb') as f:
            self.assertSequenceEqual([], verify_signature(f.read()))

    def test_incorrect_signature(self):
        """
        Tests extracting signature information when the signature itself is
        wrong.
        """
        self.assertIsNone(verify_signature(b"This is not a signature"))

    def test_utf8_content(self):
        """
        Tests extracting the signature from a message passed as unicode text
        instead of bytes.
        """
        self.import_key_into_keyring('key1.pub')
        file_path = self.get_test_data_path('signed-message')
        expected = [
            ('PTS Tests', 'fake-address@domain.com')
        ]

        with open(file_path, 'rb') as f:
            content = f.read().decode('utf-8')
            self.assertEqual(expected, verify_signature(content))

    @override_settings(DISTRO_TRACKER_FQDN='random.unrelated.domain')
    def test_uid_with_invalid_email_is_skipped(self):
        """
        Among all the available UID, make sure we skip those without email
        or with invalid emails.
        """
        # The invalid UID have been put first in the list of UIDs on that key
        self.import_key_into_keyring('key2.pub')
        file_path = self.get_test_data_path('signed-message-with-key2')
        expected = [
            ('John Doe', 'test@ouaza.com')
        ]

        with open(file_path, 'rb') as f:
            self.assertEqual(expected, verify_signature(f.read()))

    @override_settings(DISTRO_TRACKER_FQDN='tracker.debian.org')
    def test_uid_with_project_domain_is_preferred(self):
        """
        If we have an UID using the same domain name as this instance,
        then prefer that UID.
        """
        self.import_key_into_keyring('key2.pub')
        file_path = self.get_test_data_path('signed-message-with-key2')
        expected = [
            ('John Debian', 'test@debian.org')
        ]

        with open(file_path, 'rb') as f:
            self.assertEqual(expected, verify_signature(f.read()))

    @override_settings(DISTRO_TRACKER_FQDN='tracker.revoked.net')
    def test_skip_revoked_uid_with_project_domain(self):
        """Ensure that we ignore invalid and revoked UIDs."""
        self.import_key_into_keyring('key2.pub')
        file_path = self.get_test_data_path('signed-message-with-key2')
        # We do have an UID in @revoked.net but it's not selected, instead
        # we get the first key with a valid email.
        expected = [
            ('John Doe', 'test@ouaza.com')
        ]

        with open(file_path, 'rb') as f:
            self.assertEqual(expected, verify_signature(f.read()))

    @mock.patch('distro_tracker.core.utils.logger_input')
    def test_key_without_any_email(self, logger):
        """Ensure that we deal properly with keys without emails."""
        self.import_key_into_keyring('key3.pub')
        file_path = self.get_test_data_path('signed-message-with-key3')

        # No identity is returned
        with open(file_path, 'rb') as f:
            self.assertEqual([], verify_signature(f.read()))

        # A message is logged about this bad key
        self.assertTrue(logger.warning.called)


class DecodeHeaderTest(SimpleTestCase):
    """
    Tests for :func:`distro_tracker.core.utils.email_messages.decode_header`.
    """
    def test_decode_header_iso(self):
        """
        Single part iso-8859-1 encoded text.
        """
        h = Header(b'M\xfcnchen', 'iso-8859-1')
        header_text = decode_header(h)
        self.assertEqual('München', header_text)

    def test_decode_header_utf8(self):
        """
        Single part utf-8 encoded text.
        """
        h = Header(b'M\xc3\xbcnchen', 'utf-8')
        header_text = decode_header(h)
        self.assertEqual('München', header_text)

    def test_decode_header_multipart(self):
        """
        Two part header: iso-8859-1 and utf-8
        """
        h = Header(b'M\xfcnchen', 'iso-8859-1')
        h.append(b' M\xc3\xbcnchen', 'utf-8')
        header_text = decode_header(h)
        self.assertEqual('München München', header_text)

    def test_decode_header_none(self):
        self.assertIsNone(decode_header(None))


class AptCacheTests(TestCase):
    """
    Tests for :class:`distro_tracker.core.utils.packages.AptCache`.
    """
    @staticmethod
    def stub_acquire(source_records, dest_dir, debian_dir_only, content):
        # Create a file in the destination directory
        file_name = 'temp'
        file_path = os.path.join(dest_dir, file_name)
        # Create a file of the given size
        with open(file_path, 'wb') as f:
            f.write(content)
        return None, 'ekrem'

    def create_cache(self):
        """
        Helper method which creates an
        :class:`distro_tracker.core.utils.packages.AptCache` instance which is
        used for testing. Some of its methods are replaced by mocks and stubs to
        avoid HTTP calls.
        """
        self.cache = AptCache()
        self.cache._get_apt_source_records = mock.MagicMock()
        self.cache._get_format = mock.MagicMock(return_value='1.0')
        self.cache._extract_dpkg_source = mock.MagicMock()
        self.cached_files = []
        self.cache._get_all_cached_files = mock.MagicMock(
            return_value=self.cached_files)
        self.cache._match_index_file_to_repository = mock.MagicMock()

    def set_stub_acquire_content(self, content):
        """
        Helper method which sets the content of a file which is created by the
        cache instance when retrieve_source is called.
        """
        self.cache._apt_acquire_package = mock.MagicMock(side_effect=partial(
            AptCacheTests.stub_acquire, content=content))

    def set_stub_cached_files_for_repository(self, repository, files):
        """
        Helper method adds the given list of files to the stub list of cached
        files for a given repository.

        :param repository: The repository to which these files are associated.
        :type repository: :class:`Repository
            <distro_tracker.core.models.Repository>`
        :param files: List of cached file names. The function uses the list to
            build the stub by prefixing the names with expected repository
            identifiers.
        """
        # Build the prefix from the repository's URI and suite
        base_uri = repository.uri.rstrip('/')
        if base_uri.startswith('http://'):
            base_uri = base_uri[7:]
        prefix = base_uri + '/' + repository.suite + '/'
        prefix = prefix.replace('/', '_')
        for file_name in files:
            self.cached_files.append(prefix + file_name)
        self.cache._match_index_file_to_repository.return_value = (
            repository, 'main')

    def assert_cache_size_equal(self, size):
        self.assertEqual(size, self.cache.cache_size)

    def test_cache_size_increase_after_acquire(self):
        """
        Tests that the cache correctly increases its size after acquiring new
        files.
        """
        with self.settings(DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
            self.create_cache()
            # Sanity check: old size is 0 as nothing was ever cached in the
            # brand new directory
            self.assert_cache_size_equal(0)
            content = b'a' * 5  # 5 bytes
            self.set_stub_acquire_content(content)

            self.cache.retrieve_source('dummy-package', '1.0.0')

            self.assert_cache_size_equal(5)

    def test_cache_multiple_insert_no_remove(self):
        """
        Tests that the cache does not remove packages unless the size limit is
        exceeded.
        """
        with self.settings(DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
            self.create_cache()
            # Sanity check: old size is 0 as nothing was ever cached in the
            # brand new directory
            self.assert_cache_size_equal(0)
            content = b'a' * 5  # 5 bytes
            self.set_stub_acquire_content(content)
            # Add one file.
            self.cache.retrieve_source('dummy-package', '1.0.0')
            self.assert_cache_size_equal(5)
            # Same content in another file
            self.set_stub_acquire_content(content)

            self.cache.retrieve_source('package', '1.0.0')

            # Both files are now saved.
            self.assert_cache_size_equal(10)

    def test_clear_cache(self):
        """
        Tests that the cache removes packages when it exceeds its allocated
        size.
        """
        with self.settings(DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
            self.create_cache()
            # Sanity check: old size is 0 as nothing was ever cached in the
            # brand new directory
            self.assert_cache_size_equal(0)
            initial_content = b'a' * 11
            self.set_stub_acquire_content(initial_content)
            # Set initial source content
            self.cache.retrieve_source('dummy-package', '1.0.0')
            self.assert_cache_size_equal(11)
            content = b'a' * 7
            self.set_stub_acquire_content(content)

            self.cache.retrieve_source('package', '1.0.0')

            # Only the second content is found in the package
            self.assert_cache_size_equal(7)

    def test_get_sources_for_repository(self):
        """
        Tests that the cache correctly returns a list of cached Sources files
        for a given repository.
        """
        self.create_cache()
        repository = Repository.objects.create(
            name='stable',
            shorthand='stable',
            uri='https://deb.debian.org/debian/dists',
            suite='stable')
        expected_source_files = [
            'main_source_Sources',
            'contrib_source_Sources',
        ]
        files = expected_source_files + [
            'Release',
            'main_binary-amd64_Packages',
        ]
        self.set_stub_cached_files_for_repository(repository, files)

        sources = \
            self.cache.get_sources_files_for_repository(repository)

        self.assertEqual(len(expected_source_files), len(sources))
        for expected_source, returned_source in zip(
                expected_source_files, sources):
            self.assertTrue(returned_source.endswith(expected_source))

    def test_get_packages_for_repository(self):
        """
        Tests that the cache correctly returns a list of cached Packages files
        for a given repository.
        """
        self.create_cache()
        repository = Repository.objects.create(
            name='stable',
            shorthand='stable',
            uri='https://deb.debian.org/debian/dists',
            suite='stable')
        expected_packages_files = [
            'main_binary-amd64_Packages',
            'main_binary-i386_Packages',
        ]
        files = expected_packages_files + [
            'Release',
            'main_source_Sources',
        ]
        self.set_stub_cached_files_for_repository(repository, files)

        packages = \
            self.cache.get_packages_files_for_repository(repository)

        self.assertEqual(len(expected_packages_files), len(packages))
        for expected, returned in zip(
                expected_packages_files, packages):
            self.assertTrue(returned.endswith(expected))


class LinkifyTests(TestCase):
    """
    Tests for :func:`distro_tracker.core.utils.linkify`.
    """
    sample_url = "http://www.example.com/foo/"
    https_url = "https://www.example.com.foo/"

    @staticmethod
    def link(url):
        return '<a href="{url}">{url}</a>'.format(url=url)

    @staticmethod
    def debian_bug(bug, baseurl='https://bugs.debian.org/'):
        bugno = bug[1:] if bug[0] == '#' else bug
        return '<a href="{}{}">{}</a>'.format(baseurl, bugno, bug)

    @classmethod
    def lp_bug(cls, bug):
        return cls.debian_bug(bug, 'https://bugs.launchpad.net/bugs/')

    @staticmethod
    def cve_link(cve,
                 baseurl='https://cve.mitre.org/cgi-bin/cvename.cgi?name='):
        return '<a href="{}{}">{}</a>'.format(baseurl, cve, cve)

    def setUp(self):
        self.data = {
            'LinkifyHttpLinks': {
                'simple': (self.sample_url, self.link(self.sample_url)),
                'https': (self.https_url, self.link(self.https_url)),
                # Default case, link in text
                'intext': ('see ' + self.sample_url + ' for example',
                           'see ' + self.link(self.sample_url) +
                           ' for example'),
                # Existing HTML links are not re-processed
                'htmllink': (self.link(self.sample_url),
                             self.link(self.sample_url)),
                # Ensure xhttp:// is not recognized as a link
                'badlink': ('x' + self.sample_url, 'x' + self.sample_url)
            },
            'LinkifyDebianBugLinks': {
                'simple': ('closes: ' + '1234', 'closes: ' +
                           self.debian_bug(bug='1234')),
                'withsharp': ('Closes: ' + '#1234', 'Closes: ' +
                              self.debian_bug(bug='#1234')),
                'intext': ('see closes: ' + '#1234' +
                           'for informations',
                           'see closes: ' + self.debian_bug(bug='#1234') +
                           'for informations'),
                'multipleintext': ('see Closes: ' + '1234, 5678,\n9123' +
                                   'or closes: ' + '456' + 'for example',
                                   'see Closes: ' +
                                   self.debian_bug(bug='1234') + ', ' +
                                   self.debian_bug(bug='5678') + ',\n' +
                                   self.debian_bug(bug='9123') + 'or ' +
                                   'closes: ' +
                                   self.debian_bug(bug='456') + 'for example'),
                # Case of a Closes field on its single line (space-separated)
                'closesfield': ('\nCloses: 123 456\n',
                                '\nCloses: ' + self.debian_bug('123') + ' ' +
                                self.debian_bug('456') + '\n'),
                'txtbeforefield': ('\nFinally Closes: 123 456\n',
                                   '\nFinally Closes: ' +
                                   self.debian_bug('123') + ' 456\n'),
                'txtafterfield': ('\nCloses: 123 456 foobar\n',
                                  '\nCloses: ' + self.debian_bug('123') +
                                  ' 456 foobar\n'),
            },
            'LinkifyUbuntuBugLinks': {
                'simple': ('lp: ' + '1234', 'lp: ' +
                           self.lp_bug(bug='1234')),
                'withsharp': ('Lp: ' + '#1234', 'Lp: ' +
                              self.lp_bug(bug='#1234')),
                'intext': ('see lp: ' + '#1234' +
                           'for informations',
                           'see lp: ' + self.lp_bug('#1234') +
                           'for informations'),
                'multipleintext': ('see lp: ' + '1234, 5678,\n9123' +
                                   'or lp: ' + '456' + 'for example',
                                   'see lp: ' +
                                   self.lp_bug(bug='1234') + ', ' +
                                   self.lp_bug(bug='5678') + ',\n' +
                                   self.lp_bug(bug='9123') + 'or lp: ' +
                                   self.lp_bug(bug='456') + 'for example')
            },
            'LinkifyCVELinks': {
                'oldformat': ('CVE-2012-1234',
                              self.cve_link('CVE-2012-1234')),
                'newformat': ('CVE-2014-1234567',
                              self.cve_link('CVE-2014-1234567')),
                'intext': ('see ' + 'cve-2014-67890' + ' for informations',
                           'see ' + self.cve_link('cve-2014-67890') +
                           ' for informations'),
                'parens': ('(CVE-2017-1234)',
                           "(%s)" % (
                               self.cve_link('CVE-2017-1234'),
                           )),
                'notinurl': ('foo.debian.org/CVE-2014-1234',
                             'foo.debian.org/CVE-2014-1234'),
            },
        }

    def _test_linkify_class(self, cls):
        linkifier = cls()
        for name, data in self.data[cls.__name__].items():
            output = linkifier.linkify(data[0])
            self.assertEqual(output, data[1],
                             '{} failed with "{}" test data'.format(
                                 cls.__name__, name))

    def test_linkify_http(self):
        """Test the linkifyHttpLinks class"""
        self._test_linkify_class(LinkifyHttpLinks)

    def test_linkify_debian_bug(self):
        """Test the linkifyDebianbug class"""
        self._test_linkify_class(LinkifyDebianBugLinks)

    def test_linkify_ubuntu_bug(self):
        """Test the linkifyUbuntubug class"""
        self._test_linkify_class(LinkifyUbuntuBugLinks)

    def test_linkify_CVE_links(self):
        """Test the LinkifyCVELinks class"""
        self._test_linkify_class(LinkifyCVELinks)

    @override_settings(
        DISTRO_TRACKER_CVE_URL='https://security-tracker.debian.org/tracker/')
    def test_linkify_CVE_links_custom_url(self):
        """Test LinkifyCVELinks with a custom DISTRO_TRACKER_CVE_URL"""
        url = 'https://security-tracker.debian.org/tracker/'
        # Replace the URL in the expected data
        for key, content in self.data['LinkifyCVELinks'].items():
            self.data['LinkifyCVELinks'][key] = (
                content[0],
                content[1].replace(
                    "https://cve.mitre.org/cgi-bin/cvename.cgi?name=", url)
            )
        self._test_linkify_class(LinkifyCVELinks)

    def test_linkify(self):
        """Test the linkify function as a combination of all the individual
        tests."""
        text = ''
        expected = ''
        for linkifier_test_data in self.data.values():
            for before, after in linkifier_test_data.values():
                text += before + '\n'
                expected += after + '\n'
        linkify_output = linkify(text)
        self.assertEqual(linkify_output, expected)


class UtilsTests(TestCase):
    def test_now(self):
        """Ensure distro_tracker.core.utils.now() exists"""
        self.assertIsInstance(now(), datetime.datetime)

    def test_get_data_checksum(self):
        """Ensures get_data_checksum behaves as expected."""
        checksum = get_data_checksum({})
        self.assertEqual(checksum, '99914b932bd37a50b983c5e7c90ae93b')

    def test_get_data_checksum_ignores_checksum_key(self):
        checksum = get_data_checksum({
            'checksum': 'this key should be ignored for the checksum',
        })
        self.assertEqual(checksum, '99914b932bd37a50b983c5e7c90ae93b')

    def test_safe_redirect_works(self):
        """Tests the default safe_url"""

        _ret = safe_redirect(
            "/pkg/dummy",
            "/",
        )

        self.assertIsInstance(_ret, HttpResponseRedirectBase)
        self.assertEqual(_ret.url, "/pkg/dummy")

    def test_safe_redirect_fallbacks_properly(self):
        """Tests the default safe_url"""

        _ret = safe_redirect(
            "https://example.com",
            "/",
            allowed_hosts=None,
        )

        self.assertIsInstance(_ret, HttpResponseRedirectBase)
        self.assertEqual(_ret.url, "/")

    def test_safe_redirect_fallbacks_properly_again(self):
        """Tests the default safe_url"""

        _ret = safe_redirect(
            "https://example.com",
            "/",
            allowed_hosts=[],
        )

        self.assertIsInstance(_ret, HttpResponseRedirectBase)
        self.assertEqual(_ret.url, "/")

    def test_safe_redirect_works_with_allowed_hosts(self):
        """Tests the default safe_url"""

        _ret = safe_redirect(
            "https://example.com",
            "/",
            allowed_hosts=["example.com"],
        )

        self.assertIsInstance(_ret, HttpResponseRedirectBase)
        self.assertEqual(_ret.url, "https://example.com")


class CallMethodsTests(TestCase):
    def setUp(self):
        class Sample(object):
            do_it = True  # Not callable, but same prefix

            def __init__(self):
                self.called = []

            def do_step1(self, *args, **kwargs):
                self.called.append('step1')

            def do_step2(self, *args, **kwargs):
                self.called.append('step2')

            def do_clean(self, *args, **kwargs):
                self.called.append('clean')

        self.sample_object = Sample()

    def test_call_method_with_prefix(self):
        call_methods_with_prefix(self.sample_object, 'do_')
        # The tree do_* methods have been called in the right order
        self.assertListEqual(self.sample_object.called,
                             ['clean', 'step1', 'step2'])

    def test_call_method_passes_arguments(self):
        with mock.patch.object(self.sample_object, 'do_step1') as method:
            call_methods_with_prefix(self.sample_object, 'do_', 'arg',
                                     keyword='keyword')
            method.assert_called_with('arg', keyword='keyword')


class CompressionTests(TestCase):
    def setUp(self):
        # Set up a cache directory to use in the tests
        _handler, self.temporary_bzip2_file = tempfile.mkstemp(suffix='.bz2')
        os.write(
            _handler,
            (
                b'BZh91AY&SY\x03X\xf5w\x00\x00\x01\x15\x80`\x00\x00@\x06\x04'
                b'\x90\x80 \x001\x06LA\x03L"\xe0\x8bb\xa3\x9e.\xe4\x8ap\xa1 '
                b'\x06\xb1\xea\xee'
            ),
        )
        os.close(_handler)
        _handler, self.temporary_gzip_file = tempfile.mkstemp(suffix='.gz')
        os.write(
            _handler,
            (
                b"\x1f\x8b\x08\x08\xca\xaa\x14Z\x00\x03helloworld\x00\xf3H"
                b"\xcd\xc9\xc9W(\xcf/\xcaIQ\x04\x00\x95\x19\x85\x1b\x0c\x00"
                b"\x00\x00"
            ),
        )
        os.close(_handler)
        _handler, self.temporary_xz_file = tempfile.mkstemp(suffix='.xz')
        os.write(
            _handler,
            (
                b"\xfd7zXZ\x00\x00\x04\xe6\xd6\xb4F\x02\x00!\x01\x16\x00\x00"
                b"\x00t/\xe5\xa3\x01\x00\x0bHello world!\x00\nc\xd6\xf3\xf6"
                b"\x80[\xd3\x00\x01$\x0c\xa6\x18\xd8\xd8\x1f\xb6\xf3}\x01\x00"
                b"\x00\x00\x00\x04YZ"
            ),
        )
        os.close(_handler)
        _handler, self.temporary_plain_file = tempfile.mkstemp()
        os.write(_handler, b"Hello world!")
        os.close(_handler)

    def tearDown(self):
        os.unlink(self.temporary_bzip2_file)
        os.unlink(self.temporary_gzip_file)
        os.unlink(self.temporary_xz_file)
        os.unlink(self.temporary_plain_file)

    def get_uncompressed_text(self, file_path, compression):
        """Calls to the uncompress function and does the redundant jobs for
        each subtest"""

        with open(file_path, 'rb') as compressed_stream:
            with get_uncompressed_stream(compressed_stream,
                                         compression) as handler:
                return handler.read().decode('ascii')

    def test_bzip2_file(self):
        """Tests the decompression of a bzip2 file"""
        output = self.get_uncompressed_text(
            self.temporary_bzip2_file, compression="bzip2")
        self.assertEqual(output, "Hello world!")

    def test_gzip_file(self):
        """Tests the decompression of a gzip file"""
        output = self.get_uncompressed_text(
            self.temporary_gzip_file, compression="gzip")
        self.assertEqual(output, "Hello world!")

    def test_xz_file(self):
        """Tests the decompression of a lzma-xz file"""
        output = self.get_uncompressed_text(
            self.temporary_xz_file, compression="xz")
        self.assertEqual(output, "Hello world!")

    def test_no_compression_file(self):
        """Tests if a non-compressed file is correctly handled."""
        output = self.get_uncompressed_text(
            self.temporary_plain_file, compression=None)
        self.assertEqual(output, "Hello world!")

    def test_uncompress_with_unnamed_file(self):
        """Ensure we can deal with file objects that have no name attribute"""
        data = io.BytesIO(b"Hello world!")
        output = get_uncompressed_stream(data, compression=None).read()
        self.assertEqual(output, b"Hello world!")

    def test_uncompress_with_unnamed_file_and_no_compression_specified(self):
        """Ensure we raise an exception when we can't guess the compression"""
        data = io.BytesIO(b"Hello world!")
        with self.assertRaises(ValueError):
            get_uncompressed_stream(data)

    def test_compression_guess(self):
        """As the compression is given explicitely in the previous tests
        because tempfiles have no extension, this test checks if the
        guess_compression_method function in compression utils works fine.

        """

        for (ext, method) in [
                ("gz", "gzip"),
                ("bz2", "bzip2"),
                ("xz", "xz"),
                ("txt", None),
        ]:
            filename = "%s.%s" % ("test", ext)
            self.assertEqual(
                guess_compression_method(filename),
                method)

        # Ensure we check for ".gz" and not "gz" only
        self.assertIsNone(guess_compression_method("bugz"))
