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
from django.utils.encoding import force_bytes
from pts.dispatch.tests import DispatchTestHelperMixin, DispatchBaseTest
from pts.core.models import News
from pts.core.models import PackageName
from pts.core.models import SourcePackage
from pts.core.models import SourcePackageName
from pts.core.models import Repository
from pts.core.models import ContributorEmail
from pts.core.tasks import run_task
from pts.core.retrieve_data import UpdateRepositoriesTask
from pts.vendor.debian.rules import get_package_information_site_url
from pts.vendor.debian.rules import get_maintainer_extra
from pts.vendor.debian.rules import get_uploader_extra
from pts.vendor.debian.rules import get_developer_information_url
from pts.vendor.debian.tasks import RetrieveDebianMaintainersTask
from pts.vendor.debian.tasks import RetrieveLowThresholdNmuTask
from pts.vendor.debian.models import DebianContributor
from pts.mail_news.process import process

from email.message import Message

import os


__all__ = ('DispatchDebianSpecificTest', 'DispatchBaseDebianSettingsTest')


@override_settings(PTS_VENDOR_RULES='pts.vendor.debian.rules')
class DispatchBaseDebianSettingsTest(DispatchBaseTest):
    """
    This test class makes sure that base tests pass when
    :py:data:`PTS_VENDOR_RULES <pts.project.settings.PTS_VENDOR_RULES>` is set
    to use debian.
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

        self.package = PackageName.objects.create(name=self.package_name)

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

    def test_debian_trusts_bugzilla(self):
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

    def test_legacy_keyword_override_cvs(self):
        """
        Tests that keywords used by the old PTS which have been replaced are
        properly mapped to their new values by the Debian-specific module.
        """
        address = '{name}_{keyword}'.format(
            name=self.package_name, keyword='cvs')
        # Subscribed to the new keyword
        self.subscribe_user_with_keyword('user@domain.com', 'vcs')

        self.run_dispatch(address)

        self.assert_header_equal('X-PTS-Keyword', 'vcs')

    def test_legacy_keyword_override_ddtp(self):
        """
        Tests that keywords used by the old PTS which have been replaced are
        properly mapped to their new values by the Debian-specific module.
        """
        address = '{name}_{keyword}'.format(
            name=self.package_name, keyword='ddtp')
        # Subscribed to the new keyword
        self.subscribe_user_with_keyword('user@domain.com', 'translation')

        self.run_dispatch(address)

        self.assert_header_equal('X-PTS-Keyword', 'translation')


class GetPseudoPackageListTest(TestCase):
    @mock.patch('pts.core.utils.http.requests')
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
        mock_response.content = mock_response.text.encode('utf-8')
        mock_response.ok = True
        mock_requests.get.return_value = mock_response

        packages = get_pseudo_package_list()

        # Correct URL used?
        mock_requests.get.assert_called_with(
            'http://bugs.debian.org/pseudo-packages.maintainers', headers={})
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
        email = ContributorEmail.objects.create(email='dummy@debian.org')
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

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_remove_nmu(self, mock_requests):
        """
        Tests updating the list of NMU developers when one of them needs to be
        removed from the list.
        """
        # Set up a Debian developer that is already in the NMU list.
        email = ContributorEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         agree_with_low_threshold_nmu=True)
        self.set_mock_response(mock_requests,
            "Text text text\n"
            "text more text...\n"
            " 1. [[DeveloperName|Name]] - "
            "([[http://qa.debian.org/developer.php?"
            "login=other|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
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
        self.assertTrue(d.is_debian_maintainer)
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
        ContributorEmail.objects.create(email='dummy@debian.org')
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
        self.assertTrue(d.is_debian_maintainer)
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('pts.core.utils.http.requests')
    def test_developer_update_dm_list(self, mock_requests):
        """
        Tests updating the DM list when one of the developers has changes in
        the allowed packages list.
        """
        # Set up a Debian developer that is already in the NMU list.
        email = ContributorEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         is_debian_maintainer=True,
                                         allowed_packages=['one'])

        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
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
        email = ContributorEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         is_debian_maintainer=True,
                                         allowed_packages=['one'])

        self.set_mock_response(mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <different-developer@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n"
        )

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
        # The developer is no longer a debian maintainer
        self.assertFalse(d.is_debian_maintainer)


class DebianContributorExtraTest(TestCase):
    def test_maintainer_extra(self):
        email = ContributorEmail.objects.create(email='dummy@debian.org')
        d = DebianContributor.objects.create(email=email,
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
        d.is_debian_maintainer = True
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
        email = ContributorEmail.objects.create(email='dummy@debian.org')
        d = DebianContributor.objects.create(email=email,
                                             agree_with_low_threshold_nmu=True)

        # Only in NMU list - no extra data when the developer in displayed as
        # an uploader.
        self.assertIsNone(get_uploader_extra('dummy@debian.org'))
        # The developer is now in the DM list
        d.is_debian_maintainer = True
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


@override_settings(PTS_VENDOR_RULES='pts.vendor.debian.rules')
class RetrieveSourcesInformationDebian(TestCase):
    """
    Tests the Debian-specifi aspects of retrieving package information from a
    repository.
    """
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]

    @mock.patch('pts.core.retrieve_data.AptCache.update_repositories')
    def test_extra_source_only_ignored(self, mock_update_repositories):
        """
        Tests that the packages with the 'Extra-Source-Only' key are ignored.
        """
        sources_contents = (
            """Package: dummy-package
Binary: dummy-package-binary
Version: 1.0.0
Maintainer: Maintainer <maintainer@domain.com>
Architecture: all amd64
Files:
 22700cab41effa76f45968aeee39cdb1 3041 file.dsc

Package: src-pkg
Binary: other-package
Version: 2.2
Maintainer: Maintainer <maintainer@domain.com>
Architecture: all amd64
Extra-Source-Only: yes
Files:
 227ffeabc4357876f45968aeee39cdb1 3041 file.dsc
""")
        sources_file_path = os.path.join(os.path.dirname(__file__), 'Sources')
        with open(sources_file_path, 'w') as f:
            f.write(sources_contents)
        mock_update_repositories.return_value = (
            [(self.repository, sources_file_path)],
            []
        )
        # Sanity check - no source packages before running the task
        self.assertEqual(0, SourcePackageName.objects.count())

        run_task(UpdateRepositoriesTask)

        # Only one package exists
        self.assertEqual(1, SourcePackageName.objects.count())
        # It is the one without the Extra-Source-Only: yes
        self.assertEqual('dummy-package', SourcePackageName.objects.all()[0].name)

        os.remove(sources_file_path)


@override_settings(PTS_VENDOR_RULES='pts.vendor.debian.rules')
class DebianNewsFromEmailTest(TestCase):
    """
    Tests creating Debian-specific news from received emails.
    """
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name, version='1.0.0')
        self.message = Message()

    def set_subject(self, subject):
        if 'Subject' in self.message:
           del self.message['Subject']
        self.message['Subject'] = subject

    def add_header(self, header_name, header_value):
        self.message[header_name] = header_value

    def set_message_content(self, content):
        self.message.set_payload(content)

    def process_mail(self):
        process(force_bytes(self.message.as_string(), 'utf-8'))

    def get_accepted_subject(self, pkg, version):
        """
        Helper method returning the subject of an email notifying of a new
        source upload.
        """
        return 'Accepted {pkg} {ver} (source all)'.format(pkg=pkg, ver=version)

    def test_source_upload_news(self):
        """
        Tests the news created when a notification of a new source upload is
        received.
        """
        subject = self.get_accepted_subject(
            self.package_name, self.package.version)
        self.set_subject(subject)
        content = 'Content'
        self.set_message_content(content)

        self.process_mail()

        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.package.name, self.package.name)
        self.assertEqual(subject, news.title)
        self.assertIn(content, news.content)

    def test_source_upload_package_does_not_exist(self):
        """
        Tests that no news are created when the notification of a new source
        upload for a package not tracked by the PTS is received.
        """
        subject = self.get_accepted_subject('no-exist', '1.0.0')
        self.set_subject(subject)
        content = 'Content'
        self.set_message_content(content)

        self.process_mail()

        self.assertEqual(0, News.objects.count())
