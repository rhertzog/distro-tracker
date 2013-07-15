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
from django.utils.six.moves import mock
from pts.dispatch.tests import DispatchTestHelperMixin, DispatchBaseTest
from pts.core.models import Package
from pts.core.models import Developer
from pts.core.tasks import run_task
from pts.vendor.debian.rules import get_package_information_site_url
from pts.vendor.debian.rules import get_maintainer_extra
from pts.vendor.debian.rules import get_uploader_extra
from pts.vendor.debian.rules import get_developer_information_url
from pts.vendor.debian.tasks import RetrieveDebianMaintainersTask
from pts.vendor.debian.tasks import RetrieveLowThresholdNmuTask
from pts.vendor.debian.models import DebianContributor


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
            'http://qa.debian.org/developer.php?email=debian-dpkg@lists.debian.org',
            get_developer_information_url(developer_email)
        )

        developer_email = 'email@domain.com'
        self.assertEqual(
            'http://qa.debian.org/developer.php?email=email@domain.com',
            get_developer_information_url(developer_email)
        )


class RetrieveLowThresholdNmuTest(TestCase):
    def set_mock_response(self, mock_requests, text="", status_code=200):
        """
        Helper method which sets a mock response to the given mock_requests
        module.
        """
        mock_response = mock_requests.models.Response()
        mock_response.status_code = status_code
        mock_response.ok = status_code < 400
        mock_response.text = text
        mock_response.content = text.encode('utf-8')
        mock_response.iter_lines.return_value = text.splitlines()
        mock_requests.get.return_value = mock_response

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer did not previously exist in the database.
        """
        self.set_mock_response(mock_requests,
            "Text text text\n"
            "text more text...\n"
            " 1. [[DeveloperName|Name]] - "
            "([[http://qa.debian.org/developer.php?"
            "login=dummy|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.agree_with_low_threshold_nmu)

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_existed(self, mock_requests):
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer was previously registered in the database.
        """
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        self.set_mock_response(mock_requests,
            "Text text text\n"
            "text more text...\n"
            " 1. [[DeveloperName|Name]] - "
            "([[http://qa.debian.org/developer.php?"
            "login=dummy|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        # Still only one debian developer instance
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.agree_with_low_threshold_nmu)
        # The name of the original developer model has not changed.
        self.assertEqual('Name', d.developer.name)

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_remove_nmu(self, mock_requests):
        """
        Tests updating the list of NMU developers when one of them needs to be
        removed from the list.
        """
        # Set up a Debian developer that is already in the NMU list.
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        DebianContributor.objects.create(developer=d,
                                       agree_with_low_threshold_nmu=True)
        self.set_mock_response(mock_requests,
            "Text text text\n"
            "text more text...\n"
            " 1. [[DeveloperName|Name]] - "
            "([[http://qa.debian.org/developer.php?"
            "login=other|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        d = DebianContributor.objects.get(developer__email='dummy@debian.org')
        # The Debian developer is no longer in the list of low threshold nmu
        self.assertFalse(d.agree_with_low_threshold_nmu)


class RetrieveDebianMaintainersTest(TestCase):
    def set_mock_response(self, mock_requests, text="", status_code=200):
        """
        Helper method which sets a mock response to the given mock_requests
        module.
        """
        mock_response = mock_requests.models.Response()
        mock_response.status_code = status_code
        mock_response.ok = status_code < 400
        mock_response.content = text.encode('utf-8')
        mock_response.text = text
        mock_response.iter_lines.return_value = text.splitlines()
        mock_requests.get.return_value = mock_response

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the DM list when a new developer is to be added.
        """
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer did not previously exist in the database.
        """
        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.debian_maintainer)
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_existed(self, mock_requests):
        """
        Tests updating the DM list when the developer was previously registered
        in the database.
        """
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.debian_maintainer)
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )
        # The name of the original developer model has not changed.
        self.assertEqual('Name', d.developer.name)

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_update_dm_list(self, mock_requests):
        """
        Tests updating the DM list when one of the developers has changes in
        the allowed packages list.
        """
        # Set up a Debian developer that is already in the NMU list.
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        DebianContributor.objects.create(developer=d,
                                       debian_maintainer=True,
                                       allowed_packages=['one'])

        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(developer__email='dummy@debian.org')
        # The old package is no longer in its list of allowed packages.
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_delete_from_dm_list(self, mock_requests):
        """
        Tests updating the DM list when one of the developers has changes in
        the allowed packages list.
        """
        # Set up a Debian developer that is already in the DM list.
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        DebianContributor.objects.create(developer=d,
                                       debian_maintainer=True,
                                       allowed_packages=['one'])

        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <different-developer@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(developer__email='dummy@debian.org')
        # The developer is no longer a debian maintainer
        self.assertFalse(d.debian_maintainer)


class DebianDeveloperExtraTest(TestCase):
    def test_maintainer_extra(self):
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        d = DebianContributor.objects.create(developer=d,
                                           agree_with_low_threshold_nmu=True)

        # Only in NMU list
        self.assertSequenceEqual(
            [{
                'display': 'LowNMU',
                'description': 'maintainer agrees with Low Threshold NMU',
                'link': 'http://wiki.debian.org/LowThresholdNmu',
            }],
            get_maintainer_extra('dummy@debian.org')
        )
        # The developer is now in the DM list
        d.debian_maintainer = True
        d.allowed_packages = ['package-name']
        d.save()
        # When not providing a package name, the response is the same
        self.assertSequenceEqual(
            [{
                'display': 'LowNMU',
                'description': 'maintainer agrees with Low Threshold NMU',
                'link': 'http://wiki.debian.org/LowThresholdNmu',
            }],
            get_maintainer_extra('dummy@debian.org')
        )
        # With a package name an extra item is in the response.
        self.assertSequenceEqual([
            {
                'display': 'LowNMU',
                'description': 'maintainer agrees with Low Threshold NMU',
                'link': 'http://wiki.debian.org/LowThresholdNmu',
            },
            {'display': 'dm'}
        ],
            get_maintainer_extra('dummy@debian.org', 'package-name')
        )

    def test_uploader_extra(self):
        d = Developer.objects.create(email='dummy@debian.org', name='Name')
        d = DebianContributor.objects.create(developer=d,
                                           agree_with_low_threshold_nmu=True)

        # Only in NMU list - no extra data when the developer in displayed as
        # an uploader.
        self.assertIsNone(get_uploader_extra('dummy@debian.org'))
        # The developer is now in the DM list
        d.debian_maintainer = True
        d.allowed_packages = ['package-name']
        d.save()
        # When not providing a package name, the response is the same
        self.assertIsNone(get_uploader_extra('dummy@debian.org'))
        # With a package name an extra item is in the response.
        self.assertSequenceEqual([
            {'display': 'dm'}
        ],
            get_uploader_extra('dummy@debian.org', 'package-name')
        )

