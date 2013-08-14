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
from django.utils.functional import curry
from pts.mail.tests.tests_dispatch import DispatchTestHelperMixin, DispatchBaseTest
from pts.core.tests.common import make_temp_directory
from pts.core.models import ActionItem, ActionItemType
from pts.core.models import News
from pts.core.models import PackageName
from pts.core.models import SourcePackage
from pts.core.models import SourcePackageName
from pts.core.models import Repository
from pts.core.models import ContributorEmail
from pts.core.tests.common import set_mock_response
from pts.core.tasks import run_task
from pts.core.retrieve_data import UpdateRepositoriesTask
from pts.vendor.debian.rules import get_package_information_site_url
from pts.vendor.debian.rules import get_maintainer_extra
from pts.vendor.debian.rules import get_uploader_extra
from pts.vendor.debian.rules import get_developer_information_url
from pts.vendor.debian.pts_tasks import UpdateBuildLogCheckStats
from pts.vendor.debian.pts_tasks import UpdatePackageBugStats
from pts.vendor.debian.pts_tasks import RetrieveDebianMaintainersTask
from pts.vendor.debian.pts_tasks import RetrieveLowThresholdNmuTask
from pts.vendor.debian.pts_tasks import DebianWatchFileScannerUpdate
from pts.vendor.debian.pts_tasks import UpdateExcusesTask
from pts.vendor.debian.models import DebianContributor
from pts.vendor.debian.pts_tasks import UpdateLintianStatsTask
from pts.vendor.debian.models import LintianStats
from pts.mail.mail_news import process

from email.message import Message

import os
import yaml


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
    @mock.patch('pts.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer did not previously exist in the database.
        """
        set_mock_response(mock_requests,
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
        set_mock_response(mock_requests,
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
        set_mock_response(mock_requests,
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
    @mock.patch('pts.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the DM list when a new developer is to be added.
        """
        set_mock_response(mock_requests,
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
        set_mock_response(mock_requests,
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

        set_mock_response(mock_requests,
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

        set_mock_response(mock_requests,
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
    Tests the Debian-specific aspects of retrieving package information from a
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
        with make_temp_directory('-mock-repo-cache') as temp_dir_name:
            sources_file_path = os.path.join(temp_dir_name, 'Sources')
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

    def get_removed_from_testing_subject(self, pkg):
        """
        Helper method providing the subject of an email from testing watch.
        """
        return '{pkg} REMOVED from testing'.format(pkg=pkg)

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

    def test_dak_rm_news(self):
        """
        Tests that a dak rm message creates a news.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
            '{pkg} |  {ver} | source, all'
        ).format(pkg=self.package_name, ver=self.package.version)
        self.set_message_content(content)
        self.add_header('X-DAK', 'dak rm')
        self.add_header('X-Debian', 'DAK')
        sender = 'Some Sender <email@domain.com>'
        self.add_header('Sender', sender)

        self.process_mail()

        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.package.name, self.package.name)
        self.assertEqual(news.title, 'Removed {ver} from unstable'.format(
            ver=self.package.version))
        self.assertEqual(news.created_by, sender)

    def test_dak_rm_no_package(self):
        """
        Tests that a dak rm message referencing a package which the PTS does
        not track, does not create any news.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
            '{pkg} |  {ver} | source, all'
        ).format(pkg='does-not-exist', ver='1.0.0')
        self.set_message_content(content)
        self.add_header('X-DAK', 'dak rm')
        self.add_header('X-Debian', 'DAK')
        sender = 'Some Sender <email@domain.com>'
        self.add_header('Sender', sender)

        self.process_mail()

        self.assertEqual(0, News.objects.count())

    def test_dak_not_rm(self):
        """
        Tests that a message with an X-DAK header different from ``dak rm``
        does not create any news item.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
            '{pkg} |  {ver} | source, all'
        ).format(pkg=self.package_name, ver=self.package.version)
        self.set_message_content(content)
        self.add_header('X-DAK', 'dak somethingelse')
        self.add_header('X-Debian', 'DAK')
        sender = 'Some Sender <email@domain.com>'
        self.add_header('Sender', sender)

        self.process_mail()

        self.assertEqual(0, News.objects.count())

    def test_multiple_removes(self):
        """
        Tests that multiple news items are created when the dak rm message
        contains multiple remove notifications.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
        )
        content += (
            '{pkg} |  {ver} | source, all\n'
        ).format(pkg=self.package_name, ver=self.package.version)
        content += (
            '{pkg} |  {ver} | source, all\n'
        ).format(pkg=self.package_name, ver='2.0.0')
        self.set_message_content(content)
        self.add_header('X-DAK', 'dak rm')
        self.add_header('X-Debian', 'DAK')
        sender = 'Some Sender <email@domain.com>'
        self.add_header('Sender', sender)

        self.process_mail()

        self.assertEqual(2, News.objects.count())

    def test_testing_watch_news(self):
        """
        Tests that an email received from the Testing Watch is turned into a
        news item.
        """
        subject = self.get_removed_from_testing_subject(self.package_name)
        self.set_subject(subject)
        content = (
            "FYI: The status of the {pkg} source package\n"
            "in Debian's testing distribution has changed.\n\n"
            "  Previous version: 1.0.0\n"
            "  Current version: (not in testing)\n"
            "  Hint: some hint..."
        ).format(pkg=self.package_name)
        self.set_message_content(content)
        self.add_header('X-Testing-Watch-Package', self.package.name)

        self.process_mail()

        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(subject, news.title)
        self.assertIn(content, news.content)

    def test_testing_watch_package_no_exist(self):
        """
        Tests that an email received from the Testing Watch which references
        a package not tracked by the PTS does not create any news items.
        """
        subject = self.get_removed_from_testing_subject('no-exist')
        self.set_subject(subject)
        content = (
            "FYI: The status of the {pkg} source package\n"
            "in Debian's testing distribution has changed.\n\n"
            "  Previous version: 1.0.0\n"
            "  Current version: (not in testing)\n"
            "  Hint: some hint..."
        ).format(pkg='no-exist')
        self.set_message_content(content)
        self.add_header('X-Testing-Watch-Package', 'no-exist')

        self.process_mail()

        self.assertEqual(0, News.objects.count())


class UpdateLintianStatsTaskTest(TestCase):
    """
    Tests for the :class:`pts.vendor.debian.pts_tasks.UpdateLintianStatsTask` task.
    """
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

    def run_task(self):
        """
        Runs the lintian stats update task.
        """
        task = UpdateLintianStatsTask()
        task.execute()

    def assert_correct_category_stats(self, stats, expected_stats):
        """
        Helper method which asserts that the given stats match the expected stats.

        :param stats: Mapping category names to count
        :type stats: dict
        :param expected_stats: A list of counts as given by the Web lintian
            resource
        :type expected_stats: list
        """
        categories = (
            'errors',
            'warnings',
            'pedantics',
            'experimentals',
            'overriddens',
        )
        for category, count in zip(categories, expected_stats):
            self.assertEqual(stats[category], count)

    def assert_action_item_warnings_and_errors_count(self, item, errors=0, warnings=0):
        """
        Helper method which checks if an instance of :class:`pts.core.ActionItem`
        contains the given error and warning count in its extra_data.
        """
        self.assertEqual(item.extra_data['errors'], errors)
        self.assertEqual(item.extra_data['warnings'], warnings)

    @mock.patch('pts.core.utils.http.requests')
    def test_stats_created(self, mock_requests):
        """
        Tests that stats are created for a package that previously did not have
        any lintian stats.
        """
        set_mock_response(mock_requests, text="dummy-package 1 2 3 4 5 6")

        self.run_task()

        # The stats have been created
        self.assertEqual(1, LintianStats.objects.count())
        # They are associated with the correct package.
        stats = LintianStats.objects.all()[0]
        self.assertEqual(stats.package.name, 'dummy-package')
        # The category counts themselves are correct
        self.assert_correct_category_stats(stats.stats, [1, 2, 3, 4, 5, 6])

    @mock.patch('pts.core.utils.http.requests')
    def test_stats_updated(self, mock_requests):
        """
        Tests that when a package already had associated linian stats, they are
        correctly updated after running the task.
        """
        set_mock_response(mock_requests, text="dummy-package 6 5 4 3 2 1")
        # Create the pre-existing stats for the package
        LintianStats.objects.create(
            package=self.package_name, stats=[1, 2, 3, 4, 5, 6])

        self.run_task()

        # Still only one lintian stats object
        self.assertEqual(1, LintianStats.objects.count())
        # The package is still correct
        stats = LintianStats.objects.all()[0]
        self.assertEqual(stats.package.name, 'dummy-package')
        # The stats have been updated
        self.assert_correct_category_stats(stats.stats, [6, 5, 4, 3, 2, 1])

    @mock.patch('pts.core.utils.http.requests')
    def test_stats_created_multiple_packages(self, mock_requests):
        """
        Tests that stats are correctly creatd when there are stats for
        multiple packages in the response.
        """
        # Create a second package.
        SourcePackageName.objects.create(name='other-package')
        response = (
            "dummy-package 6 5 4 3 2 1\n"
            "other-package 1 2 3 4 5 6"
        )
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # Stats created for both packages
        self.assertEqual(2, LintianStats.objects.count())
        all_names = [stats.package.name for stats in LintianStats.objects.all()]
        self.assertIn('dummy-package', all_names)
        self.assertIn('other-package', all_names)

    @mock.patch('pts.core.utils.http.requests')
    def test_unknown_package(self, mock_requests):
        """
        Tests that when an unknown package is encountered, no stats are created.
        """
        set_mock_response(mock_requests, text="no-exist 1 2 3 4 5 6")

        self.run_task()

        # There are no stats
        self.assertEqual(0, LintianStats.objects.count())

    @mock.patch('pts.core.utils.http.requests')
    def test_parse_error(self, mock_requests):
        """
        Tests that when a parse error is encountered for a single package, it
        is skipped without affected the rest of the packages in the response.
        """
        # Create a second package.
        SourcePackageName.objects.create(name='other-package')
        response = (
            "dummy-package 6 5 4 3 2 1\n"
            "other-package 1 2 a 4 5 6"
        )
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # Only one package has stats
        self.assertEqual(1, LintianStats.objects.count())
        stats = LintianStats.objects.all()[0]
        self.assertEqual(stats.package.name, 'dummy-package')

    @mock.patch('pts.core.utils.http.requests')
    def test_correct_url_used(self, mock_requests):
        """
        Tests that lintian stats are retrieved from the correct URL.
        """
        self.run_task()

        # We only care about the URL used, not the headers or other arguments
        self.assertEqual(
            mock_requests.get.call_args[0][0],
            'http://lintian.debian.org/qa-list.txt')

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_created_errors(self, mock_requests):
        """
        Tests that an action item is created when the package has errors.
        """
        errors, warnings = 2, 0
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The correct number of errors and warnings is stored in the item
        item = ActionItem.objects.all()[0]
        self.assert_action_item_warnings_and_errors_count(item, errors, warnings)
        # It has the correct type
        self.assertEqual(
            item.item_type.type_name,
            UpdateLintianStatsTask.ACTION_ITEM_TYPE_NAME)
        # It is a high severity issue
        self.assertEqual('high', item.get_severity_display())
        # Correct full description template
        self.assertEqual(
            item.full_description_template,
            UpdateLintianStatsTask.ITEM_FULL_DESCRIPTION_TEMPLATE)


    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_created_warnings(self, mock_requests):
        """
        Tests that an action item is created when the package has warnings.
        """
        errors, warnings = 0, 2
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The correct number of errors and warnings is stored in the item
        item = ActionItem.objects.all()[0]
        self.assert_action_item_warnings_and_errors_count(item, errors, warnings)
        # It is a normal severity issue
        self.assertEqual('normal', item.get_severity_display())

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_created_errors_and_warnings(self, mock_requests):
        """
        Tests that an action item is created when the package has errors and
        warnings.
        """
        errors, warnings = 2, 2
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The item is linked to the correct package
        item = ActionItem.objects.all()[0]
        self.assertEqual(item.package.name, self.package_name.name)
        # The correct number of errors and warnings is stored in the item
        self.assert_action_item_warnings_and_errors_count(item, errors, warnings)
        # It is a high severity issue since it contains both errors and warnings
        self.assertEqual('high', item.get_severity_display())

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_not_created(self, mock_requests):
        """
        Tests that no action item is created when the package has no errors or
        warnings.
        """
        response = "dummy-package 0 0 5 4 3 2"
        set_mock_response(mock_requests, text=response)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_removed(self, mock_requests):
        """
        Tests that a previously existing action item is removed if the updated
        stats no longer contain errors or warnings.
        """
        # Make sure an item exists for the package
        item_type, _ = ActionItemType.objects.get_or_create(
            type_name=UpdateLintianStatsTask.ACTION_ITEM_TYPE_NAME)
        ActionItem.objects.create(
            package=self.package_name,
            item_type=item_type,
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})
        response = "dummy-package 0 0 5 4 3 2"
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # There are no action items any longer.
        self.assertEqual(0, self.package_name.action_items.count())

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_removed_no_data(self, mock_requests):
        """
        Tests that a previously existing action item is removed when the
        updated stats no longer contain any information for the package.
        """
        item_type, _ = ActionItemType.objects.get_or_create(
            type_name=UpdateLintianStatsTask.ACTION_ITEM_TYPE_NAME)
        ActionItem.objects.create(
            package=self.package_name,
            item_type=item_type,
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})
        response = "some-package 0 0 5 4 3 2"
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # There are no action items any longer.
        self.assertEqual(0, self.package_name.action_items.count())

    @mock.patch('pts.core.utils.http.requests')
    def test_action_item_created_multiple_packages(self, mock_requests):
        """
        Tests that action items are created correctly when there are stats
        for multiple different packages in the response.
        """
        other_package = PackageName.objects.create(name='other-package')
        errors, warnings = (2, 0), (0, 2)
        response = (
            "dummy-package {err1} {warn1} 0 0 0 0\n"
            "other-package {err2} {warn2} 0 0 0 0"
            "some-package 0 0 0 0 0 0".format(
                err1=errors[0], warn1=warnings[0],
                err2=errors[1], warn2=warnings[1])
        )
        set_mock_response(mock_requests, text=response)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action items are created for two packages.
        self.assertEqual(1, self.package_name.action_items.count())
        self.assertEqual(1, other_package.action_items.count())
        # The items contain correct data.
        item = self.package_name.action_items.all()[0]
        self.assert_action_item_warnings_and_errors_count(item, errors[0], warnings[0])
        item = other_package.action_items.all()[0]
        self.assert_action_item_warnings_and_errors_count(item, errors[1], warnings[1])

    @mock.patch('pts.core.utils.http.requests')
    def test_update_does_not_affect_other_item_types(self, mock_requests):
        """
        Tests that running an update of lintian stats does not cause other
        package categories to be removed.
        """
        # Create an item for the package with a different type.
        other_type = ActionItemType.objects.create(type_name='other-type')
        ActionItem.objects.create(
            item_type=other_type,
            package=self.package_name,
            short_description='Desc.')
        errors, warnings = 2, 0
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)
        # Sanity check: exactly one action item in the beginning
        self.assertEqual(1, ActionItem.objects.count())

        self.run_task()

        # An action item is created.
        self.assertEqual(2, self.package_name.action_items.count())


class DebianBugActionItemsTests(TestCase):
    """
    Tests the creation of :class:`pts.core.ActionItem` instances based on
    Debian bug stats.
    """
    @staticmethod
    def stub_tagged_bugs(tag, user=None, help_bugs=None, gift_bugs=None):
        if tag == 'help':
            return help_bugs
        elif tag == 'gift':
            return gift_bugs

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self.task = UpdatePackageBugStats()
        self.udd_bugs = {}
        self.help_bugs = {}
        self.gift_bugs = {}
        # Stub the data providing methods
        self.task._get_udd_bug_stats = mock.MagicMock(
            return_value=self.udd_bugs)
        self.task._get_tagged_bug_stats = mock.MagicMock(
            side_effect=curry(
                DebianBugActionItemsTests.stub_tagged_bugs,
                help_bugs=self.help_bugs,
                gift_bugs=self.gift_bugs))
        # Ignore binary package bugs for action item tests.
        self.task.update_binary_bugs = mock.MagicMock()

    def run_task(self):
        self.task.execute()

    def add_patch_bug(self, package, bug_count):
        """
        Helper method adding patch bugs to the stub return value.
        """
        self.add_udd_bug_category(package, 'patch', bug_count)

    def add_udd_bug_category(self, package, category, bug_count):
        """
        Adds stats for a bug category to the stub response, as if the category
        was found in the UDD bug stats.
        """
        self.udd_bugs.setdefault(package, [])
        self.udd_bugs[package].append({
            'category_name': category,
            'bug_count': bug_count,
        })

    def add_help_bug(self, package, bug_count):
        """
        Helper method adding help bugs to the stub return value.
        """
        self.help_bugs[package] = bug_count

    def get_patch_action_type(self):
        """
        Helper method returning a :class:`pts.core.models.ActionItemType` for
        the debian patch bug warning action item type.
        """
        return ActionItemType.objects.get_or_create(
            type_name=UpdatePackageBugStats.PATCH_BUG_ACTION_ITEM_TYPE_NAME)[0]

    def get_help_action_type(self):
        """
        Helper method returning a :class:`pts.core.models.ActionItemType` for
        the debian help bug warning action item type.
        """
        return ActionItemType.objects.get_or_create(
            type_name=UpdatePackageBugStats.HELP_BUG_ACTION_ITEM_TYPE_NAME)[0]


    def test_patch_bug_action_item(self):
        """
        Tests that an action item is created when there are bugs tagged patch.
        """
        bug_count = 2
        self.add_patch_bug(self.package_name.name, bug_count)
        # Sanity check: no items
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # The item is of the correct type
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            item.item_type.type_name, 
            UpdatePackageBugStats.PATCH_BUG_ACTION_ITEM_TYPE_NAME)
        # The item references the correct package.
        self.assertEqual(item.package.name, self.package_name.name)
        # It contains the extra data
        self.assertEqual(item.extra_data['bug_count'], bug_count)
        # Correct full description template
        self.assertEqual(
            item.full_description_template,
            UpdatePackageBugStats.PATCH_ITEM_FULL_DESCRIPTION_TEMPLATE)

    def test_patch_bug_action_item_updated(self):
        """
        Tests that an already existing action item is updated after running the
        task.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_patch_action_type(),
            short_description="Desc")
        bug_count = 2
        self.add_patch_bug(self.package_name.name, bug_count)

        self.run_task()

        # Still only one item...
        self.assertEqual(1, self.package_name.action_items.count())
        # It contains updated data
        item = self.package_name.action_items.all()[0]
        self.assertEqual(item.extra_data['bug_count'], bug_count)

    def test_patch_bug_action_item_removed(self):
        """
        Tests that an already existing action item is removed after the update
        does not contain any more bugs in the patch category.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_patch_action_type(),
            short_description="Desc")
        bug_count = 0
        self.add_patch_bug(self.package_name.name, bug_count)

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_patch_bug_action_item_removed_no_data(self):
        """
        Tests that an already existing action item is removed if the update
        does not give any stats at all.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_patch_action_type(),
            short_description="Desc")

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_patch_bug_action_item_removed_no_data_for_category(self):
        """
        Tests that an already existing action item is removed if the update
        does not contain stats for the patch category, but does contain
        stats for different categories.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_patch_action_type(),
            short_description="Desc")
        self.add_udd_bug_category(self.package_name.name, 'normal', 1)

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_help_bug_action_item(self):
        """
        Tests that an action item is created when there are bugs tagged help.
        """
        bug_count = 2
        self.add_help_bug(self.package_name.name, bug_count)
        # Sanity check: no items
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # The item references the correct package.
        item = ActionItem.objects.all()[0]
        self.assertEqual(item.package.name, self.package_name.name)
        # It contains the extra data
        self.assertEqual(item.extra_data['bug_count'], bug_count)
        # Correct full description template
        self.assertEqual(
            item.full_description_template,
            UpdatePackageBugStats.HELP_ITEM_FULL_DESCRIPTION_TEMPLATE)

    def test_help_action_item_updated(self):
        """
        Tests that an already existing action item is updated after running the
        task.
        """
        # Create a previously existing action item for the help type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_help_action_type(),
            short_description="Desc")
        bug_count = 2
        self.add_help_bug(self.package_name.name, bug_count)

        self.run_task()

        # Still only one item...
        self.assertEqual(1, self.package_name.action_items.count())
        # It contains updated data
        item = self.package_name.action_items.all()[0]
        self.assertEqual(item.extra_data['bug_count'], bug_count)

    def test_help_bug_action_item_removed(self):
        """
        Tests that an already existing action item is removed after the update
        does not contain any more bugs in the help category.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_help_action_type(),
            short_description="Desc")
        bug_count = 0
        self.add_help_bug(self.package_name.name, bug_count)

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_help_bug_action_item_removed_no_data(self):
        """
        Tests that an already existing action item is removed if the update
        does not give any stats at all.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_help_action_type(),
            short_description="Desc")

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_help_bug_action_item_removed_no_data_for_category(self):
        """
        Tests that an already existing action item is removed if the update
        does not contain stats for the help category, but does contain
        stats for different categories.
        """
        # Create a previously existing action item for the patch type.
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_help_action_type(),
            short_description="Desc")
        self.add_udd_bug_category(self.package_name.name, 'normal', 1)

        self.run_task()

        # No more action items.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_multiple_action_items_for_package(self):
        """
        Tests that multiple :class:`pts.core.models.ActionItem` instances are
        created for a package if it contains both patch and help bugs.
        """
        patch_bug_count = 2
        help_bug_count = 5
        self.add_patch_bug(self.package_name.name, patch_bug_count)
        self.add_help_bug(self.package_name.name, help_bug_count)
        # Sanity check: no action items
        self.assertEqual(0, self.package_name.action_items.count())

        self.run_task()

        # Two action items.
        self.assertEqual(2, self.package_name.action_items.count())
        # Correct respective bug counts
        patch_item = self.package_name.action_items.get(
            item_type=self.get_patch_action_type())
        self.assertEqual(patch_item.extra_data['bug_count'], patch_bug_count)
        help_item = self.package_name.action_items.get(
            item_type=self.get_help_action_type())
        self.assertEqual(help_item.extra_data['bug_count'], help_bug_count)

    def test_action_item_for_multiple_packages(self):
        """
        Tests that action items are correctly created when more than one
        package has bug warnings.
        """
        stats = (
            (2, 5),
            (1, 1),
        )
        packages = (
            self.package_name,
            PackageName.objects.create(name='other-package'),
        )
        # Create the stub response
        for package, bug_stats in zip(packages, stats):
            patch_bug_count, help_bug_count = bug_stats
            self.add_patch_bug(package.name, patch_bug_count)
            self.add_help_bug(package.name, help_bug_count)

        self.run_task()

        # Each package has two action items
        for package, bug_stats in zip(packages, stats):
            patch_bug_count, help_bug_count = bug_stats
            self.assertEqual(2, package.action_items.count())
            patch_item = package.action_items.get(
                item_type=self.get_patch_action_type())
            self.assertEqual(patch_item.extra_data['bug_count'], patch_bug_count)
            help_item = package.action_items.get(
                item_type=self.get_help_action_type())
            self.assertEqual(help_item.extra_data['bug_count'], help_bug_count)


class UpdateExcusesTaskActionItemTest(TestCase):
    """
    Tests for the creating of action items by the
    :class:`pts.vendor.debian.pts_tasks.UpdateExcusesTask`.
    """
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self.task = UpdateExcusesTask()
        self.task._get_update_excuses_content = mock.MagicMock()

    def run_task(self):
        self.task.execute()

    def get_test_file_path(self, file_name):
        return os.path.join(os.path.dirname(__file__), 'tests-data', file_name)

    def set_update_excuses_content(self, content):
        """
        Sets the stub content of the update_excuses.html that the task will
        have access to.
        """
        self.task._get_update_excuses_content.return_value = iter(
            content.splitlines())

    def set_update_excuses_content_from_file(self, file_name):
        """
        Sets the stub content of the update_excuses.html that the task will
        have access to based on the content of the test file with the given
        name.
        """
        with open(self.get_test_file_path(file_name), 'r') as f:
            content = f.read()

        self.set_update_excuses_content(content)

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdateExcusesTask.ACTION_ITEM_TYPE_NAME)[0]

    def test_action_item_created(self):
        """
        Tests that an action item is created when a package has not moved to
        testing after the allocated period.
        """
        self.set_update_excuses_content_from_file('update_excuses-1.html')
        # Sanity check: no action items currently
        self.assertEqual(0, ActionItem.objects.count())
        expected_data = {
            'age': '20',
            'limit': '10',
        }

        self.run_task()

        # An action item is created
        self.assertEqual(1, ActionItem.objects.count())
        # Correct type
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            item.item_type.type_name,
            UpdateExcusesTask.ACTION_ITEM_TYPE_NAME)
        # Correct extra data
        self.assertDictEqual(item.extra_data, expected_data)
        # Correct template used
        self.assertEqual(
            item.full_description_template,
            UpdateExcusesTask.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def test_action_item_not_created(self):
        """
        Tests that an action item is not created when the allocated time period
        has not yet passed.
        """
        self.set_update_excuses_content_from_file('update_excuses-2.html')
        # Sanity check: no action items currently
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Still no action items
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_removed(self):
        """
        Tests that an already existing action item is removed when the package
        is no longer problematic.
        """
        # Create an item for the package prior to running the task
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        self.set_update_excuses_content_from_file('update_excuses-2.html')

        self.run_task()

        # The action item is removed.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_updated(self):
        """
        Tests that an already existing action item's extra data is updated.
        """
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        self.set_update_excuses_content_from_file('update_excuses-1.html')
        expected_data = {
            'age': '20',
            'limit': '10',
        }

        self.run_task()

        # Still just one item
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated?
        item = ActionItem.objects.all()[0]
        self.assertDictEqual(expected_data, item.extra_data)


class UpdateBuildLogCheckStatsActionItemTests(TestCase):
    """
    Tests that :class:`pts.core.models.ActionItem` instances are correctly
    created when running the
    :class:`pts.vendor.debian.pts_tasks.UpdateBuildLogCheckStats` task.
    """
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self.task = UpdateBuildLogCheckStats()
        self.task._get_buildd_content = mock.MagicMock()

    def set_buildd_content(self, content):
        """
        Sets the stub value for buildd data which the task will see once it
        runs.
        """
        self.task._get_buildd_content.return_value = content

    def run_task(self):
        self.task.execute()

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdateBuildLogCheckStats.ACTION_ITEM_TYPE_NAME)[0]

    def test_action_item_created(self):
        """
        Tests that a new action item is created when a package has errors
        or warnings.
        """
        expected_data = {
            'errors': 1,
            'warnings': 2,
        }
        self.set_buildd_content("dummy-package|1|2|0|0")
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created
        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            item.item_type.type_name,
            self.get_action_item_type().type_name)
        # Contains the correct extra data
        self.assertDictEqual(expected_data, item.extra_data)
        # The severity is high since it contains both errors and warnings
        self.assertEqual('high', item.get_severity_display())
        # Full description template correct
        self.assertEqual(
            item.full_description_template,
            UpdateBuildLogCheckStats.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def test_action_item_warning_low_severity(self):
        """
        Tests that action items have low severity if the package only has
        warnings.
        """
        self.set_buildd_content("dummy-package|0|1|0|0")

        self.run_task()

        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        self.assertEqual('low', item.get_severity_display())

    def test_action_item_error_high_severity(self):
        """
        Tests that action items have high severity if the package has only
        errors.
        """
        self.set_buildd_content("dummy-package|1|0|0|0")

        self.run_task()

        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        self.assertEqual('high', item.get_severity_display())

    def test_action_item_not_created(self):
        """
        Tests that a new action item is not created when the package does not
        have any errors or warnings.
        """
        # Package has some buildd stats, but no warnings or errors
        self.set_buildd_content("dummy-package|0|0|1|1")
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # No item created.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_updated(self):
        """
        Tests that an already existing action item is updated when the task
        runs.
        """
        # Create an action item which exists before that task is run
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        expected_data = {
            'errors': 1,
            'warnings': 2,
        }
        self.set_buildd_content("dummy-package|1|2|1|1")

        self.run_task()

        # Stll just one action item
        self.assertEqual(1, ActionItem.objects.count())
        # The extra data has been updated?
        item = ActionItem.objects.all()[0]
        self.assertEqual(expected_data, item.extra_data)

    def test_action_item_removed(self):
        """
        Tests that an already existing action item is removed when the package
        no longer has any warnings or errors (but still has buildd stats).
        """
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        self.set_buildd_content("dummy-package|0|0|1|1")

        self.run_task()

        # No longer has any action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_removed_all_stats(self):
        """
        Tests that an already existing action item is removed when the package
        no longer has any buildd stats.
        """
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        self.set_buildd_content("other-package|0|1|1|1")

        self.run_task()

        # No longer has any action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_multiple_packages(self):
        """
        Tests that an action item is correctly created for multple packages
        found in the buildd response.
        """
        other_package = SourcePackageName.objects.create(name='other-package')
        self.set_buildd_content(
            "other-package|0|1|1|1\n"
            "dummy-package|1|1|0|0")

        self.run_task()

        # Both packages have an action item
        self.assertEqual(1, other_package.action_items.count())
        self.assertEqual(1, self.package_name.action_items.count())


class DebianWatchFileScannerUpdateTests(TestCase):
    """
    Tests that :class:`pts.core.models.ActionItem` instances are correctly
    created when running the
    :class:`pts.vendor.debian.pts_tasks.UpdateBuildLogCheckStats` task.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = DebianWatchFileScannerUpdate()
        # Stub the data providing methods: no content by default
        self.task._get_udd_dehs_content = mock.MagicMock(return_value='')
        self.task._get_watch_broken_content = mock.MagicMock(return_value='')

    def run_task(self):
        self.task.execute()

    def set_udd_dehs_content(self, content):
        """
        Sets the stub content returned to the task as UDD DEHS data.
        :param content: A list of dicts of information returned by UDD. The
            content given as a response to the task will be the YAML encoded
            representation of this list.
        """
        self.task._get_udd_dehs_content.return_value = yaml.safe_dump(
            content,
            default_flow_style=False)

    def set_watch_broken_content(self, packages):
        """
        Sets the stub content returned to the task as the content of the
        watch-broken.txt file.

        :param packages: A list of packages which should be returned to
            indicate a broken watch file.
        """
        self.task._get_watch_broken_content.return_value = '\n'.join(packages)

    def get_item_type(self, type_name):
        """
        Helper method returning a :class:`pts.core.models.ActionItemType`
        instance with the given type name.
        """
        return ActionItemType.objects.get_or_create(type_name=type_name)[0]

    def test_new_upstream_version_item_created(self):
        """
        Tests that a new upstream version item is created when a package has
        a newer upstream version according to DEHS data retrieved from UDD.
        """
        version = '2.0.0'
        url = 'http://some.url.here'
        dehs = [
            {
                'package': self.package.name,
                'status': 'Newer version available',
                'upstream-url': url,
                'upstream-version': version,
            }
        ]
        self.set_udd_dehs_content(dehs)
        # Sanity check: no action items
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Action item correct type
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            'new-upstream-version',
            item.item_type.type_name)
        # Correct full description template
        self.assertEqual(
            DebianWatchFileScannerUpdate.ACTION_ITEM_TEMPLATES['new-upstream-version'],
            item.full_description_template)
        # Correct extra data
        expected_data = {
            'upstream_version': version,
            'upstream_url': url,
        }
        self.assertDictEqual(expected_data, item.extra_data)
        # High severity item
        self.assertEqual('high', item.get_severity_display())

    def test_new_upstream_version_item_removed(self):
        """
        Tests that a new upstream version item is removed when a package no
        longer has a newer upstream version.
        """
        # Make sure the package previously had an action item.
        item_type = self.get_item_type('new-upstream-version')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc')
        dehs = []
        self.set_udd_dehs_content(dehs)

        self.run_task()

        # Action item removed
        self.assertEqual(0, ActionItem.objects.count())

    def test_new_upstream_version_item_updated(self):
        """
        Tests that a new upstream version action item is updated when there is
        newer data available for the package.
        """
        item_type = self.get_item_type('new-upstream-version')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc')
        url = 'http://some.url'
        version = '2.0.0'
        dehs = [
            {
                'package': self.package.name,
                'status': 'Newer version available',
                'upstream-url': url,
                'upstream-version': version,
            }
        ]
        self.set_udd_dehs_content(dehs)

        self.run_task()

        # Still the one action item
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated
        item = ActionItem.objects.all()[0]
        expected_data = {
            'upstream_url': url,
            'upstream_version': version,
        }
        self.assertEqual(expected_data, item.extra_data)

    def test_watch_failure_item_created(self):
        """
        Tests that a ``watch-failure`` action item is created when the package
        contains a watch failure as indicated by DEHS data returned by UDD.
        """
        version = '2.0.0'
        url = 'http://some.url.here'
        warning = 'Some warning goes here...'
        dehs = [
            {
                'package': self.package.name,
                'status': 'up to date',
                'upstream-url': url,
                'upstream-version': version,
                'warnings': warning,
            }
        ]
        self.set_udd_dehs_content(dehs)
        # Sanity check: no action items
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Action item correct type
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            'watch-failure',
            item.item_type.type_name)
        # Correct full description template
        self.assertEqual(
            DebianWatchFileScannerUpdate.ACTION_ITEM_TEMPLATES['watch-failure'],
            item.full_description_template)
        # Correct extra data
        expected_data = {
            'warning': warning,
        }
        self.assertDictEqual(expected_data, item.extra_data)
        # High severity item
        self.assertEqual('high', item.get_severity_display())

    def test_watch_failure_item_removed(self):
        """
        Tests that a ``watch-failure`` item is removed when a package no longer
        has the issue.
        """
        # Make sure the package previously had an action item.
        item_type = self.get_item_type('watch-failure')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc')
        dehs = []
        self.set_udd_dehs_content(dehs)

        self.run_task()

        # Action item removed
        self.assertEqual(0, ActionItem.objects.count())

    def test_watch_failure_item_updated(self):
        """
        Tests that a ``watch-failure`` action item is updated when there is
        newer data available for the package.
        """
        item_type = self.get_item_type('watch-failure')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc',
            extra_data={
                'warning': 'Old warning',
            })
        version = '2.0.0'
        url = 'http://some.url.here'
        warning = 'Some warning goes here...'
        dehs = [
            {
                'package': self.package.name,
                'status': 'up to date',
                'upstream-url': url,
                'upstream-version': version,
                'warnings': warning,
            }
        ]
        self.set_udd_dehs_content(dehs)

        self.run_task()

        # Still the one action item
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated
        item = ActionItem.objects.all()[0]
        expected_data = {
            'warning': warning,
        }
        self.assertEqual(expected_data, item.extra_data)

    def test_no_dehs_data(self):
        """
        Tests that when there is no DEHS data at all, no action items are created.
        """
        self.run_task()

        self.assertEqual(0, ActionItem.objects.count())

    def test_watch_broken_item_created(self):
        """
        Tests that a ``watch-file-broken`` action item is created when the package
        contains a watch failure as indicated by the watch-broken.txt file.
        """
        self.set_watch_broken_content([self.package.name])
        # Sanity check: no action items
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Action item correct type
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            'watch-file-broken',
            item.item_type.type_name)
        # Correct full description template
        self.assertEqual(
            DebianWatchFileScannerUpdate.ACTION_ITEM_TEMPLATES['watch-file-broken'],
            item.full_description_template)
        # Correct extra data
        self.assertIsNone(item.extra_data)
        # Low severity item
        self.assertEqual('low', item.get_severity_display())

    def test_watch_broken_item_removed(self):
        """
        Tests that a ``watch-file-broken`` item is removed when a package no longer
        has the issue.
        """
        # Make sure the package previously had an action item.
        item_type = self.get_item_type('watch-file-broken')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc')

        self.run_task()

        # Action item removed
        self.assertEqual(0, ActionItem.objects.count())

    def test_watch_broken_item_updated(self):
        """
        Tests that a ``watch-file-broken`` action item is updated when there is
        newer data available for the package.
        """
        item_type = self.get_item_type('watch-file-broken')
        ActionItem.objects.create(
            package=self.package,
            item_type=item_type,
            short_description='Desc',
            extra_data={
                'key': 'value',
            })
        self.set_watch_broken_content([self.package.name])

        self.run_task()

        # Still the one action item
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated
        item = ActionItem.objects.all()[0]
        self.assertIsNone(item.extra_data)
