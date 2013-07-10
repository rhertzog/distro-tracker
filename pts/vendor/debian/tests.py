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
Tests for Debian-specific modules/functionality of the PTS.
"""

from __future__ import unicode_literals
from django.test import TestCase, SimpleTestCase
from django.test.utils import override_settings
from django.core import mail
from pts.dispatch.tests import DispatchTestHelperMixin, DispatchBaseTest
from pts.core.models import Package
from django.utils.six.moves import mock
from pts.vendor.debian.rules import get_package_information_site_url
from pts.vendor.debian.rules import get_developer_information_url


__all__ = ('DispatchDebianSpecificTest', 'DispatchBaseDebianSettingsTest')


@override_settings(PTS_VENDOR_RULES='pts.vendor.debian.rules')
class DispatchBaseDebianSettingsTest(DispatchBaseTest):
    """
    This test class makes sure that base tests which should pass no matter the
    vendor work when PTS_VENDOR_RULES is set to use debian.
    """
    pass


@override_settings(PTS_VENDOR_RULES='pts.vendor.debian.rules')
class DispatchDebianSpecificTest(TestCase, DispatchTestHelperMixin):
    """
    Tests Debian-specific keyword classification.
    """
    def setUp(self):
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.set_message_content('message content')

        self.package = Package.objects.create(name=self.package_name)

    def test_dispatch_bts_control(self):
        """
        Tests that the dispatch properly tags a message as bts-control
        """
        self.set_header('X-Debian-PR-Message', 'transcript of something')
        self.set_header('X-Loop', 'owner@bugs.debian.org')
        self.subscribe_user_with_keyword('user@domain.com', 'bts-control')

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'bts-control')

    def test_dispatch_bts(self):
        """
        Tests that the dispatch properly tags a message as bts
        """
        self.set_header('X-Debian-PR-Message', '1')
        self.set_header('X-Loop', 'owner@bugs.debian.org')
        self.subscribe_user_with_keyword('user@domain.com', 'bts')

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'bts')

    def test_dispatch_upload_source(self):
        self.set_header('Subject', 'Accepted 0.1 in unstable')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('Files\nchecksum lib.dsc\ncheck lib2.dsc')
        self.subscribe_user_with_keyword('user@domain.com', 'upload-source')

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'upload-source')

    def test_dispatch_upload_binary(self):
        self.set_header('Subject', 'Accepted 0.1 in unstable')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('afgdfgdrterfg')
        self.subscribe_user_with_keyword('user@domain.com', 'upload-binary')

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'upload-binary')

    def test_dispatch_archive(self):
        self.set_header('Subject', 'Comments regarding some changes')
        self.set_header('X-DAK', 'DAK')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.set_message_content('afgdfgdrterfg')
        self.subscribe_user_with_keyword('user@domain.com', 'archive')

        self.run_dispatch()

        self.assert_message_forwarded_to('user@domain.com')
        self.assert_header_equal('X-PTS-Keyword', 'archive')

    def test_default_not_trusted(self):
        """
        Tests that a non-trusted default message is dropped.
        """
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 0)

    def test_debian_trusts_mozilla(self):
        """
        Tests that messages tagged with the default keyword are forwarded when
        they originated from Bugzilla.
        """
        self.set_header('X-Bugzilla-Product', '1')
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assertEqual(len(mail.outbox), 1)

    def test_debian_specific_headers(self):
        """
        Tests that debian specific headers are included in forwarded messages.
        """
        expected_headers = [
            ('X-Debian-Package', self.package_name),
            ('X-Debian', 'PTS'),
        ]
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_all_headers_found(expected_headers)


class GetPseudoPackageListTest(TestCase):
    @mock.patch('pts.vendor.debian.rules.requests')
    def test_debian_pseudo_packages(self, mock_requests):
        """
        Tests that Debian-specific function for retrieving allowed pseudo
        packages uses the correct source and properly parses it.
        """
        from pts.vendor.debian.rules import get_pseudo_package_list
        mock_response = mock_requests.models.Response()
        mock_response.status_code = 200
        mock_response.text = (
            'package1      text here\n'
            'package2\t\t text'
        )
        mock_requests.get.return_value = mock_response

        packages = get_pseudo_package_list()

        # Correct URL used?
        mock_requests.get.assert_called_with(
            'http://bugs.debian.org/pseudo-packages.maintainers')
        # Correct packages extracted?
        self.assertSequenceEqual(
            ['package1', 'package2'],
            packages
        )


class GetPackageInformationSiteUrlTest(SimpleTestCase):
    def test_get_source_package_url(self):
        """
        Tests retrieving a URL to the package information site for a source
        package.
        """
        # Source package with no repository given
        self.assertEqual(
            'http://packages.debian.org/src:dpkg',
            get_package_information_site_url('dpkg', source_package=True)
        )
        # Source package in a repository
        self.assertEqual(
            'http://packages.debian.org/source/stable/dpkg',
            get_package_information_site_url('dpkg', True, 'stable')
        )

    def test_get_binary_package_url(self):
        """
        Tests retrieving a URL to the package information site for a binary
        package.
        """
        # Binary package with no repository given
        self.assertEqual(
            'http://packages.debian.org/dpkg',
            get_package_information_site_url('dpkg')
        )
        # Binary package in a repository
        self.assertEqual(
            'http://packages.debian.org/unstable/dpkg',
            get_package_information_site_url('dpkg', repository_name='unstable')
        )


class GetDeveloperInformationSiteUrlTest(SimpleTestCase):
    def test_get_developer_site_info_url(self):
        """
        Test retrieving a URL to a developer information Web site.
        """
        developer_email = 'debian-dpkg@lists.debian.org'
        self.assertEqual(
            'http://qa.debian.org/developer.php?login=debian-dpkg@lists.debian.org',
            get_developer_information_url(developer_email)
        )

        developer_email = 'email@domain.com'
        self.assertEqual(
            'http://qa.debian.org/developer.php?login=email@domain.com',
            get_developer_information_url(developer_email)
        )
