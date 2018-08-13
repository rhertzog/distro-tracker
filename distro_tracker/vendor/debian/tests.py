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
Tests for Debian-specific modules/functionality of Distro Tracker.
"""

import io
import json
import logging
import os
import yaml
import gzip

from email.message import Message
from unittest import mock

from bs4 import BeautifulSoup as soup
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.functional import curry

from distro_tracker.accounts.models import User, UserEmail
from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
    BinaryPackageName,
    EmailSettings,
    Keyword,
    News,
    PackageBugStats,
    PackageData,
    PackageName,
    PseudoPackageName,
    Repository,
    SourcePackage,
    SourcePackageName,
    Subscription,
)
from distro_tracker.core.package_tables import BugStatsTableField
from distro_tracker.core.retrieve_data import UpdateRepositoriesTask
from distro_tracker.core.tasks import run_task
from distro_tracker.core.utils.email_messages import message_from_bytes
from distro_tracker.core.utils.packages import package_url
from distro_tracker.mail.mail_news import process
from distro_tracker.mail.tests.tests_dispatch import DispatchTestHelperMixin
from distro_tracker.test import SimpleTestCase, TemplateTestsMixin, TestCase
from distro_tracker.test.utils import make_temp_directory, set_mock_response
from distro_tracker.vendor.debian.management.commands.\
    tracker_import_old_subscriber_dump \
    import Command as ImportOldSubscribersCommand
from distro_tracker.vendor.debian.management.commands.\
    tracker_import_old_tags_dump \
    import Command as ImportOldTagsCommand
from distro_tracker.vendor.debian.models import (
    DebianContributor,
    LintianStats,
    UbuntuPackage
)
from distro_tracker.vendor.debian.rules import (
    classify_message,
    get_developer_information_url,
    get_maintainer_extra,
    get_package_information_site_url,
    get_uploader_extra,
    additional_prefetch_related_lookups,
    get_vcs_data,
)
from distro_tracker.vendor.debian.sso_auth import DebianSsoUserBackend
from distro_tracker.vendor.debian.tracker_package_tables import (
    UpstreamTableField,
)
from distro_tracker.vendor.debian.tracker_tasks import (
    DebianWatchFileScannerUpdate,
    RetrieveDebianMaintainersTask,
    RetrieveLowThresholdNmuTask,
    TagPackagesWithRcBugs,
    UpdateAppStreamStatsTask,
    UpdateAutoRemovalsStatsTask,
    UpdateBuildLogCheckStats,
    UpdateBuildReproducibilityTask,
    UpdateDebciStatusTask,
    UpdateDebianDuckTask,
    UpdateExcusesTask,
    UpdateLintianStatsTask,
    UpdateNewQueuePackages,
    UpdatePackageBugStats,
    UpdatePackageScreenshotsTask,
    UpdatePiuPartsTask,
    UpdateSecurityIssuesTask,
    UpdateUbuntuStatsTask,
    UpdateVcsWatchTask,
    UpdateWnppStatsTask
)
from distro_tracker.vendor.debian.views import CodeSearchView

logging.disable(logging.CRITICAL)


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class DispatchDebianSpecificTest(TestCase, DispatchTestHelperMixin):

    """
    Tests Debian-specific keyword classification.
    """

    GIT_HEADERS = ('X-Git-Repo', 'X-GitLab-Project')

    def setUp(self):
        self.clear_message()
        self.from_email = 'dummy-email@domain.com'
        self.set_package_name('dummy-package')
        self.add_header('From', 'Real Name <{from_email}>'.format(
            from_email=self.from_email))
        self.add_header('Subject', 'Some subject')
        self.set_message_content('message content')

        self.package = PackageName.objects.create(
            source=True,
            name=self.package_name)

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
            ('X-Debian', 'tracker.debian.org'),
        ]
        self.subscribe_user_to_package('user@domain.com', self.package_name)

        self.run_dispatch()

        self.assert_all_headers_found(expected_headers)

    def run_classify(self, package=None, keyword=None):
        return classify_message(self.message, package, keyword)

    def _test_classify_converts_legacy_keyword(self, keyword, expected):
        package, new_keyword = self.run_classify('foo', keyword)
        self.assertEqual(new_keyword, expected)

    def test_classify_converts_legacy_keyword(self):
        conversions = {
            'cvs': 'vcs',
            'ddtp': 'translation',
            'buildd': 'build',
            'katie-other': 'archive',
        }
        for old, new in conversions.items():
            self._test_classify_converts_legacy_keyword(old, new)

    def define_bts_mail(self, package, message='report 12345', source=None):
        self.set_header('X-Loop', 'owner@bugs.debian.org')
        self.set_header('X-Debian-PR-Message', message)
        self.set_header('X-Debian-PR-Package', package)
        if source:
            self.set_header('X-Debian-PR-Source', source)

    def test_classify_bts_mail_traffic_of_normal_package(self):
        self.define_bts_mail('pkg-binary', source='pkg-source')
        pkg, _ = self.run_classify()
        self.assertEqual(pkg, 'pkg-source')

    def test_classify_bts_mail_traffic_of_pseudo_package(self):
        self.define_bts_mail('pkg-pseudo', source=None)
        pkg, _ = self.run_classify()
        self.assertEqual(pkg, 'pkg-pseudo')

    def test_classify_bts_mail_traffic_with_correct_keyword(self):
        self.define_bts_mail('foo', message='followup 12345')
        pkg, keyword = self.run_classify()
        self.assertEqual(keyword, 'bts')

    def test_classify_bts_control_traffic_with_correct_keyword(self):
        self.define_bts_mail('foo', message='transcript')
        pkg, keyword = self.run_classify()
        self.assertEqual(keyword, 'bts-control')

    def test_classify_bts_mail_on_multiple_packages_with_suggestion(self):
        """
        Suggested package takes precedence when the mail header
        mentions multiple packages.
        """
        self.define_bts_mail('pkg-binary', source='a b c d')
        pkg, keyword = self.run_classify('pkg-source')
        self.assertEqual(pkg, 'pkg-source')

    def test_classify_bts_mail_on_multiple_packages_without_suggestion(self):
        """
        Since we have no suggested package, we assume all packages need
        to be informed and we return a list
        """
        self.define_bts_mail('pkg-binary', source=' a b c d ')
        pkg, keyword = self.run_classify()
        self.assertListEqual(pkg, ['a', 'b', 'c', 'd'])

    def test_classify_bts_mail_does_not_override_suggestion(self):
        """
        This case ensures that we can send a X-Debbugs-Cc copy of a bug report
        to another maintainer via pkg-foo@packages.debian.org and still get the
        bug forwarded to the pkg-foo subscribers under the contact keyword.
        """
        self.define_bts_mail('release.debian.org', source=None)
        pkg, keyword = self.run_classify('pkg-foo', 'contact')
        self.assertEqual(pkg, 'pkg-foo')
        self.assertEqual(keyword, 'contact')

    def define_dak_mail(self, package='foo', subject=None,
                        dak_cmd='dak process-upload'):
        self.set_header('X-DAK', dak_cmd)
        self.set_header('X-Debian', 'DAK')
        if package:
            self.set_header('X-Debian-Package', package)
        if subject:
            self.set_header('Subject', subject)

    def test_classify_identifies_package_in_dak_mails(self):
        self.define_dak_mail(package='pkg-a')
        pkg, _ = self.run_classify()
        self.assertEqual(pkg, 'pkg-a')

    def test_classify_binary_upload_mails(self):
        subject = 'foo_1.0-1_amd64.changes ACCEPTED into unstable'
        self.define_dak_mail(subject=subject)
        _, keyword = self.run_classify()
        self.assertEqual(keyword, 'upload-binary')

    def test_classify_source_upload_mails(self):
        subject = 'foo_1.0-1_amd64.changes ACCEPTED into unstable'
        self.define_dak_mail(subject=subject)
        self.set_message_content('' + 'a' * 40 + ' 1234 foo_1.0-1.dsc\n')
        _, keyword = self.run_classify()
        self.assertEqual(keyword, 'upload-source')

    def test_classify_other_archive_mails(self):
        subject = 'Comments regarding foo_1.0-1_amd64.changes'
        self.define_dak_mail(subject=subject)
        _, keyword = self.run_classify()
        self.assertEqual(keyword, 'archive')

    @mock.patch('distro_tracker.mail.mail_news.create_news')
    def test_classify_stores_dak_source_accepted_as_news(self,
                                                         mock_create_news):
        subject = 'Accepted libosmium 2.5.3-1~exp2 (source) into experimental'
        self.define_dak_mail(package='pkg-a', subject=subject)
        self.run_classify()
        mock_create_news.assert_called_with(self.message, 'pkg-a',
                                            create_package=True)

    def test_classify_creates_package_name_on_first_accepted_mail(self):
        subject = 'Accepted libosmium 2.5.3-1~exp2 (source) into experimental'
        self.define_dak_mail(package='pkg-a', subject=subject)
        self.run_classify()
        self.assertIsNotNone(PackageName.objects.get(name='pkg-a'))

    @mock.patch('distro_tracker.mail.mail_news.create_news')
    def test_classify_does_not_store_dak_binary_accepted_as_news(
            self, mock_create_news):
        subject = 'Accepted libosmium 2.5.3-1~exp2 (i386 all) into experimental'
        self.define_dak_mail(package='pkg-a', subject=subject)
        self.run_classify()
        self.assertFalse(mock_create_news.called)

    def define_dak_rm_mail(self, **kwargs):
        subject = 'Bug#123: Removed package(s) from unstable'
        packages = kwargs.pop('packages', [self.package_name])
        self.define_dak_mail(dak_cmd='dak rm', subject=subject, package=None,
                             **kwargs)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
        )
        for pkg in packages:
            content += '{pkg} |  1.2-1 | source, amd64\n'.format(pkg=pkg)
        self.set_message_content(content)

    def test_classify_dak_rm_mail(self):
        self.define_dak_rm_mail(packages=['pkg-a'])
        pkg, keyword = self.run_classify()
        self.assertEqual(pkg, 'pkg-a')
        self.assertEqual(keyword, 'archive')

    def test_classify_dak_rm_mail_multiple_sources(self):
        self.define_dak_rm_mail(packages=['pkg-a', 'pkg-b'])
        pkg, keyword = self.run_classify()
        self.assertEqual(pkg, ['pkg-a', 'pkg-b'])
        self.assertEqual(keyword, 'archive')

    def test_classify_generates_news_with_dak_rm_mail(self):
        self.define_dak_rm_mail()
        self.assertEqual(self.package.news_set.count(), 0)
        pkg, keyword = self.run_classify()
        self.assertEqual(self.package.news_set.count(), 1)

    def test_classify_testing_watch_mail(self):
        self.add_header('X-Testing-Watch-Package', 'pkg-a')
        pkg, keyword = self.run_classify()
        self.assertEqual(pkg, 'pkg-a')
        self.assertEqual(keyword, 'summary')

    def test_classify_generates_news_with_testing_watch_mail(self):
        self.add_header('X-Testing-Watch-Package', self.package_name)
        self.assertEqual(self.package.news_set.count(), 0)
        pkg, keyword = self.run_classify()
        self.assertEqual(self.package.news_set.count(), 1)

    def test_classify_git_mail(self):
        for header in self.GIT_HEADERS:
            with self.subTest(header=header):
                self.add_header(header, self.package_name)
                pkg, keyword = self.run_classify()
                self.assertEqual(pkg, self.package_name)
                self.assertEqual(keyword, 'vcs')
                del self.message[header]

    def test_classify_git_mail_drops_git_suffix_from_repo_name(self):
        for header in self.GIT_HEADERS:
            with self.subTest(header=header):
                self.add_header(header, self.package_name + '.git')
                pkg, keyword = self.run_classify()
                self.assertEqual(pkg, self.package_name)
                self.assertEqual(keyword, 'vcs')
                del self.message[header]

    def test_classify_git_mail_keeps_basename_only(self):
        for header in self.GIT_HEADERS:
            with self.subTest(header=header):
                self.add_header(header,
                                'packages/unstable/' + self.package_name)
                pkg, keyword = self.run_classify()
                self.assertEqual(pkg, self.package_name)
                self.assertEqual(keyword, 'vcs')
                del self.message[header]

    def test_classify_buildd_mail(self):
        self.set_header('X-Debian', 'buildd.debian.org')
        self.set_header('X-Debian-Package', 'foobar')
        pkg, keyword = self.run_classify()
        self.assertEqual(pkg, 'foobar')
        self.assertEqual(keyword, 'build')


class GetPseudoPackageListTest(TestCase):

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_debian_pseudo_packages(self, mock_requests):
        """
        Tests that Debian-specific function for retrieving allowed pseudo
        packages uses the correct source and properly parses it.
        """
        from distro_tracker.vendor.debian.rules import get_pseudo_package_list
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
            'https://bugs.debian.org/pseudo-packages.maintainers',
            headers={},
            allow_redirects=True,
            verify=mock.ANY)
        # Correct packages extracted?
        self.assertSequenceEqual(
            ['package1', 'package2'],
            packages
        )


class GetPackageInformationSiteUrlTest(SimpleTestCase):

    def setUp(self):
        self.repository = {
            'name': 'Debian Stable',
            'suite': 'stable',
            'codename': 'wheezy',
            'shorthand': 'stable',
        }

    def test_get_source_package_url(self):
        """
        Tests retrieving a URL to the package information site for a source
        package.
        """
        # Source package with no repository given
        self.assertEqual(
            'https://packages.debian.org/src:dpkg',
            get_package_information_site_url('dpkg', source_package=True)
        )
        # Source package in a repository
        self.assertEqual(
            'https://packages.debian.org/source/stable/dpkg',
            get_package_information_site_url('dpkg', source_package=True,
                                             repository=self.repository)
        )
        # Source package in a proposed-updates repository
        url = 'https://release.debian.org/proposed-updates/{}.html#dpkg_1.6.15'
        for suite in ('stable', 'oldstable'):
            self.repository['suite'] = '{}-proposed-updates'.format(suite)
            self.assertEqual(
                url.format(suite),
                get_package_information_site_url('dpkg', source_package=True,
                                                 repository=self.repository,
                                                 version='1.6.15')
            )

    def test_get_binary_package_url(self):
        """
        Tests retrieving a URL to the package information site for a binary
        package.
        """
        # Binary package with no repository given
        self.assertEqual(
            'https://packages.debian.org/dpkg',
            get_package_information_site_url('dpkg')
        )
        # Binary package in a repository
        self.assertEqual(
            'https://packages.debian.org/stable/dpkg',
            get_package_information_site_url(
                'dpkg',
                repository=self.repository))
        # Binary package in a proposed-updates repository
        for suite in ('stable', 'oldstable'):
            self.repository['suite'] = '{}-proposed-updates'.format(suite)
            self.assertEqual(
                '',
                get_package_information_site_url('dpkg', source_package=False,
                                                 repository=self.repository,
                                                 version='1.6.15')
            )


class GetDeveloperInformationSiteUrlTest(SimpleTestCase):

    def test_get_developer_site_info_url(self):
        """
        Test retrieving a URL to a developer information Web site.
        """
        developer_email = 'debian-dpkg@lists.debian.org'
        self.assertEqual(
            'https://qa.debian.org/developer.php'
            '?email=debian-dpkg%40lists.debian.org',
            get_developer_information_url(developer_email))

        developer_email = 'email@domain.com'
        self.assertEqual(
            'https://qa.debian.org/developer.php?email=email%40domain.com',
            get_developer_information_url(developer_email)
        )


class RetrieveLowThresholdNmuTest(TestCase):

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer did not previously exist in the database.
        """
        set_mock_response(mock_requests,
                          "Text text text\n"
                          "text more text...\n"
                          " 1. [[DeveloperName|Name]] - "
                          "([[https://qa.debian.org/developer.php?"
                          "login=dummy|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.agree_with_low_threshold_nmu)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_existed(self, mock_requests):
        """
        Tests updating the list of developers that allow the low threshold
        NMU when the developer was previously registered in the database.
        """
        UserEmail.objects.create(email='dummy@debian.org')
        set_mock_response(mock_requests,
                          "Text text text\n"
                          "text more text...\n"
                          " 1. [[DeveloperName|Name]] - "
                          "([[https://qa.debian.org/developer.php?"
                          "login=dummy|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        # Still only one debian developer instance
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.agree_with_low_threshold_nmu)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_remove_nmu(self, mock_requests):
        """
        Tests updating the list of NMU developers when one of them needs to be
        removed from the list.
        """
        # Set up a Debian developer that is already in the NMU list.
        email = UserEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         agree_with_low_threshold_nmu=True)
        set_mock_response(mock_requests,
                          "Text text text\n"
                          "text more text...\n"
                          " 1. [[DeveloperName|Name]] - "
                          "([[https://qa.debian.org/developer.php?"
                          "login=other|all packages]])\n")

        run_task(RetrieveLowThresholdNmuTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
        # The Debian developer is no longer in the list of low threshold nmu
        self.assertFalse(d.agree_with_low_threshold_nmu)


class RetrieveDebianMaintainersTest(TestCase):

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_did_not_exist(self, mock_requests):
        """
        Tests updating the DM list when a new developer is to be added.
        """
        set_mock_response(
            mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n")

        run_task(RetrieveDebianMaintainersTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.is_debian_maintainer)
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_existed(self, mock_requests):
        """
        Tests updating the DM list when the developer was previously registered
        in the database.
        """
        UserEmail.objects.create(email='dummy@debian.org')
        set_mock_response(
            mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n")

        run_task(RetrieveDebianMaintainersTask)

        # A Debian developer created
        self.assertEqual(DebianContributor.objects.count(), 1)
        d = DebianContributor.objects.all()[0]
        self.assertTrue(d.is_debian_maintainer)
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_update_dm_list(self, mock_requests):
        """
        Tests updating the DM list when one of the developers has changes in
        the allowed packages list.
        """
        # Set up a Debian developer that is already in the NMU list.
        email = UserEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         is_debian_maintainer=True,
                                         allowed_packages=['one'])

        set_mock_response(
            mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <dummy@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n")

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
        # The old package is no longer in its list of allowed packages.
        self.assertSequenceEqual(
            ['dummy-package', 'second-package'],
            d.allowed_packages
        )

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_developer_delete_from_dm_list(self, mock_requests):
        """
        Tests updating the DM list when one of the developers has changes in
        the allowed packages list.
        """
        # Set up a Debian developer that is already in the DM list.
        email = UserEmail.objects.create(email='dummy@debian.org')
        DebianContributor.objects.create(email=email,
                                         is_debian_maintainer=True,
                                         allowed_packages=['one'])

        set_mock_response(
            mock_requests,
            "Fingerprint: CFC5B232C0D082CAE6B3A166F04CEFF6016CFFD0\n"
            "Uid: Dummy Developer <different-developer@debian.org>\n"
            "Allow: dummy-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E),\n"
            " second-package (709F54E4ECF3195623326AE3F82E5CC04B2B2B9E)\n")

        run_task(RetrieveDebianMaintainersTask)

        d = DebianContributor.objects.get(email__email='dummy@debian.org')
        # The developer is no longer a debian maintainer
        self.assertFalse(d.is_debian_maintainer)


class DebianContributorExtraTest(TestCase):

    def test_maintainer_extra(self):
        email = UserEmail.objects.create(email='dummy@debian.org')
        d = DebianContributor.objects.create(email=email,
                                             agree_with_low_threshold_nmu=True)

        expected = [
            {
                'display': 'DMD',
                'description': 'UDD\'s Debian Maintainer Dashboard',
                'link': 'https://udd.debian.org/dmd/?dummy%40debian.org#todo',
            },
            {
                'display': 'LowNMU',
                'description': 'maintainer agrees with Low Threshold NMU',
                'link': 'https://wiki.debian.org/LowThresholdNmu',
            }
        ]
        # Only in NMU list
        self.assertSequenceEqual(expected,
                                 get_maintainer_extra('dummy@debian.org'))
        # The developer is now in the DM list
        d.is_debian_maintainer = True
        d.allowed_packages = ['package-name']
        d.save()
        # When not providing a package name, the response is the same
        self.assertSequenceEqual(expected,
                                 get_maintainer_extra('dummy@debian.org'))
        # With a package name an extra item is in the response.
        expected.append({'display': 'dm'})
        self.assertSequenceEqual(
            expected,
            get_maintainer_extra('dummy@debian.org', 'package-name')
        )

    def test_uploader_extra(self):
        email = UserEmail.objects.create(email='dummy@debian.org')
        d = DebianContributor.objects.create(email=email,
                                             agree_with_low_threshold_nmu=True)
        expected = [
            {
                'display': 'DMD',
                'description': 'UDD\'s Debian Maintainer Dashboard',
                'link': 'https://udd.debian.org/dmd/?dummy%40debian.org#todo',
            },
        ]
        # Only in NMU list - no extra data when the developer in displayed as
        # an uploader.
        self.assertSequenceEqual(expected,
                                 get_uploader_extra('dummy@debian.org'))
        # The developer is now in the DM list
        d.is_debian_maintainer = True
        d.allowed_packages = ['package-name']
        d.save()
        # When not providing a package name, the response is the same
        self.assertSequenceEqual(expected,
                                 get_uploader_extra('dummy@debian.org'))
        # With a package name an extra item is in the response.
        expected.append({'display': 'dm'})
        self.assertSequenceEqual(
            expected,
            get_uploader_extra('dummy@debian.org', 'package-name')
        )


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class RetrieveSourcesInformationDebian(TestCase):

    """
    Tests the Debian-specific aspects of retrieving package information from a
    repository.
    """
    fixtures = ['repository-test-fixture.json']

    def setUp(self):
        self.repository = Repository.objects.all()[0]
        self.component = 'main'

    @mock.patch(
        'distro_tracker.core.retrieve_data.AptCache.update_repositories')
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
                [(self.repository, self.component, sources_file_path)],
                []
            )
            # Sanity check - no source packages before running the task
            self.assertEqual(0, SourcePackageName.objects.count())

            run_task(UpdateRepositoriesTask)

            # Only one package exists
            self.assertEqual(1, SourcePackageName.objects.count())
            # It is the one without the Extra-Source-Only: yes
            self.assertEqual(
                'dummy-package',
                SourcePackageName.objects.all()[0].name)


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class DebianNewsFromEmailTest(TestCase):

    """
    Tests creating Debian-specific news from received emails.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
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
        content = b'Content'
        self.set_message_content(content)

        self.process_mail()

        self.assertEqual(1, News.objects.count())
        news = News.objects.all()[0]
        self.assertEqual(news.package.name, self.package.name)
        self.assertEqual(subject, news.title)
        self.assertIn(content, news.content)

    def test_source_upload_package_does_not_exist(self):
        """
        Tests that a news and the associated source package are created when
        the notification of a new source upload for a package not yet tracked by
        Distro Tracker is received.
        """
        subject = self.get_accepted_subject('no-exist', '1.0.0')
        self.set_subject(subject)
        content = 'Content'
        self.set_message_content(content)

        self.process_mail()

        self.assertTrue(PackageName.objects.filter(name='no-exist').exists())
        self.assertEqual(1, News.objects.count())

    def test_dak_rm_news(self):
        """
        Tests that a dak rm message creates a news.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
            '{pkg} |  {ver} | source, all').format(
            pkg=self.package_name,
            ver=self.package.version)
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

    def test_dak_rm_no_package(self):
        """
        Tests that a dak rm message referencing a package which Distro
        Tracker does not track, does not create any news.
        """
        subject = 'Removed package(s) from unstable'
        self.set_subject(subject)
        content = (
            'We believe that the bug you reported is now fixed; the following\n'
            'package(s) have been removed from unstable:\n\n'
            '{pkg} |  {ver} | source, all').format(
            pkg='does-not-exist',
            ver='1.0.0')
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
            '{pkg} |  {ver} | source, all').format(
            pkg=self.package_name,
            ver=self.package.version)
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
            'package(s) have been removed from unstable:\n\n')
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
        ).format(pkg=self.package_name).encode('utf-8')
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
        a package not tracked by Distro Tracker does not create any news items.
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
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateLintianStatsTask`
    task.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
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
        Helper method which asserts that the given stats match the expected
        stats.

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

    def assert_action_item_warnings_and_errors_count(
            self,
            item,
            errors=0,
            warnings=0):
        """
        Helper method which checks if an instance of
        :class:`distro_tracker.core.ActionItem` contains the given error and
        warning count in its extra_data.
        """
        self.assertEqual(item.extra_data['errors'], errors)
        self.assertEqual(item.extra_data['warnings'], warnings)

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdateLintianStatsTask.ACTION_ITEM_TYPE_NAME)[0]

    @mock.patch('distro_tracker.core.utils.http.requests')
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

    @mock.patch('distro_tracker.core.utils.http.requests')
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

    @mock.patch('distro_tracker.core.utils.http.requests')
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
        all_names = [stats.package.name
                     for stats in LintianStats.objects.all()]
        self.assertIn('dummy-package', all_names)
        self.assertIn('other-package', all_names)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_unknown_package(self, mock_requests):
        """
        Tests that when an unknown package is encountered, no stats are created.
        """
        set_mock_response(mock_requests, text="no-exist 1 2 3 4 5 6")

        self.run_task()

        # There are no stats
        self.assertEqual(0, LintianStats.objects.count())

    @mock.patch('distro_tracker.core.utils.http.requests')
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

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_correct_url_used(self, mock_requests):
        """
        Tests that lintian stats are retrieved from the correct URL.
        """
        self.run_task()

        # We only care about the URL used, not the headers or other arguments
        self.assertEqual(
            mock_requests.get.call_args[0][0],
            'https://lintian.debian.org/qa-list.txt')

    @mock.patch('distro_tracker.core.utils.http.requests')
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
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors,
            warnings)
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

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_updated(self, mock_requests):
        """
        Tests that an existing action item is updated with new data.
        """
        # Create an existing action item
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})
        old_timestamp = old_item.last_updated_timestamp
        errors, warnings = 2, 0
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated?
        item = ActionItem.objects.all()[0]
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors,
            warnings)
        # The timestamp is updated
        self.assertNotEqual(old_timestamp, item.last_updated_timestamp)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_not_updated(self, mock_requests):
        """
        Tests that an existing action item is left unchanged when the update
        shows unchanged lintian stats.
        """
        errors, warnings = 2, 0
        # Create an existing action item
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': errors, 'warnings': warnings})
        old_timestamp = old_item.last_updated_timestamp
        response = "dummy-package {err} {warn} 0 0 0 0".format(
            err=errors, warn=warnings)
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # Item unchanged?
        item = ActionItem.objects.all()[0]
        self.assertEqual(old_timestamp, item.last_updated_timestamp)

    @mock.patch('distro_tracker.core.utils.http.requests')
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
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors,
            warnings)
        # It is a normal severity issue
        self.assertEqual('normal', item.get_severity_display())

    @mock.patch('distro_tracker.core.utils.http.requests')
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
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors,
            warnings)
        # It is a high severity issue since it contains both errors and
        # warnings
        self.assertEqual('high', item.get_severity_display())

    @mock.patch('distro_tracker.core.utils.http.requests')
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

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_removed(self, mock_requests):
        """
        Tests that a previously existing action item is removed if the updated
        stats no longer contain errors or warnings.
        """
        # Make sure an item exists for the package
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})
        response = "dummy-package 0 0 5 4 3 2"
        set_mock_response(mock_requests, text=response)

        self.run_task()

        # There are no action items any longer.
        self.assertEqual(0, self.package_name.action_items.count())

    @mock.patch('distro_tracker.core.utils.http.requests')
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

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_created_multiple_packages(self, mock_requests):
        """
        Tests that action items are created correctly when there are stats
        for multiple different packages in the response.
        """
        other_package = PackageName.objects.create(
            name='other-package',
            source=True)
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
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors[0],
            warnings[0])
        item = other_package.action_items.all()[0]
        self.assert_action_item_warnings_and_errors_count(
            item,
            errors[1],
            warnings[1])

    @mock.patch('distro_tracker.core.utils.http.requests')
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


class UpdateAppStreamStatsTaskTest(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateAppStreamStatsTask`
    task.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self._tagdef_url = 'https://appstream.debian.org/hints/asgen-hints.json'
        self._hints_url_template = ('https://appstream.debian.org/hints/sid/'
                                    '{section}/Hints-{arch}.json.gz')

        tag_definitions_dict = {'tag-mock-error': {
                                'text': 'Mocking an error tag.',
                                'severity': 'error'},
                                'tag-mock-warning': {
                                'text': 'Mocking a warning tag.',
                                'severity': 'warning'},
                                'tag-mock-info': {
                                'text': 'Mocking an info tag.',
                                'severity': 'info'}
                                }
        self._tag_definitions = json.dumps(tag_definitions_dict)

        self._repository = Repository.objects.create(
            name='Debian Unstable', codename='sid', suite='unstable',
            shorthand='unstable', components=['main', 'contrib', 'non-free'],
            default=True)

    def _create_hint_entry(self, package, version=1.0,
                           n_errors=0, n_warnings=0, n_infos=0):
        entry = {'package': '{}/{}/amd64'.format(package, version),
                 'hints': {'org.example.test1.desktop': []}}
        for i in range(n_errors):
            entry['hints']['org.example.test1.desktop'].append(
                {'tag': 'tag-mock-error',
                 'vars': {}})
        for i in range(n_warnings):
            entry['hints']['org.example.test1.desktop'].append(
                {'tag': 'tag-mock-warning',
                 'vars': {}})
        for i in range(n_infos):
            entry['hints']['org.example.test1.desktop'].append(
                {'tag': 'tag-mock-info',
                 'vars': {}})
        return entry

    def run_task(self):
        """
        Runs the AppStream hints update task.
        """
        task = UpdateAppStreamStatsTask()
        task.execute()

    def _set_mock_response(self, mock_requests, text="", status_code=200):
        """
        Helper method which sets a mock response to the given mock requests
        module.
        """

        mock_response = mock_requests.models.Response()
        mock_response.status_code = status_code
        mock_response.ok = status_code < 400

        def compress_text(s):
            """
            Helper to GZip-compress a string.
            """
            if isinstance(s, bytes):
                src_data = s
            else:
                src_data = bytes(s, 'utf-8')
            return gzip.compress(src_data)

        def build_response(*args, **kwargs):
            if args[0] == self._tagdef_url:
                # the tag definitions are requested
                mock_response.content = self._tag_definitions.encode('utf-8')
                mock_response.json.return_value = \
                    json.loads(self._tag_definitions)
            elif args[0] == self._hints_url_template.format(
                    section='main', arch='amd64'):
                # hint data was requested
                data = compress_text(text)
                mock_response.text = data
                mock_response.content = data
            else:
                # return a compressed, but empty hints document as default
                data = compress_text('[]')
                mock_response.text = data
                mock_response.content = data

            return mock_response

        mock_requests.get.side_effect = build_response

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdateAppStreamStatsTask.ACTION_ITEM_TYPE_NAME)[0]

    def assert_correct_severity_stats(self, hints, expected_hints):
        """
        Helper method which asserts that the given hint stats match the expected
        stats.
        """
        for severity in ['errors', 'warnings', 'infos']:
            count = hints[severity] if severity in hints else 0
            expected_count = \
                expected_hints[severity] if severity in expected_hints else 0
            self.assertEqual(count, expected_count)

    def assert_action_item_error_and_warning_count(self, item,
                                                   errors=0, warnings=0):
        """
        Helper method which checks if an instance of
        :class:`distro_tracker.core.ActionItem` contains the given error and
        warning count in its extra_data.
        """

        for pkg, info in item.extra_data.items():
            self.assertEqual(info.get('errors', 0), errors)
            self.assertEqual(info.get('warnings', 0), warnings)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_hint_stats_created(self, mock_requests):
        """
        Tests that stats are created for a package that previously did not have
        any AppStream stats.
        """

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=1)
        test_entry['hints']['org.example.test2.desktop'] = \
            [{'vars': {},
              'tag': 'tag-mock-error'},
             {'vars': {},
              'tag': 'tag-mock-warning'}]
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)

        self.run_task()

        # The stats have been created
        self.assertEqual(1, PackageData.objects.filter(key='appstream').count())
        # They are associated with the correct package.
        data = PackageData.objects.filter(key='appstream')[0]
        self.assertEqual(data.package.name, 'dummy-package')
        # The category counts themselves are correct
        self.assert_correct_severity_stats(data.value['dummy-package'],
                                           {'errors': 2,
                                            'warnings': 1,
                                            'infos': 0})

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_hint_stats_updated(self, mock_requests):
        """
        Tests that when a package already had associated AppStream stats,
        they are correctly updated after running the task.
        """

        # Create the pre-existing stats for the package
        PackageData.objects.create(package=self.package_name,
                                   key='appstream',
                                   value={'errors': 1, 'warnings': 3})

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=2)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)

        self.run_task()

        # Still only one AppStream stats object
        self.assertEqual(1, PackageData.objects.filter(key='appstream').count())
        # The package is still correct
        data = PackageData.objects.filter(key='appstream')[0]
        self.assertEqual(data.package.name, 'dummy-package')
        # The stats have been updated
        self.assert_correct_severity_stats(data.value['dummy-package'],
                                           {'errors': 2,
                                            'warnings': 0,
                                            'infos': 0})

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_stats_created_multiple_packages(self, mock_requests):
        """
        Tests that stats are correctly creatd when there are stats for
        multiple packages in the response.
        """
        # Create a second package.
        SourcePackageName.objects.create(name='other-package')

        test_entry1 = self._create_hint_entry(package='dummy-package',
                                              n_errors=2)
        test_entry2 = self._create_hint_entry(package='other-package',
                                              version='1.2',
                                              n_errors=1, n_warnings=1)
        test_data = json.dumps([test_entry1, test_entry2]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # Stats created for both packages
        self.assertEqual(2, PackageData.objects.filter(key='appstream').count())
        all_names = [stats.package.name
                     for stats in PackageData.objects.filter(key='appstream')]
        self.assertIn('dummy-package', all_names)
        self.assertIn('other-package', all_names)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_stats_associated_with_source(self, mock_requests):
        """
        Tests that we correctly map the binary packages to source packages,
        and the stats are accurate.
        """

        # Create source packages and connected binary packages
        bin1 = BinaryPackageName.objects.create(name="alpha-package-bin")
        bin2 = BinaryPackageName.objects.create(name="alpha-package-data")

        src_name1 = SourcePackageName.objects.create(name='alpha-package')
        src_pkg1, _ = SourcePackage.objects.get_or_create(
            source_package_name=src_name1, version='1.0.0')
        src_pkg1.binary_packages.set([bin1, bin2])
        src_pkg1.save()

        bin3 = BinaryPackageName.objects.create(name="beta-common")
        src_name2 = SourcePackageName.objects.create(name='beta-package')
        src_pkg2, _ = SourcePackage.objects.get_or_create(
            source_package_name=src_name2, version='1.2.0')
        src_pkg2.binary_packages.set([bin3])
        src_pkg2.save()

        # Set mock data
        test_entry1 = self._create_hint_entry(package='alpha-package-bin',
                                              n_errors=1, n_warnings=1)
        test_entry2 = self._create_hint_entry(package='alpha-package-data',
                                              n_warnings=1)
        test_entry3 = self._create_hint_entry(package='beta-common',
                                              version='1.2',
                                              n_errors=2)
        hints_list = [test_entry1, test_entry2, test_entry3]
        test_data = json.dumps(hints_list).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # Stats created for two source packages
        self.assertEqual(2, PackageData.objects.filter(key='appstream').count())
        all_names = [stats.package.name
                     for stats in PackageData.objects.filter(key='appstream')]

        # source packages should be in the result
        self.assertIn('alpha-package', all_names)
        self.assertIn('beta-package', all_names)

        # binary packages should not be there
        self.assertNotIn('alpha-package-bin', all_names)
        self.assertNotIn('alpha-package-data', all_names)
        self.assertNotIn('beta-common', all_names)

        # check if the stats are correct
        data = PackageData.objects.get(key='appstream',
                                       package__name='alpha-package')
        self.assert_correct_severity_stats(data.value['alpha-package-bin'],
                                           {'errors': 1,
                                            'warnings': 1})
        self.assert_correct_severity_stats(data.value['alpha-package-data'],
                                           {'warnings': 1})

        data = PackageData.objects.get(key='appstream',
                                       package__name='beta-package')
        self.assert_correct_severity_stats(data.value['beta-common'],
                                           {'errors': 2,
                                            'warnings': 0,
                                            'infos': 0})

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_unknown_package(self, mock_requests):
        """
        Tests that when an unknown package is encountered, no stats are created.
        """

        test_entry = self._create_hint_entry(package='nonexistant', n_errors=1)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # There are no stats
        self.assertEqual(0, PackageData.objects.filter(key='appstream').count())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_updated(self, mock_requests):
        """
        Tests that an existing action item is updated with new data.
        """
        # Create an existing action item
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})
        old_timestamp = old_item.last_updated_timestamp

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=2)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)

        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated?
        item = ActionItem.objects.all()[0]
        self.assert_action_item_error_and_warning_count(item, 2, 0)

        # The timestamp is updated
        self.assertNotEqual(old_timestamp, item.last_updated_timestamp)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_not_updated(self, mock_requests):
        """
        Tests that an existing action item is left unchanged when the update
        shows unchanged stats.
        """
        errors = 2
        # Create an existing action item
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            extra_data={'dummy-package':
                        {'url': u'#',
                         'errors': errors}}
        )
        old_timestamp = old_item.last_updated_timestamp

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=errors)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # Item unchanged?
        item = ActionItem.objects.all()[0]
        self.assertEqual(old_timestamp, item.last_updated_timestamp)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_created(self, mock_requests):
        """
        Tests that an action item is created when the package has errors and
        warnings.
        """

        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=1, n_warnings=1)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The item is linked to the correct package
        item = ActionItem.objects.all()[0]
        self.assertEqual(item.package.name, self.package_name.name)
        # The correct number of errors and warnings is stored in the item
        self.assert_action_item_error_and_warning_count(item,
                                                        errors=1, warnings=1)
        # It is a high severity issue
        self.assertEqual('high', item.get_severity_display())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_not_created(self, mock_requests):
        """
        Tests that no action item is created when the package has no errors or
        warnings.
        """

        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        test_entry = self._create_hint_entry(package='dummy-package', n_infos=1)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_created_errors(self, mock_requests):
        """
        Tests that an action item is created when the package has errors.
        """

        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_errors=2)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The correct number of errors and warnings is stored in the item
        item = ActionItem.objects.all()[0]
        self.assert_action_item_error_and_warning_count(item,
                                                        errors=2, warnings=0)
        # It has the correct type
        self.assertEqual(
            item.item_type.type_name,
            UpdateAppStreamStatsTask.ACTION_ITEM_TYPE_NAME)
        # It is a high severity issue
        self.assertEqual('high', item.get_severity_display())
        # Correct full description template
        self.assertEqual(
            item.full_description_template,
            UpdateAppStreamStatsTask.ITEM_FULL_DESCRIPTION_TEMPLATE)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_created_warnings(self, mock_requests):
        """
        Tests that an action item is created when the package has warnings.
        """

        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        test_entry = self._create_hint_entry(package='dummy-package',
                                             n_warnings=2)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # An action item is created.
        self.assertEqual(1, ActionItem.objects.count())
        # The correct number of errors and warnings is stored in the item
        item = ActionItem.objects.all()[0]
        self.assert_action_item_error_and_warning_count(item,
                                                        errors=0, warnings=2)
        # It should be a normal severity issue
        self.assertEqual('normal', item.get_severity_display())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_removed(self, mock_requests):
        """
        Tests that a previously existing action item is removed if the updated
        hints no longer contain errors or warnings.
        """
        # Make sure an item exists for the package
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})

        test_entry = self._create_hint_entry(package='dummy-package', n_infos=1)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # There are no action items any longer.
        self.assertEqual(0, self.package_name.action_items.count())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_removed_no_data(self, mock_requests):
        """
        Tests that a previously existing action item is removed when the
        updated hints no longer contain any information for the package.
        """
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Short description...",
            extra_data={'errors': 1, 'warnings': 2})

        test_entry = self._create_hint_entry(package='some-unrelated-package',
                                             n_errors=1)
        test_data = json.dumps([test_entry]).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # There are no action items any longer.
        self.assertEqual(0, self.package_name.action_items.count())

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_action_item_created_multiple_packages(self, mock_requests):
        """
        Tests that action items are created correctly when there are stats
        for multiple different packages in the response.
        """

        other_package = PackageName.objects.create(
            name='other-package',
            source=True)
        # Sanity check: there were no action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        test_entry1 = self._create_hint_entry(package='dummy-package',
                                              n_errors=2)
        test_entry2 = self._create_hint_entry(package='other-package',
                                              version='1.4',
                                              n_warnings=2)
        test_entry3 = self._create_hint_entry(package='some-package',
                                              n_errors=1)
        hints_list = [test_entry1, test_entry2, test_entry3]
        test_data = json.dumps(hints_list).encode('utf-8')

        self._set_mock_response(mock_requests, text=test_data)
        self.run_task()

        # Action items are created for two packages.
        self.assertEqual(1, self.package_name.action_items.count())
        self.assertEqual(1, other_package.action_items.count())
        # The items contain correct data.
        item = self.package_name.action_items.all()[0]
        self.assert_action_item_error_and_warning_count(item,
                                                        errors=2, warnings=0)

        item = other_package.action_items.all()[0]
        self.assert_action_item_error_and_warning_count(item,
                                                        errors=0, warnings=2)


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class DebianBugActionItemsTests(TestCase):

    """
    Tests the creation of :class:`distro_tracker.core.ActionItem` instances
    based on Debian bug stats.
    """
    @staticmethod
    def stub_tagged_bugs(tag, user=None, help_bugs=None, newcomer_bugs=None):
        if tag == 'help':
            return help_bugs
        elif tag == 'newcomer':
            return newcomer_bugs

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self.task = UpdatePackageBugStats()
        self.udd_bugs = {}
        self.help_bugs = {}
        self.newcomer_bugs = {}
        # Stub the data providing methods
        self.task._get_udd_bug_stats = mock.MagicMock(
            return_value=self.udd_bugs)
        self.task._get_tagged_bug_stats = mock.MagicMock(
            side_effect=curry(
                DebianBugActionItemsTests.stub_tagged_bugs,
                help_bugs=self.help_bugs,
                newcomer_bugs=self.newcomer_bugs))
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
        Helper method returning a
        :class:`distro_tracker.core.models.ActionItemType` for the debian patch
        bug warning action item type.
        """
        return ActionItemType.objects.get_or_create(
            type_name=UpdatePackageBugStats.PATCH_BUG_ACTION_ITEM_TYPE_NAME)[0]

    def get_help_action_type(self):
        """
        Helper method returning a
        :class:`distro_tracker.core.models.ActionItemType` for the debian help
        bug warning action item type.
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
        self.assertNotEqual(item.extra_data['url'], '')
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
        Tests that multiple :class:`distro_tracker.core.models.ActionItem`
        instances are created for a package if it contains both patch and help
        bugs.
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
            PackageName.objects.create(name='other-package', source=True),
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
            self.assertEqual(
                patch_item.extra_data['bug_count'],
                patch_bug_count)
            help_item = package.action_items.get(
                item_type=self.get_help_action_type())
            self.assertEqual(help_item.extra_data['bug_count'], help_bug_count)


class UpdateExcusesTaskActionItemTest(TestCase):

    """
    Tests for the creating of action items by the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateExcusesTask`.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.package = SourcePackage(
            source_package_name=self.package_name, version='1.0.0')

        self.task = UpdateExcusesTask()
        self.task._get_excuses_yaml = mock.MagicMock()

    def run_task(self):
        self.task.execute()

    def set_update_excuses_content(self, content):
        """
        Sets the stub content of the update_excuses.yaml that the task will
        have access to.
        """
        self.task._get_excuses_yaml.return_value = yaml.load(content)

    def set_update_excuses_content_from_file(self, file_name):
        """
        Sets the stub content of the update_excuses.yaml that the task will
        have access to based on the content of the test file with the given
        name.
        """
        with open(self.get_test_data_path(file_name), 'r') as f:
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
        self.set_update_excuses_content_from_file('update_excuses-1.yaml')
        # Sanity check: no action items currently
        self.assertEqual(0, ActionItem.objects.count())
        expected_data = {
            'age': 20,
            'limit': 10,
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
        self.set_update_excuses_content_from_file('update_excuses-2.yaml')
        # Sanity check: no action items currently
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Still no action items
        self.assertEqual(0, ActionItem.objects.count())

    def test_item_skipped_when_slash_in_name(self):
        """
        Tests that when the task meets a package with a / in its name, it
        ignores it.
        """
        self.set_update_excuses_content_from_file('update_excuses-3.yaml')
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
        self.set_update_excuses_content_from_file('update_excuses-2.yaml')

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
        self.set_update_excuses_content_from_file('update_excuses-1.yaml')
        expected_data = {
            'age': 20,
            'limit': 10,
        }

        self.run_task()

        # Still just one item
        self.assertEqual(1, ActionItem.objects.count())
        # Extra data updated?
        item = ActionItem.objects.all()[0]
        self.assertDictEqual(expected_data, item.extra_data)


class UpdateBuildLogCheckStatsActionItemTests(TestCase):

    """
    Tests that :class:`distro_tracker.core.models.ActionItem` instances are
    correctly created when running the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateBuildLogCheckStats`
    task.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
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
        self.set_buildd_content(b"dummy-package|1|2|0|0")
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
        self.set_buildd_content(b"dummy-package|0|1|0|0")

        self.run_task()

        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        self.assertEqual('low', item.get_severity_display())

    def test_action_item_error_high_severity(self):
        """
        Tests that action items have high severity if the package has only
        errors.
        """
        self.set_buildd_content(b"dummy-package|1|0|0|0")

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
        self.set_buildd_content(b"dummy-package|0|0|1|1")
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
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        old_timestamp = old_item.last_updated_timestamp
        expected_data = {
            'errors': 1,
            'warnings': 2,
        }
        self.set_buildd_content(b"dummy-package|1|2|1|1")

        self.run_task()

        # Stll just one action item
        self.assertEqual(1, ActionItem.objects.count())
        # The extra data has been updated?
        item = ActionItem.objects.all()[0]
        self.assertEqual(expected_data, item.extra_data)
        # The time stamp is updated?
        self.assertNotEqual(old_timestamp, item.last_updated_timestamp)

    def test_action_item_not_updated(self):
        """
        Tests that an already existing action item is unchanged if the new data
        does not differ from the already stored data.
        """
        # Create an action item which exists before that task is run
        expected_data = {
            'errors': 1,
            'warnings': 2,
        }
        old_item = ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc",
            extra_data=expected_data)
        old_timestamp = old_item.last_updated_timestamp
        self.set_buildd_content(b"dummy-package|1|2|1|1")

        self.run_task()

        # Stll just one action item
        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        # The item is unchanged
        self.assertEqual(old_timestamp, item.last_updated_timestamp)

    def test_action_item_removed(self):
        """
        Tests that an already existing action item is removed when the package
        no longer has any warnings or errors (but still has buildd stats).
        """
        ActionItem.objects.create(
            package=self.package_name,
            item_type=self.get_action_item_type(),
            short_description="Desc")
        self.set_buildd_content(b"dummy-package|0|0|1|1")

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
        self.set_buildd_content(b"other-package|0|1|1|1")

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
            b"other-package|0|1|1|1\n"
            b"dummy-package|1|1|0|0")

        self.run_task()

        # Both packages have an action item
        self.assertEqual(1, other_package.action_items.count())
        self.assertEqual(1, self.package_name.action_items.count())


class DebianWatchFileScannerUpdateTests(TestCase):

    """
    Tests that :class:`distro_tracker.core.models.ActionItem` instances are
    correctly created when running the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateBuildLogCheckStats`
    task.
    """

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = DebianWatchFileScannerUpdate()
        # Stub the data providing methods: no content by default
        self.task._get_upstream_status_content = mock.MagicMock(
            return_value=b'')

    def run_task(self):
        self.task.execute()

    def set_upstream_status_content(self, content):
        """
        Sets the stub content returned to the task as UDD DEHS data.
        :param content: A list of dicts of information returned by UDD. The
            content given as a response to the task will be the YAML encoded
            representation of this list.
        """
        self.task._get_upstream_status_content.return_value = json.dumps(
            content).encode('utf-8')

    def get_item_type(self, type_name):
        """
        Helper method returning a
        :class:`distro_tracker.core.models.ActionItemType` instance with the
        given type name.
        """
        return ActionItemType.objects.get_or_create(type_name=type_name)[0]

    def test_package_info_created_with_upstream_data(self):
        """
        Tests that a new PackageData is created with key 'general' and upstream
        data
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
        self.set_upstream_status_content(dehs)
        # No general data for package
        self.assertEqual(0, self.package.data.count())

        self.run_task()

        # General data created
        self.assertEqual(1, self.package.data.count())

        general = self.package.data.get(key='general').value
        self.assertEqual(general['upstream']['version'], version)
        self.assertEqual(general['upstream']['url'], url)

    def test_package_info_updated_with_upstream_data(self):
        """
        Tests that package's general data is updated with upstream
        data
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
        self.set_upstream_status_content(dehs)
        PackageData.objects.create(
            package=self.package, key='general', value={})
        # No upstream data yet
        self.assertNotIn('upstream', self.package.data.get(key='general').value)

        self.run_task()

        # Upstream data updated
        general = self.package.data.get(key='general').value
        self.assertEqual(general['upstream']['version'], version)
        self.assertEqual(general['upstream']['url'], url)

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
        self.set_upstream_status_content(dehs)
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
            DebianWatchFileScannerUpdate.ACTION_ITEM_TEMPLATES
            ['new-upstream-version'], item.full_description_template)
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
        self.set_upstream_status_content(dehs)

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
        self.set_upstream_status_content(dehs)

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
        self.set_upstream_status_content(dehs)
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
        self.set_upstream_status_content(dehs)

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
        self.set_upstream_status_content(dehs)

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
        Tests that when there is no DEHS data at all, no action items are
        created.
        """
        self.run_task()

        self.assertEqual(0, ActionItem.objects.count())


class UpdateSecurityIssuesTaskTests(TestCase):

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.task = UpdateSecurityIssuesTask()
        # Stub the data providing methods: no content by default
        self.task._get_issues_content = mock.MagicMock(return_value='')

    def load_test_json(self, key):
        datafn = 'security-tracker-{}.json'.format(key)
        with open(self.get_test_data_path(datafn), 'r') as f:
            content = json.load(f)
        return content

    def mock_json_data(self, key=None, content={}):
        if key:
            content = self.load_test_json(key)
        self.task._get_issues_content = mock.MagicMock(return_value=content)
        return content

    def run_task(self):
        self.task.execute()

    def get_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name='debian-security-issue')[0]

    def test_get_issues_summary_with_eol(self):
        data = self.load_test_json('eol')['dummy-package']
        stats = self.task.get_issues_summary(data)
        self.assertEqual(stats['jessie']['open'], 0)
        self.assertEqual(stats['sid']['open'], 1)

    def test_get_issues_summary_with_unimportant(self):
        data = self.load_test_json('unimportant')['dummy-package']
        stats = self.task.get_issues_summary(data)
        self.assertEqual(stats['jessie']['open'], 0)
        self.assertEqual(stats['sid']['open'], 0)
        self.assertEqual(stats['jessie']['nodsa'], 0)
        self.assertEqual(stats['sid']['nodsa'], 0)
        self.assertEqual(stats['jessie']['unimportant'], 1)
        self.assertEqual(stats['sid']['unimportant'], 0)

    def test_get_issues_summary_with_nodsa(self):
        data = self.load_test_json('nodsa')['dummy-package']
        stats = self.task.get_issues_summary(data)
        self.assertEqual(stats['jessie']['open'], 0)
        self.assertEqual(stats['sid']['open'], 0)
        self.assertEqual(stats['jessie']['nodsa'], 1)
        self.assertEqual(stats['sid']['nodsa'], 0)
        self.assertEqual(stats['jessie']['unimportant'], 0)
        self.assertEqual(stats['sid']['unimportant'], 0)

    def test_get_issues_summary_with_open(self):
        data = self.load_test_json('open')['dummy-package']
        stats = self.task.get_issues_summary(data)
        self.assertEqual(stats['jessie']['open'], 2)
        self.assertEqual(stats['jessie']['nodsa'], 1)
        self.assertEqual(stats['jessie']['unimportant'], 0)
        self.assertEqual(stats['stretch']['open'], 0)
        self.assertEqual(stats['stretch']['nodsa'], 0)
        self.assertEqual(stats['stretch']['unimportant'], 1)
        self.assertEqual(stats['sid']['open'], 2)
        self.assertEqual(stats['sid']['nodsa'], 0)
        self.assertEqual(stats['sid']['unimportant'], 0)

    def test_get_issues_summary_has_details(self):
        data = self.load_test_json('open')['dummy-package']
        stats = self.task.get_issues_summary(data)
        self.assertDictEqual(
            stats['jessie']['open_details'],
            {
                'CVE-2015-0234': 'Description of CVE-2015-0234',
                'CVE-2015-0235': '',
            }
        )
        self.assertDictEqual(
            stats['jessie']['nodsa_details'],
            {
                'CVE-2015-0233': 'Description of CVE-2015-0233',
            }
        )

    def test_get_issues_stats(self):
        content = self.mock_json_data('open')
        stats = self.task.get_issues_stats(content)
        self.assertTrue(stats['dummy-package']['jessie']['open'], 2)
        self.assertTrue(stats['dummy-package']['jessie']['nodsa'], 1)

    def test_execute_create_data(self):
        self.mock_json_data('open')
        self.run_task()
        data = self.package.data.get(
            key='debian-security').value
        self.assertEqual(data['stats']['jessie']['open'], 2)
        self.assertEqual(data['stats']['jessie']['nodsa'], 1)

    def test_execute_drop_data(self):
        pkg = SourcePackageName.objects.create(name='pkg')
        pkg.data.create(key='debian-security', value={})
        self.mock_json_data('open')
        self.assertEqual(
            pkg.data.filter(key='debian-security').count(),
            1)
        self.run_task()
        self.assertEqual(
            pkg.data.filter(key='debian-security').count(),
            0)

    def test_execute_update_data(self):
        self.package.data.create(
            key='debian-security',
            value={
                'details': {},
                'stats': {},
                'checksum': '99914b932bd37a50b983c5e7c90ae93b',
            })
        content = self.mock_json_data('open')
        self.run_task()
        after = self.package.data.get(key='debian-security')
        self.assertNotEqual(after.value['checksum'],
                            '99914b932bd37a50b983c5e7c90ae93b')
        self.maxDiff = None
        self.assertDictEqual(
            after.value,
            self.task.generate_package_data(content['dummy-package'])
        )

    def test_execute_update_data_skipped(self):
        # Inject an inconsistent initial value that would be overwritten
        # in case of update
        initial_value = {
            'details': {
                'test_key': 'test_value'
            },
            'stats': {
                'test_key': 'test_value'
            },
            # This checksum is for details={} (empty dict)
            'checksum': '99914b932bd37a50b983c5e7c90ae93b',
        }
        self.package.data.create(
            key='debian-security', value=initial_value)
        # Ensure the data retrieved is empty for the package we test
        content = {
            'dummy-package': {}
        }
        self.mock_json_data(content=content)
        self.run_task()
        # Ensure that we still have the initial data and that it has not
        # been updated
        after = self.package.data.get(key='debian-security')
        self.assertDictEqual(after.value, initial_value)

    def test_update_action_item(self):
        action_item = ActionItem(extra_data={'release': 'jessie'},
                                 package=self.package)
        # First case, normal issue
        data = self.load_test_json('open')['dummy-package']
        stats = self.task.get_issues_summary(data)['jessie']
        self.task.update_action_item(stats, action_item)
        self.assertEqual(action_item.severity, ActionItem.SEVERITY_HIGH)
        self.assertIn('security issues</a> in jessie',
                      action_item.short_description)
        self.assertEqual(action_item.extra_data['security_issues_count'], 3)
        # Second case, nodsa issue only
        data = self.load_test_json('nodsa')['dummy-package']
        stats = self.task.get_issues_summary(data)['jessie']
        self.task.update_action_item(stats, action_item)
        self.assertEqual(action_item.severity, ActionItem.SEVERITY_LOW)
        self.assertIn('ignored security issue</a> in jessie',
                      action_item.short_description)
        self.assertEqual(action_item.extra_data['security_issues_count'], 1)

    def test_action_item_created(self):
        """
        Tests that an action item is created when a package has security
        issues.
        """
        self.mock_json_data('open')
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        self.assertEqual(2, ActionItem.objects.count())
        for item in ActionItem.objects.all():
            self.assertTrue(item.item_type.type_name.startswith(
                'debian-security-issue-in'))
            self.assertTrue('release' in item.extra_data)
            self.assertTrue('security_issues_count' in item.extra_data)

    def test_action_item_removed(self):
        """
        Tests that an action item is removed when a package no longer has
        security issues.
        """
        self.mock_json_data('open')
        self.run_task()
        self.assertTrue(ActionItem.objects.count() > 0)

        self.mock_json_data('unimportant')
        self.run_task()

        # Removed the action item
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_updated(self):
        """
        Tests that an action item is updated when there are no package security
        issue stats.
        """
        self.mock_json_data('nodsa')
        self.run_task()
        ai = ActionItem.objects.get(
            item_type__type_name='debian-security-issue-in-jessie')
        self.assertEqual(ai.extra_data['security_issues_count'], 1)
        self.assertEqual(ai.severity, ActionItem.SEVERITY_LOW)
        self.assertIn("1 ignored security issue", ai.short_description)

        self.mock_json_data('open')
        self.run_task()
        ai = ActionItem.objects.get(id=ai.id)
        self.assertEqual(ai.extra_data['security_issues_count'], 3)
        self.assertEqual(ai.severity, ActionItem.SEVERITY_HIGH)
        self.assertIn("3 security issues", ai.short_description)

    def test_get_template_action_item(self):
        self.mock_json_data('nodsa')
        self.run_task()
        ai = ActionItem.objects.get(
            item_type__type_name='debian-security-issue-in-jessie')

        response = self.client.get(ai.get_absolute_url())

        self.assertTemplateUsed(response,
                                'debian/security-issue-action-item.html')


class CodeSearchLinksTest(TestCase):

    """
    Tests that the code search links are shown in the package page.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')
        self.stable = Repository.objects.create(
            name='Debian Stable', codename='wheezy', suite='stable',
            shorthand='stable')
        self.unstable = Repository.objects.create(
            name='Debian Unstable', codename='sid', suite='unstable',
            shorthand='unstable')

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def browse_link_in_content(self, content):
        html = soup(content, 'html.parser')
        for a_tag in html.findAll('a', {'href': True}):
            if a_tag['href'].startswith('https://sources.debian.org'):
                return True
        return False

    def search_form_in_content(self, content):
        html = soup(content, 'html.parser')
        return bool(html.find('form', {'class': 'code-search-form'}))

    def test_package_in_stable(self):
        """
        Tests that only the browse source code link appears when the package is
        only in stable.
        """
        # Add the package to stable
        self.stable.add_source_package(self.package)

        response = self.get_package_page_response(self.package.name)

        self.assertTrue(self.browse_link_in_content(response.content))
        self.assertFalse(self.search_form_in_content(response.content))

    def test_package_not_in_allowed_repository(self):
        """
        Tests that no links are added when the package is not found in one of
        the allowed repositories
        (:attr:`distro_tracker.vendor.debian.tracker_panels.SourceCodeSearchLinks.ALLOWED_REPOSITORIES`)
        """
        other_repository = Repository.objects.create(name='some-other-repo')
        other_repository.add_source_package(self.package)

        response = self.get_package_page_response(self.package.name)

        self.assertFalse(self.browse_link_in_content(response.content))
        self.assertFalse(self.search_form_in_content(response.content))

    def test_package_in_unstable(self):
        """
        Tests that the search form is shown in addition to the browse source
        link if the package is found in unstable.
        """
        self.unstable.add_source_package(self.package)

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf-8')
        self.assertTrue(self.browse_link_in_content(response_content))
        self.assertTrue(self.search_form_in_content(response_content))

    def test_pseudo_package(self):
        """
        Tests that neither link is shown when the package is a pseudo package,
        instead of a source package.
        """
        pseudo_package = PseudoPackageName.objects.create(name='somepackage')

        response = self.get_package_page_response(pseudo_package.name)

        response_content = response.content.decode('utf-8')
        self.assertFalse(self.browse_link_in_content(response_content))
        self.assertFalse(self.search_form_in_content(response_content))

    def test_code_search_view_missing_query_parameter(self):
        """Test codesearch view with missing query parameter"""
        # missing query parameter
        response = self.client.get(reverse('dtracker-code-search'),
                                   {'package': self.package.name})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Both package and query are required parameters',
                      response.content.decode('utf-8'))

    def test_code_search_view_missing_package_parameter(self):
        """Test codesearch view with missing package parameter"""
        response = self.client.get(reverse('dtracker-code-search'),
                                   {'query': 'def'})
        self.assertEqual(response.status_code, 400)

    def test_code_search_view_empty_query(self):
        """Test codesearch view with empty query"""
        response = self.client.get(reverse('dtracker-code-search'),
                                   {'package': self.package.name,
                                    'query': ''})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Empty query is not allowed',
                      response.content.decode('utf-8'))

    def test_code_search_view_redirect_simple(self):
        """Test codesearch view redirects properly"""
        response = self.client.get(reverse('dtracker-code-search'),
                                   {'package': self.package.name,
                                    'query': 'def'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(CodeSearchView.BASE_URL, response['Location'])

    def test_code_search_view_urlencode_where_needed(self):
        """Test codesearch view urlencode stuff"""
        response = self.client.get(reverse('dtracker-code-search'),
                                   {'package': 'g++',
                                    'query': 'bépo'})
        self.assertEqual(response.status_code, 302)
        self.assertIn("q=b%C3%A9po+package%3Ag%2B%2B", response['Location'])


class PopconLinkTest(TestCase):

    """
    Tests that the popcon link is added to source package pages.
    """

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def test_source_package(self):
        package_name = SourcePackageName.objects.create(name='dummy')
        package = SourcePackage.objects.create(
            source_package_name=package_name,
            version='1.0.0')

        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf8')
        self.assertIn('popcon', response_content)

    def test_pseudo_package(self):
        package = PseudoPackageName.objects.create(name='somepackage')

        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf-8')
        self.assertNotIn('popcon', response_content)


class DebciLinkTest(TestCase, TemplateTestsMixin):

    """
    Tests that the debci link is added to source package pages.
    """

    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def test_package_with_debci_report(self):
        PackageData.objects.create(
            package=self.package_name,
            key='debci',
            value={'debci report': 'not null'}
        )

        response = self.get_package_page_response(self.package.name)
        self.assertLinkIsInResponse(
            response,
            'https://ci.debian.net/packages/d/dummy/'
        )

    def test_package_without_debci_report(self):
        response = self.get_package_page_response(self.package.name)
        self.assertLinkIsNotInResponse(
            response,
            'https://ci.debian.net/packages/d/dummy/'
        )


class DebtagsLinkTest(TestCase):

    """
    Tests that the debtags link is added to source package pages.
    """

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def test_source_package(self):
        package_name = SourcePackageName.objects.create(name='dummy')
        package = SourcePackage.objects.create(
            source_package_name=package_name,
            version='1.0.0')
        PackageData.objects.create(
            package=package.source_package_name,
            key='general',
            value={
                'name': 'dummy',
                'maintainer': {
                    'email': 'hertzog@debian.org',
                }
            }
        )

        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf8')
        self.assertIn('edit tags', response_content)

    def test_pseudo_package(self):
        package = PseudoPackageName.objects.create(name='somepackage')

        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf-8')
        self.assertNotIn('edit tags', response_content)


class ScreenshotsLinkTest(TestCase):
    """
    Tests that the screenshots link is added to source package pages.
    """
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(name='dummy')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')
        PackageData.objects.create(
            package=self.package.source_package_name,
            key='screenshots',
            value={'screenshots': 'true'}
        )

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def test_source_package_with_screenshot(self):
        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf8')
        self.assertIn('screenshots', response_content)

    def test_source_package_without_screenshot(self):
        package_name = SourcePackageName.objects.create(name='other')
        package = SourcePackage.objects.create(
            source_package_name=package_name,
            version='1.0.0')
        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf8')
        self.assertNotIn('screenshots', response_content)

    def test_pseudo_package(self):
        package = PseudoPackageName.objects.create(name='somepackage')

        response = self.get_package_page_response(package.name)

        response_content = response.content.decode('utf-8')
        self.assertNotIn('screenshots', response_content)


class UpdatePiupartsTaskTests(TestCase):
    suites = []

    @staticmethod
    def stub_get_piuparts_content(suite, stub_data):
        return stub_data.get(suite, None)

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = UpdatePiuPartsTask()
        # Stub the data providing methods
        self.return_content = {}
        self.task._get_piuparts_content = mock.MagicMock(
            side_effect=curry(
                UpdatePiupartsTaskTests.stub_get_piuparts_content,
                stub_data=self.return_content))

        # Clear the actual list of suites
        self.suites[:] = []

    def run_task(self):
        self.task.execute()

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdatePiuPartsTask.ACTION_ITEM_TYPE_NAME)[0]

    def set_suites(self, suites):
        """
        Sets the list of suites which the task should use.
        """
        for suite in suites:
            self.suites.append(suite)

    def set_piuparts_content(self, suite, fail_packages, pass_packages=()):
        """
        Sets the given list of packages as a stub value which is returned to
        the task for the given suite.
        """
        content = '\n'.join('{}: fail'.format(pkg) for pkg in fail_packages)
        content += '\n'.join('{}: pass'.format(pkg) for pkg in pass_packages)

        self.return_content[suite] = content.encode('utf-8')

    def assert_get_piuparts_called_with(self, suites):
        """
        Asserts that the _get_piuparts_content method was called only with the
        given suites.
        """
        self.assertEqual(
            len(suites),
            len(self.task._get_piuparts_content.mock_calls))
        for suite, mock_call in \
                zip(suites, self.task._get_piuparts_content.call_args_list):
            self.assertEqual(mock.call(suite), mock_call)

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_retrieves_all_suites(self):
        """
        Tests that the task tries to retrieve the data for each of the suites
        given in the
        :data:`distro_tracker.project.local_settings.DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES`
        setting.
        """
        suites = ['sid', 'jessie']
        self.set_suites(suites)

        self.run_task()

        self.assert_get_piuparts_called_with(suites)

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_created(self):
        """
        Tests that an action item is created when a source package is found to
        be failing the piuparts test in a single suite.
        """
        packages = [self.package.name]
        suite = 'jessie'
        self.set_suites([suite])
        self.set_piuparts_content(suite, packages)

        self.run_task()

        # Created the action item.
        self.assertEqual(1, ActionItem.objects.count())
        # Correct item type?
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            UpdatePiuPartsTask.ACTION_ITEM_TYPE_NAME,
            item.item_type.type_name)
        # Correct template?
        self.assertEqual(
            UpdatePiuPartsTask.ACTION_ITEM_TEMPLATE,
            item.full_description_template)
        # Correct list of failing suites?
        self.assertEqual([suite], item.extra_data['suites'])

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_not_created(self):
        """
        Tests that an action item is not created when a source package is found
        to be passing the piuparts test.
        """
        packages = [self.package.name]
        suite = 'jessie'
        self.set_suites([suite])
        self.set_piuparts_content(suite, [], packages)

        self.run_task()

        # No action item created
        self.assertEqual(0, ActionItem.objects.count())

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_updated(self):
        """
        Tests that an existing action item is updated when there are updated
        piuparts stats for the package.
        """
        # Create an action item: package failing in sid
        ActionItem.objects.create(
            package=self.package,
            item_type=self.get_action_item_type(),
            short_description="Desc",
            extra_data={
                'suites': ['sid']
            })
        packages = [self.package.name]
        suite = 'jessie'
        self.set_suites([suite])
        self.set_piuparts_content(suite, packages)

        self.run_task()

        # Still only one action item
        self.assertEqual(1, ActionItem.objects.count())
        # Updated a list of suites
        item = ActionItem.objects.all()[0]
        self.assertEqual([suite], item.extra_data['suites'])

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_multiple_suites(self):
        """
        Tests that an action item contains all suites in which a failure was
        detected.
        """
        packages = [self.package.name]
        # Suites where piuparts is failing
        suites = ['sid', 'jessie']
        # Suites where piuparts is ok
        pass_suites = ['wheezy']
        self.set_suites(suites + pass_suites)
        for suite in suites:
            self.set_piuparts_content(suite, packages)
        for suite in pass_suites:
            self.set_piuparts_content(suite, [], packages)

        self.run_task()

        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        # All the suites found in extra data?
        self.assertEqual(len(suites), len(item.extra_data['suites']))
        for suite in suites:
            self.assertIn(suite, item.extra_data['suites'])

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_not_updated_when_unchanged(self):
        """
        Tests that an existing action item is not updated when the update
        detects that the stats have not changed.
        """
        # Create an action item: package failing in multiple repositories
        item = ActionItem.objects.create(
            package=self.package,
            item_type=self.get_action_item_type(),
            short_description="Desc",
            extra_data={
                'suites': ['jessie', 'sid']
            })
        old_timestamp = item.last_updated_timestamp
        packages = [self.package.name]
        # Different order of suites than the one found in the current item
        # should not affect anything
        suites = ['sid', 'jessie']
        self.set_suites(suites)
        for suite in suites:
            self.set_piuparts_content(suite, packages)

        self.run_task()

        # Still only one action item
        self.assertEqual(1, ActionItem.objects.count())
        # Still the same list of suites
        item = ActionItem.objects.all()[0]
        self.assertEqual(['jessie', 'sid'], item.extra_data['suites'])
        # Time stamp unchanged
        self.assertEqual(old_timestamp, item.last_updated_timestamp)

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_removed(self):
        """
        Tests that an existing action item is removed if the update indicates
        the package is passing piuparts tests in all suites.
        """
        ActionItem.objects.create(
            package=self.package,
            item_type=self.get_action_item_type(),
            short_description="Desc",
            extra_data={
                'suites': ['jessie', 'sid']
            })
        packages = [self.package.name]
        # Different order of suites than the one found in the current item
        # should not affect anything
        suites = ['sid', 'jessie']
        self.set_suites(suites)
        # Set the package as passing in all suites
        for suite in suites:
            self.set_piuparts_content(suite, [], packages)

        self.run_task()

        # Action item removed?
        self.assertEqual(0, ActionItem.objects.count())

    @override_settings(DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES=suites)
    def test_action_item_removed_no_stats(self):
        """
        Tests that an existing action item is removed if the update indicates
        the package no longer has any piuparts stats.
        """
        ActionItem.objects.create(
            package=self.package,
            item_type=self.get_action_item_type(),
            short_description="Desc",
            extra_data={
                'suites': ['jessie', 'sid']
            })

        self.run_task()

        self.assertEqual(0, ActionItem.objects.count())


class UpdateUbuntuStatsTaskTests(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_taks.UpdateUbuntuStatsTask`
    task.
    """

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = UpdateUbuntuStatsTask()
        # Stub the data providing method
        self.task._get_versions_content = mock.MagicMock(return_value=b'')
        self.task._get_bug_stats_content = mock.MagicMock(return_value=b'')
        self.task._get_ubuntu_patch_diff_content = mock.MagicMock(
            return_value=b'')

    def set_versions_content(self, versions):
        """
        Sets the stub content for the list of Ubuntu package versions.

        :param versions: A list of (package_name, version) pairs which should
            be found in the response.
        """
        self.task._get_versions_content.return_value = '\n'.join(
            '{pkg} {ver}'.format(pkg=pkg, ver=ver)
            for pkg, ver in versions).encode('utf-8')

    def set_bugs_content(self, bugs):
        """
        Sets the stub content for the list of Ubuntu package bugs.

        :param bugs: A list of (package_name, bug_count, patch_count) tuples
            which should be found in the response.
        """
        self.task._get_bug_stats_content.return_value = '\n'.join(
            '{pkg}|{cnt}|{merged}'.format(pkg=pkg, cnt=cnt, merged=merged)
            for pkg, cnt, merged in bugs).encode('utf-8')

    def set_diff_content(self, diffs):
        """
        Sets the stub content for the list of diff URLs.

        :param diffs: A list of (package_name, diff_url) pairs which should be
            found in the response.
        """
        self.task._get_ubuntu_patch_diff_content.return_value = '\n'.join(
            '{pkg} {url}'.format(pkg=pkg, url=url)
            for pkg, url in diffs).encode('utf-8')

    def run_task(self):
        self.task.execute()

    def test_ubuntu_package_created(self):
        """
        Tests that a new
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` model
        instance is created if an Ubuntu version of the package is found.
        """
        version = '1.0-1ubuntu1'
        self.set_versions_content([
            (self.package.name, version)
        ])

        self.run_task()

        # Created an ubuntu package
        self.assertEqual(1, UbuntuPackage.objects.count())
        # Has the correct version?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        self.assertEqual(version, ubuntu_pkg.version)
        # Linked to the correct package?
        self.assertEqual(self.package.name, ubuntu_pkg.package.name)

    def test_ubuntu_package_removed(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        removed if an Ubuntu version of the package is no longer found.
        """
        version = '1.0-1ubuntu1'
        # Create an old ubuntu package
        UbuntuPackage.objects.create(
            package=self.package,
            version=version)
        self.set_versions_content([])

        self.run_task()

        # The package is removed.
        self.assertEqual(0, UbuntuPackage.objects.count())

    def test_ubuntu_package_bugs_created(self):
        """
        Tests that a :class:`distro_tracker.vendor.debian.models.UbuntuPackage`
        instance which is created for a new Ubuntu package contains the bugs
        count.
        """
        version = '1.0-1ubuntu1'
        self.set_versions_content([
            (self.package.name, version)
        ])
        bug_count, patch_count = 5, 1
        self.set_bugs_content([
            (self.package.name, bug_count, patch_count),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # Has the correct bugs count?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'bug_count': bug_count,
            'patch_count': patch_count
        }
        self.assertDictEqual(expected, ubuntu_pkg.bugs)

    def test_ubuntu_package_bugs_updated(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain the new Ubuntu package bugs when it
        previously contained no bug information.
        """
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version)
        bug_count, patch_count = 5, 1
        self.set_bugs_content([
            (self.package.name, bug_count, patch_count),
        ])
        self.set_versions_content([
            (self.package.name, version),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # Has the correct bugs count?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'bug_count': bug_count,
            'patch_count': patch_count
        }
        self.assertDictEqual(expected, ubuntu_pkg.bugs)

    def test_ubuntu_package_bugs_updated_existing(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain the new Ubuntu package bugs when it
        previously contained older bug information.
        """
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version,
            bugs={
                'bug_count': 100,
                'patch_count': 50,
            })
        bug_count, patch_count = 5, 1
        self.set_bugs_content([
            (self.package.name, bug_count, patch_count),
        ])
        self.set_versions_content([
            (self.package.name, version),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # Has the correct bugs count?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'bug_count': bug_count,
            'patch_count': patch_count
        }
        self.assertDictEqual(expected, ubuntu_pkg.bugs)

    def test_ubuntu_package_bug_stats_removed(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain no bug stats when there are no bug stats
        found for the package by the update.
        """
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version,
            bugs={
                'bug_count': 100,
                'patch_count': 50,
            })
        self.set_versions_content([
            (self.package.name, version),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # No more bug stats?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        self.assertIsNone(ubuntu_pkg.bugs)

    def test_ubuntu_package_diff_created(self):
        """
        Tests that a :class:`distro_tracker.vendor.debian.models.UbuntuPackage`
        instance which is created for a new Ubuntu package contains the diff
        info.
        """
        version = '1.1-1ubuntu1'
        self.set_versions_content([
            (self.package.name, version)
        ])
        # Have the patch version be different than the package version
        patch_version = '1.0-1ubuntu1'
        diff_url = 'd/dummy-package/dummy-package_{ver}.patch'.format(
            ver=patch_version)
        self.set_diff_content([
            (self.package.name, diff_url),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # Has the correct diff info?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'version': patch_version,
            'diff_url': diff_url,
        }
        self.assertDictEqual(expected, ubuntu_pkg.patch_diff)

    def test_ubuntu_package_diff_updated(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain the new Ubuntu patch diffs when it
        previously contained no diff info.
        """
        # Create an UbuntuPackage with no patch diff info
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version)
        self.set_versions_content([
            (self.package.name, version)
        ])
        diff_url = 'd/dummy-package/dummy-package_{ver}.patch'.format(
            ver=version)
        self.set_diff_content([
            (self.package.name, diff_url),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # The diff info is updated?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'version': version,
            'diff_url': diff_url,
        }
        self.assertDictEqual(expected, ubuntu_pkg.patch_diff)

    def test_ubuntu_package_diff_updated_existing(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain the new Ubuntu patch diff info when it
        previously contained older patch diff info.
        """
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version,
            patch_diff={
                'version': '1.0-0',
                'diff_url': 'http://old.url.com',
            })
        self.set_versions_content([
            (self.package.name, version)
        ])
        diff_url = 'd/dummy-package/dummy-package_{ver}.patch'.format(
            ver=version)
        self.set_diff_content([
            (self.package.name, diff_url),
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # The diff info is updated?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        expected = {
            'version': version,
            'diff_url': diff_url,
        }
        self.assertDictEqual(expected, ubuntu_pkg.patch_diff)

    def test_ubuntu_package_diff_removed(self):
        """
        Tests that an existing
        :class:`distro_tracker.vendor.debian.models.UbuntuPackage` instance is
        correctly updated to contain no diff info when there is no diff info
        found for the package by the update.
        """
        version = '1.0-1ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=version,
            patch_diff={
                'version': '1.0-0',
                'diff_url': 'http://old.url.com',
            })
        self.set_versions_content([
            (self.package.name, version)
        ])

        self.run_task()

        self.assertEqual(1, UbuntuPackage.objects.count())
        # No more patch diff info?
        ubuntu_pkg = UbuntuPackage.objects.all()[0]
        self.assertIsNone(ubuntu_pkg.patch_diff)


class UbuntuPanelTests(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_panels.UbuntuPanel` panel.
    """

    def setUp(self):
        self.package = PackageName.objects.create(
            source=True,
            name='dummy-package')

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def ubuntu_panel_in_content(self, content):
        html = soup(content, 'html.parser')
        for panel in html.findAll('div', {'class': 'panel-heading'}):
            if 'ubuntu' in str(panel):
                return True

        return False

    def test_panel_displayed(self):
        """
        Tests that the panel is displayed when the package has a known Ubuntu
        version.
        """
        # Create the ubuntu version
        ubuntu_version = '1.0.0-ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=ubuntu_version)

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf8')
        self.assertTrue(self.ubuntu_panel_in_content(response_content))
        self.assertIn(ubuntu_version, response_content)

    def test_panel_not_displayed(self):
        """
        Tests tat the panel is not displayed when the package has no known
        Ubuntu versions.
        """
        # Sanity check: no Ubuntu version for the packag?
        self.assertEqual(
            0,
            UbuntuPackage.objects.filter(package=self.package).count())

        response = self.get_package_page_response(self.package.name)

        self.assertFalse(self.ubuntu_panel_in_content(response.content))

    def test_bugs_displayed(self):
        """
        Tests that the Ubuntu bug counts are displayed in the Ubuntu panel, if
        they exist for the package.
        """
        ubuntu_version = '1.0.0-ubuntu1'
        bug_count, patch_count = 10, 5
        UbuntuPackage.objects.create(
            package=self.package,
            version=ubuntu_version,
            bugs={
                'bug_count': bug_count,
                'patch_count': patch_count,
            })

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf8')
        self.assertIn("10 bugs", response_content)
        self.assertIn("5 patches", response_content)

    def test_patch_diff_displayed(self):
        """
        Tests that the Ubuntu patch diff link is displayed in the Ubuntu panel,
        if it exists for the package.
        """
        ubuntu_version = '1.0.0-ubuntu1'
        diff_url = 'd/dummy-package/dummy-package_1.0.0-ubuntu1'
        UbuntuPackage.objects.create(
            package=self.package,
            version=ubuntu_version,
            patch_diff={
                'diff_url': diff_url,
                'version': ubuntu_version,
            })

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf-8')
        self.assertIn(
            'patches for {}'.format(ubuntu_version),
            response_content)
        self.assertIn(ubuntu_version, response_content)


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateWnppStatsTaskTests(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateWnppStatsTask`
    task.
    """

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = UpdateWnppStatsTask()
        # Stub the data providing method
        self.task._get_wnpp_content = mock.MagicMock(return_value='')

    def get_action_item_type(self):
        return ActionItemType.objects.get_or_create(
            type_name=UpdateWnppStatsTask.ACTION_ITEM_TYPE_NAME)[0]

    def set_wnpp_content(self, content):
        """
        Sets the stub wnpp content which the task will retrieve once it runs.
        :param content: A list of (package_name, issues) pairs. ``issues`` is
            a list of dicts describing the WNPP bugs the package has.
        """
        return '\n'.join(
            '{pkg}: {issues}'.format(
                pkg=pkg,
                issues='|'.join(
                    '{type} {bug_id}'.format(
                        type=issue['wnpp_type'],
                        bug_id=issue['bug_id'])
                    for issue in issues))
            for pkg, issues in content)

    def run_task(self):
        self.task.execute()

    def test_action_item_created(self, mock_requests):
        """
        Tests that an :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is created when the
        package has a WNPP bug.
        """
        wnpp_type, bug_id = 'O', 12345
        content = self.set_wnpp_content([(
            self.package.name, [{
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }]
        )])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # An action item has been created
        self.assertEqual(1, ActionItem.objects.count())
        # The item has the correct type and template
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            UpdateWnppStatsTask.ACTION_ITEM_TYPE_NAME,
            item.item_type.type_name)
        self.assertEqual(
            UpdateWnppStatsTask.ACTION_ITEM_TEMPLATE,
            item.full_description_template)
        # The extra data is correctly set?
        expected_data = {
            'wnpp_type': wnpp_type,
            'bug_id': bug_id,
        }
        self.assertEqual(expected_data, item.extra_data['wnpp_info'])
        # Test that the short description is correctly set.
        dsc = ('<a href="https://bugs.debian.org/12345">O: This package has'
               ' been orphaned and needs a maintainer.</a>')
        self.assertEqual(dsc, item.short_description)

    def test_action_item_created_unknown_type(self, mock_requests):
        """
        Tests that an :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is created when the
        package has a WNPP bug of an unknown type.
        """
        wnpp_type, bug_id = 'RFC', 12345
        content = self.set_wnpp_content([(
            self.package.name, [{
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }]
        )])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # An action item has been created
        self.assertEqual(1, ActionItem.objects.count())
        # The item has the correct type and template
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            UpdateWnppStatsTask.ACTION_ITEM_TYPE_NAME,
            item.item_type.type_name)
        self.assertEqual(
            UpdateWnppStatsTask.ACTION_ITEM_TEMPLATE,
            item.full_description_template)
        # The extra data is correctly set?
        expected_data = {
            'wnpp_type': wnpp_type,
            'bug_id': bug_id,
        }
        self.assertEqual(expected_data, item.extra_data['wnpp_info'])
        # Test that the short description is correctly set.
        dsc = ('<a href="https://bugs.debian.org/12345">RFC: The WNPP database'
               ' contains an entry for this package.</a>')
        self.assertEqual(dsc, item.short_description)

    def test_action_item_updated(self, mock_requests):
        """
        Tests that an existing :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is updated when there
        are changes to the WNPP bug info.
        """
        # Create an existing action item
        old_bug_id = 54321
        old_item = ActionItem.objects.create(
            item_type=self.get_action_item_type(),
            package=self.package,
            extra_data={
                'wnpp_info': {
                    'wnpp_type': 'O',
                    'bug_id': old_bug_id,
                }
            })
        old_timestamp = old_item.last_updated_timestamp
        # Set new WNPP info
        wnpp_type, bug_id = 'O', 12345
        content = self.set_wnpp_content([(
            self.package.name, [{
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }]
        )])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # Still one action item
        self.assertEqual(1, ActionItem.objects.count())
        # The item has been updated
        item = ActionItem.objects.all()[0]
        self.assertNotEqual(old_timestamp, item.last_updated_timestamp)
        # The extra data is updated as well?
        expected_data = {
            'wnpp_type': wnpp_type,
            'bug_id': bug_id,
        }
        self.assertEqual(expected_data, item.extra_data['wnpp_info'])

    def test_action_item_not_updated(self, mock_requests):
        """
        Tests that an existing :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is not updated when
        there are no changes to the WNPP bug info.
        """
        # Create an existing action item
        wnpp_type, bug_id = 'O', 12345
        old_item = ActionItem.objects.create(
            item_type=self.get_action_item_type(),
            package=self.package,
            extra_data={
                'wnpp_info': {
                    'wnpp_type': wnpp_type,
                    'bug_id': bug_id,
                }
            })
        old_timestamp = old_item.last_updated_timestamp
        # Set "new" WNPP info
        content = self.set_wnpp_content([(
            self.package.name, [{
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }]
        )])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # Still one action item
        self.assertEqual(1, ActionItem.objects.count())
        # The item has not been changed
        item = ActionItem.objects.all()[0]
        self.assertEqual(old_timestamp, item.last_updated_timestamp)

    def test_action_item_removed(self, mock_requests):
        """
        Tests that an existing :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is removed when there
        is no more WNPP bug info.
        """
        # Create an existing action item
        wnpp_type, bug_id = 'O', 12345
        ActionItem.objects.create(
            item_type=self.get_action_item_type(),
            package=self.package,
            extra_data={
                'wnpp_info': {
                    'wnpp_type': wnpp_type,
                    'bug_id': bug_id,
                },
            })
        # Set "new" WNPP info
        set_mock_response(mock_requests, text="")

        self.run_task()

        # Still one action item
        # No more actino items
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_not_created(self, mock_requests):
        """
        Tests that an :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is not created for non
        existing packages.
        """
        wnpp_type, bug_id = 'O', 12345
        content = self.set_wnpp_content([(
            'no-exist', [{
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }]
        )])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # No action items
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_multiple_packages(self, mock_requests):
        """
        Tests that an :class:`ActionItem
        <distro_tracker.core.models.ActionItem>` instance is created for
        multiple packages.
        """
        wnpp = [
            {
                'wnpp_type': 'O',
                'bug_id': 12345,
            },
            {
                'wnpp_type': 'RM',
                'bug_id': 11111,
            }
        ]
        other_package = PackageName.objects.create(
            name='other-package',
            source=True)
        packages = [other_package, self.package]
        content = self.set_wnpp_content([
            (package.name, [wnpp_item])
            for package, wnpp_item in zip(packages, wnpp)
        ])
        set_mock_response(mock_requests, text=content)

        self.run_task()

        # An action item is created for all packages
        self.assertEqual(2, ActionItem.objects.count())
        for package, wnpp_info in zip(packages, wnpp):
            self.assertEqual(1, package.action_items.count())
            item = package.action_items.all()[0]
            self.assertEqual(wnpp_info, item.extra_data['wnpp_info'])


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class UpdateNewQueuePackagesTests(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateNewQueuePackages`
    task.
    """

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')

        self.task = UpdateNewQueuePackages()
        # Stub the data providing method
        self.new_content = ''
        self.task._get_new_content = mock.MagicMock(return_value='')

    def add_package_to_new(self, package):
        package_content = '\n'.join(
            '{}: {}'.format(key, value)
            for key, value in package.items())
        self.new_content += package_content + '\n\n'

    def run_task(self):
        self.task._get_new_content.return_value = self.new_content
        self.task.execute()

    def get_new_info(self, package):
        """
        Helper method which returns the package's
        :class:`PackageData
        <distro_tracker.core.models.PackageData>` instance containing
        the NEW queue info, or ``None`` if there is no such instance.
        """
        try:
            return package.data.get(key=UpdateNewQueuePackages.DATA_KEY)
        except PackageData.DoesNotExist:
            return None

    def test_single_distribution(self):
        """
        Tests that the NEW queue information is correctly extracted when the
        package is found in only one distribution in the NEW queue.
        """
        distribution = 'sid'
        version = '1.0.0'
        self.add_package_to_new({
            'Version': version,
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNotNone(new_info)
        # The distribution is found in the info
        self.assertIn(distribution, new_info.value)
        # The correct version is found in the info
        self.assertEqual(version, new_info.value[distribution]['version'])

    def test_single_distribution_multiple_versions(self):
        """
        Tests that the NEW queue information is correctly extracted when the
        package has multiple versions for a distribution.
        """
        distribution = 'sid'
        latest_version = '3.0.0'
        self.add_package_to_new({
            'Version': '1.0 ' + latest_version + ' 2.0',
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNotNone(new_info)
        # The distribution is found in the info
        self.assertIn(distribution, new_info.value)
        # The correct version is found in the info
        self.assertEqual(
            latest_version,
            new_info.value[distribution]['version'])

    def test_multiple_distributions(self):
        """
        Tests that the NEW queue information is correctly extracted when the
        package has multiple distributions in the NEW queue.
        """
        distributions = ['sid', 'stable-security']
        versions = ['1.0.0', '2.0.0']
        for dist, ver in zip(distributions, versions):
            self.add_package_to_new({
                'Version': ver,
                'Source': self.package.name,
                'Queue': 'new',
                'Distribution': dist,
            })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNotNone(new_info)
        # All distributions found in the info with the correct corresponding
        # version.
        for dist, ver in zip(distributions, versions):
            self.assertIn(dist, new_info.value)
            # The correct version is found in the info
            self.assertEqual(ver, new_info.value[dist]['version'])

    def test_multiple_entries_single_distribution(self):
        """
        Tests that the latest version is always used for a distribution no
        matter if it is found in a separate entry instead of being in the same
        Version field.
        """
        distribution = 'sid'
        latest_version = '3.0.0'
        self.add_package_to_new({
            'Version': '1.0',
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })
        self.add_package_to_new({
            'Version': latest_version,
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })
        self.add_package_to_new({
            'Version': '2.0',
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNotNone(new_info)
        # The distribution is found in the info
        self.assertIn(distribution, new_info.value)
        # The correct version is found in the info
        self.assertEqual(
            latest_version,
            new_info.value[distribution]['version'])

    def test_malformed_entry(self):
        """
        Tests that nothing is created when the package's entry is missing the
        Queue field.
        """
        distribution = 'sid'
        version = '1.0.0'
        self.add_package_to_new({
            'Version': version,
            'Source': self.package.name,
            'Distribution': distribution,
        })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNone(new_info)

    def test_entry_updated(self):
        """
        Tests that the NEW info is updated when the entry is updated.
        """
        distribution = 'sid'
        old_version = '1.0.0'
        version = '2.0.0'
        # Create an old entry
        PackageData.objects.create(
            package=self.package,
            key=UpdateNewQueuePackages.DATA_KEY,
            value={
                distribution: {
                    'version': old_version,
                }
            })
        self.add_package_to_new({
            'Version': version,
            'Source': self.package.name,
            'Queue': 'new',
            'Distribution': distribution,
        })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNotNone(new_info)
        # The distribution is found in the info
        self.assertIn(distribution, new_info.value)
        # The correct version is found in the info
        self.assertEqual(version, new_info.value[distribution]['version'])

    def test_entry_dropped(self):
        """
        Tests that the NEW entry is correctly dropped from PackageData
        when the entry is gone.
        """
        distribution = 'sid'
        old_version = '1.0.0'
        # Create an old entry
        PackageData.objects.create(
            package=self.package,
            key=UpdateNewQueuePackages.DATA_KEY,
            value={
                distribution: {
                    'version': old_version,
                }
            })

        self.run_task()

        new_info = self.get_new_info(self.package)
        self.assertIsNone(new_info)


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class NewQueueVersionsPanelTests(TestCase):

    """
    Tests that the NEW queue versions are displayed in the versions panel.
    """

    def setUp(self):
        self.package = PackageName.objects.create(
            source=True,
            name='dummy-package')
        self.package.data.create(key='versions', value={})

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def add_new_queue_entry(self, distribution, version):
        info, _ = PackageData.objects.get_or_create(
            package=self.package, key=UpdateNewQueuePackages.
            DATA_KEY)
        if not info.value:
            info.value = {}
        info.value.update({
            distribution: {
                'version': version,
            }
        })
        info.save()

    def test_single_new_version(self):
        """
        Tests for when a package has a version in NEW for only one
        distribution.
        """
        distribution = 'sid'
        version = '1.0.0~sidtest'
        self.add_new_queue_entry(distribution, version)

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf-8')
        self.assertIn('NEW/sid', response_content)
        self.assertIn(version, response_content)

    def test_multiple_distributions(self):
        """
        Tests for when a package has a version in NEW for multiple
        distributions.
        """
        dists = ['sid', 'stable-security']
        versions = ['1.0.0~sidtest', '1.0.0~stable-sec-test']
        for dist, ver in zip(dists, versions):
            self.add_new_queue_entry(dist, ver)

        response = self.get_package_page_response(self.package.name)

        response_content = response.content.decode('utf8')
        for dist, ver in zip(dists, versions):
            self.assertIn('NEW/' + dist, response_content)
            self.assertIn(ver, response_content)


class ImportOldNewsTests(TestCase):

    """
    Tests the management command for importing old news.
    """

    def create_message(self, subject, from_email, date, content):
        msg = Message()
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['Date'] = date
        msg.set_payload(content.encode('utf-8'), 'utf-8')

        return msg

    def test_news_created(self):
        packages = ['dpkg', 'dummy', 'asdf', '000']
        email = 'user@domain.com'
        subject_template = 'Message to {}'
        content_template = "Hello Öäüßčćž한글{}"
        date = 'Mon, 28 Nov 2005 15:47:11 -0800'

        with make_temp_directory('old-pts') as old_distro_tracker_root:
            # Make the expected directory structure and add some news
            for package in packages:
                PackageName.objects.create(name=package, source=True)
                news_dir = os.path.join(
                    old_distro_tracker_root, package[0], package, 'news')
                os.makedirs(news_dir)

                # Add a news for this package
                msg = self.create_message(
                    subject_template.format(package),
                    email,
                    date,
                    content_template.format(package))
                with open(os.path.join(news_dir, 'news.txt'), 'wb') as f:
                    if hasattr(msg, 'as_bytes'):
                        content = msg.as_bytes()
                    else:
                        content = msg.as_string()
                    f.write(content)

            call_command('tracker_import_old_news', old_distro_tracker_root)

            # All news items created
            self.assertEqual(len(packages), News.objects.count())
            # All news item have the correct associated content
            for package in packages:
                news = News.objects.get(package__name=package)
                subject = subject_template.format(package)
                content = content_template.format(package).encode('utf-8')
                self.assertEqual(subject, news.title)
                # The date of the news item is correctly set to the old item's
                # date?
                self.assertEqual(
                    '2005 11 28',
                    news.datetime_created.strftime('%Y %m %d'))
                # The news item's content can be seamlessly transformed back to
                # an email Message object.
                msg = message_from_bytes(news.content)
                self.assertEqual(subject, msg['Subject'])
                self.assertEqual(content, msg.get_payload(decode=True))


class ImportOldSubscribersTests(TestCase):

    """
    Tests for the
    :mod:`distro_tracker.vendor.debian.management.commands.tracker_import_old_subscriber_dump`
    management command.
    """

    def setUp(self):
        self.packages = {}

    def set_package_subscribers(self, package, subscribers):
        self.packages[package] = subscribers

    def get_input(self):
        return '\n'.join(
            '{} => [ {} ]'.format(
                package,
                ' '.join(subscribers))
            for package, subscribers in self.packages.items()
        )

    def run_command(self):
        command = ImportOldSubscribersCommand()
        command.stdin = io.StringIO(self.get_input())
        command.handle()

    def assert_subscribed_to_package(self, package, subscribers):
        for subscriber in subscribers:
            self.assertTrue(Subscription.objects.filter(
                package=package,
                email_settings__user_email__email=subscriber).exists())

    def test_non_existing_package_imported(self):
        """
        Test that when a package that is found in the dump being imported
        does not exist, a new "subscription-only" package is automatically
        created.
        """
        package_name = 'new-package'
        subscribers = [
            'email@domain.com',
            'other@domain.com',
        ]
        self.set_package_subscribers(package_name, subscribers)

        self.run_command()

        self.assertEqual(1, PackageName.objects.count())
        package = PackageName.objects.all()[0]
        self.assertEqual(package_name, package.name)
        self.assert_subscribed_to_package(package, subscribers)

    def test_existing_package_imported(self):
        """
        Tests that when a package already exists, only a subscription is
        created, without modifying the package.
        """
        package_name = 'new-package'
        SourcePackageName.objects.create(name=package_name)
        subscribers = [
            'email@domain.com',
            'other@domain.com',
        ]
        self.set_package_subscribers(package_name, subscribers)

        self.run_command()

        # Still only one package
        self.assertEqual(1, PackageName.objects.count())
        # Still a source package
        self.assertEqual(1, SourcePackageName.objects.count())
        package = PackageName.objects.all()[0]
        self.assertEqual(package_name, package.name)
        # Correct subscribers imported
        self.assert_subscribed_to_package(package, subscribers)

    def test_multiple_subscriptions_imported(self):
        """
        Tests that multiple subscriptions for a single user are imported.
        """
        packages = [
            PackageName.objects.create(name='pkg1', source=True),
            PackageName.objects.create(name='pkg2', source=True),
        ]
        email = 'user@domain.com'
        for package in packages:
            self.set_package_subscribers(package.name, [email])

        self.run_command()

        self.assertEqual(2, PackageName.objects.count())
        # All subscriptions created?
        for package in packages:
            package = PackageName.objects.get(pk=package.pk)
            self.assert_subscribed_to_package(package, [email])


class ImportTagsTests(TestCase):

    """
    Tests for the management command for importing the dump of user tags
    (subscription-specific keywords and user default keywords).
    """

    def setUp(self):
        self.tags = {}

    def add_subscription_specific_tags(self, email, package, tags):
        self.tags[email + '#' + package] = tags

    def add_default_tags(self, email, tags):
        self.tags[email] = tags

    def get_input(self):
        return '\n'.join(
            '{}: {}'.format(
                email,
                ','.join(tags))
            for email, tags in self.tags.items()
        )

    def run_command(self):
        command = ImportOldTagsCommand()
        command.stdin = io.StringIO(self.get_input())
        command.handle()

    def assert_keyword_sets_equal(self, set1, set2):
        self.assertEqual(len(set1), len(set2))
        for k in set1:
            self.assertIn(k, set2)

    def test_default_keywords_imported(self):
        email = 'user@domain.com'
        keywords = Keyword.objects.all()[:4]
        tags = [k.name for k in keywords]
        self.add_default_tags(email, tags)

        self.run_command()

        self.assertEqual(1, EmailSettings.objects.count())
        settings = EmailSettings.objects.all()[0]
        self.assert_keyword_sets_equal(
            keywords,
            settings.default_keywords.all())

    def test_subscription_specific_keywords_imported(self):
        email = 'user@domain.com'
        package = 'pkg'
        sub = Subscription.objects.create_for(package, email)
        keywords = Keyword.objects.all()[:4]
        tags = [k.name for k in keywords]
        self.add_subscription_specific_tags(email, package, tags)

        self.run_command()

        # The subscription is updated to contain a new set of keywords
        sub = Subscription.objects.get(pk=sub.pk)
        self.assert_keyword_sets_equal(
            keywords,
            sub.keywords.all())

    def test_both_types_imported(self):
        email = 'user@domain.com'
        package = 'pkg'
        sub = Subscription.objects.create_for(package, email)
        keywords = Keyword.objects.all()[:4]
        tags = [k.name for k in keywords]
        self.add_subscription_specific_tags(email, package, tags)
        default_keywords = Keyword.objects.all()[4:]
        self.add_default_tags(email, [k.name for k in default_keywords])

        self.run_command()

        # The subscription is updated to contain a new set of keywords
        sub = Subscription.objects.get(pk=sub.pk)
        self.assert_keyword_sets_equal(
            keywords,
            sub.keywords.all())
        # The user's default keywords are also updated
        settings = EmailSettings.objects.all()[0]
        self.assert_keyword_sets_equal(
            default_keywords,
            settings.default_keywords.all())

    def test_legacy_mapping_import(self):
        keyword = Keyword.objects.get(name='archive')
        old_tag = 'katie-other'
        email = 'user@domain.com'
        self.add_default_tags(email, [old_tag])

        self.run_command()

        settings = EmailSettings.objects.all()[0]
        self.assert_keyword_sets_equal(
            [keyword],
            settings.default_keywords.all())


@mock.patch(
    'distro_tracker.vendor.debian.sso_auth.'
    'DebianSsoUserBackend.get_user_details')
@override_settings(MIDDLEWARE=[
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'distro_tracker.vendor.debian.sso_auth.DebianSsoUserMiddleware',
], AUTHENTICATION_BACKENDS=(
    'distro_tracker.vendor.debian.sso_auth.DebianSsoUserBackend',
    'django_email_accounts.auth.UserEmailBackend',
))
class DebianSsoLoginTests(TestCase):
    """
    Tests relating to logging in via the sso.debian.org
    via DACS (which sets REMOTE_USER).
    """

    DD_USER = 'DEBIANORG::DEBIAN:user'
    DD_EMAIL = 'user@debian.org'
    ALIOTH_USER = 'DEBIANORG::DEBIAN:foo-guest@users.alioth.debian.org'
    ALIOTH_EMAIL = 'foo-guest@users.alioth.debian.org'
    INVALID_USER = 'FEDERATION::JURISDICTION:user'

    def get_page(self, remote_user=None):
        self.client.get(reverse('dtracker-index'), **{
            'REMOTE_USER': remote_user,
        })

    def assert_user_logged_in(self, user):
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def assert_no_user_logged_in(self):
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_first_log_in(self, get_user_details):
        """
        Tests that when a Debian Developer first logs in an account is
        automatically created.
        """
        first_name, last_name = 'First', 'Last'
        get_user_details.return_value = {
            'first_name': first_name,
            'last_name': last_name,
        }

        self.get_page(self.DD_USER)

        self.assertEqual(1, User.objects.count())
        user = User.objects.all()[0]
        self.assertEqual(first_name, user.first_name)
        self.assertEqual(last_name, user.last_name)
        self.assertEqual(self.DD_EMAIL, user.main_email)
        self.assert_user_logged_in(user)

    def test_first_log_in_via_alioth(self, get_user_details):
        """
        Tests that when an Alioth user first logs in an account is not
        automatically created.
        """
        get_user_details.return_value = None

        self.get_page(self.ALIOTH_USER)

        self.assertEqual(0, User.objects.count())
        self.assert_no_user_logged_in()

    def test_no_log_in_invalid_username(self, get_user_details):
        """
        Tests that no user is logged in when the federation or jurisdiction are
        incorrect.
        """
        self.get_page(self.INVALID_USER)

        self.assertEqual(0, User.objects.count())
        self.assert_no_user_logged_in()

    def test_first_log_in_preexisting(self, get_user_details):
        """
        Tests that an already existing user is logged in without modifying the
        account fields.
        """
        old_name = 'Oldname'
        user = User.objects.create_user(
            main_email=self.DD_EMAIL,
            first_name=old_name)

        self.get_page(self.DD_USER)

        self.assertEqual(1, User.objects.count())
        user = User.objects.all()[0]
        self.assertEqual(old_name, user.first_name)
        self.assert_user_logged_in(user)

    def test_first_log_in_preexisting_associated(self, get_user_details):
        """
        Tests that an already existing user that has an associated
        (not main_email) @debian.org address is logged in without modifying the
        account fields.
        """
        old_name = 'Oldname'
        user = User.objects.create_user(
            main_email='user@domain.com',
            first_name=old_name)
        # The @debian.org address is an associated email
        user.emails.create(email=self.DD_EMAIL)

        self.get_page(self.DD_USER)

        self.assertEqual(1, User.objects.count())
        user = User.objects.all()[0]
        self.assertEqual(old_name, user.first_name)
        self.assert_user_logged_in(user)

    def test_first_log_in_preexisting_useremail(self, get_user_details):
        UserEmail.objects.create(email=self.DD_EMAIL)

        self.get_page(self.DD_USER)

        self.assertEqual(1, User.objects.count())
        self.assertTrue(get_user_details.called)

    def test_user_logged_out(self, get_user_details):
        """
        Tests that Distro Tracker logs out the user after the SSO headers are
        invalid.
        """
        user = User.objects.create_user(
            main_email=self.DD_EMAIL)
        self.client.login(remote_user=user.main_email)
        # Sanity check: the user is logged in
        self.assert_user_logged_in(user)

        self.get_page()

        self.assert_no_user_logged_in()

    def test_user_logged_out_no_header(self, get_user_details):
        """
        Tests that Distro Tracker logs out the user if the SSO headers are gone.
        """
        user = User.objects.create_user(
            main_email=self.DD_EMAIL)
        self.client.login(remote_user=user.main_email)
        # Sanity check: the user is logged in
        self.assert_user_logged_in(user)

        self.client.get('/')

        self.assert_no_user_logged_in()

    def test_authenticate_returns_correct_class(self, get_user_details):
        auth_backend = DebianSsoUserBackend()
        user = auth_backend.authenticate(remote_user=self.DD_EMAIL)
        self.assertIsInstance(user, User)  # from distro_tracker.accounts.models

    def test_authenticate_returns_correct_class_with_existing_user(
            self, get_user_details):
        User.objects.create_user(main_email=self.DD_EMAIL)
        auth_backend = DebianSsoUserBackend()
        user = auth_backend.authenticate(remote_user=self.DD_EMAIL)
        self.assertIsInstance(user, User)  # from distro_tracker.accounts.models


class DebianSsoLoginWithSSLClientCertificateTests(DebianSsoLoginTests):
    """
    Tests relating to logging in with a SSL client certificate
    generated on sso.debian.org.
    See https://wiki.debian.org/DebianSingleSignOn
    """

    DD_USER = 'user@debian.org'
    DD_EMAIL = 'user@debian.org'
    ALIOTH_USER = 'foo-guest@users.alioth.debian.org'
    ALIOTH_EMAIL = 'foo-guest@users.alioth.debian.org'

    def get_page(self, remote_user=None):
        self.client.get(reverse('dtracker-index'), **{
            'SSL_CLIENT_S_DN_CN': remote_user,
        })

    def test_no_log_in_invalid_username(self):
        # This test does not make sense here, there are no invalid
        # values
        pass


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateDebianDuckTaskTest(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateDebianDuckTask`
    task.
    """

    def setUp(self):
        self.dummy_package = SourcePackageName.objects.create(
            name='dummy-package')
        self.other_package = SourcePackageName.objects.create(
            name='other-package')
        self.duck_data = """
        dummy-package
        dummy-package2
        """

    def run_task(self):
        """
        Runs the Duck status update task.
        """
        task = UpdateDebianDuckTask()
        task.execute()

    def test_action_item_when_in_list(self, mock_requests):
        """
        Tests that an ActionItem is created for a package reported by duck.
        """
        set_mock_response(mock_requests, text=self.duck_data)

        self.run_task()
        self.assertEqual(1, self.dummy_package.action_items.count())

    def test_no_action_item_when_not_in_list(self, mock_requests):
        """
        Tests that no ActionItem is created for a package not reported by duck.
        """
        set_mock_response(mock_requests, text=self.duck_data)

        self.run_task()
        self.assertEqual(0, self.other_package.action_items.count())

    def test_action_item_is_dropped_when_duck_reports_nothing_again(
            self,
            mock_requests):
        """
        Tests that ActionItems are dropped when a package was previousy reported
        but is now not reported anymore.
        """
        set_mock_response(mock_requests, text=self.duck_data)
        self.run_task()
        self.assertEqual(1, self.dummy_package.action_items.count())

        duck_data = """
        yet-another-package
        """
        set_mock_response(mock_requests, text=duck_data)

        self.run_task()
        self.assertEqual(0, self.dummy_package.action_items.count())


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateDebciStatusTaskTest(TestCase):

    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.UpdateDebciStatusTask`
    task.
    """

    def setUp(self):
        self.dummy_package = SourcePackageName.objects.create(
            name='dummy-package')
        self.other_package = SourcePackageName.objects.create(
            name='other-package')
        self.json_data = """[
            {
                "run_id": "20140705_145427",
                "package": "dummy-package",
                "version": "1.0-1",
                "date": "2014-07-05 14:55:57",
                "status": "pass",
                "blame": [ ],
                "previous_status": "pass",
                "duration_seconds": "91",
                "duration_human": "0h 1m 31s",
                "message": "All tests passed"
            },
            {
                "run_id": "20140705_212616",
                "package": "other-package",
                "version": "2.0-2",
                "date": "2014-07-05 21:34:22",
                "status": "fail",
                "blame": [ ],
                "previous_status": "fail",
                "duration_seconds": "488",
                "duration_human": "0h 8m 8s",
                "message": "Tests failed"
            },
            {
                "run_id": "20140705_143518",
                "package": "another-package",
                "version": "3.0-3",
                "date": "2014-07-05 17:33:08",
                "status": "fail",
                "blame": [ ],
                "previous_status": "fail",
                "duration_seconds": "222",
                "duration_human": "0h 3m 42s",
                "message": "Tests failed"
            }]
        """

    def run_task(self):
        """
        Runs the debci status update task.
        """
        task = UpdateDebciStatusTask()
        task.execute()

    def test_no_action_item_for_passing_test(self, mock_requests):
        """
        Tests that an ActionItem isn't created for a passing debci status.
        """
        set_mock_response(mock_requests, text=self.json_data)

        self.run_task()

        self.assertEqual(0, self.dummy_package.action_items.count())

    def test_no_action_item_for_unknown_package(self, mock_requests):
        """
        Tests that an ActionItem isn't created for an unknown package.
        """
        json_data = """
            [{
                "run_id": "20140705_143518",
                "package": "another-package",
                "version": "3.0-3",
                "date": "2014-07-05 17:33:08",
                "status": "fail",
                "blame": [ ],
                "previous_status": "fail",
                "duration_seconds": "222",
                "duration_human": "0h 3m 42s",
                "message": "Tests failed"
            }]
        """
        set_mock_response(mock_requests, text=json_data)

        self.run_task()

        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_for_failing_test(self, mock_requests):
        """
        Tests that a proper ActionItem is created for a failing test
        on a known package.
        """
        set_mock_response(mock_requests, text=self.json_data)

        self.run_task()

        # Check that the ActionItem contains the correct contents.
        self.assertEqual(self.other_package.action_items.count(), 1)
        action_item = self.other_package.action_items.all()[0]
        url = "https://ci.debian.net/packages/o/other-package/"
        log = "https://ci.debian.net/data/packages/unstable/amd64/o/" + \
            "other-package/latest-autopkgtest/log.gz"
        self.assertIn(url, action_item.short_description)
        self.assertIn(log, action_item.short_description)
        self.assertEqual(action_item.extra_data['duration'], "0h 8m 8s")
        self.assertEqual(action_item.extra_data['previous_status'], "fail")
        self.assertEqual(action_item.extra_data['date'], "2014-07-05 21:34:22")
        self.assertEqual(action_item.extra_data['url'], url)
        self.assertEqual(action_item.extra_data['log'], log)

    def test_action_item_is_dropped_when_test_passes_again(
            self,
            mock_requests):
        """
        Tests that ActionItems are dropped when the test passes again.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()
        json_data = """
            [{
                "run_id": "20140705_143519",
                "package": "other-package",
                "version": "3.0-4",
                "date": "2014-07-07 17:33:08",
                "status": "pass",
                "blame": [ ],
                "previous_status": "fail",
                "duration_seconds": "222",
                "duration_human": "0h 3m 42s",
                "message": "Tests passed"
            }]
        """
        set_mock_response(mock_requests, text=json_data)

        self.run_task()

        self.assertEqual(self.other_package.action_items.count(), 0)

    def test_action_item_is_dropped_when_info_vanishes(self, mock_requests):
        """
        Tests that ActionItems are dropped when the debci report doesn't
        mention the package.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()
        set_mock_response(mock_requests, text="[]")

        self.run_task()

        self.assertEqual(ActionItem.objects.count(), 0)

    def test_lib_package_link(self, mock_requests):
        """
        Tests that links to lib packages' log files are correct.
        """
        libpackage = SourcePackageName.objects.create(name='libpackage')
        json_data = """
            [{
                "run_id": "20140705_143518",
                "package": "libpackage",
                "version": "3.0-3",
                "date": "2014-07-05 17:33:08",
                "status": "fail",
                "blame": [ ],
                "previous_status": "fail",
                "duration_seconds": "222",
                "duration_human": "0h 3m 42s",
                "message": "Tests failed"
            }]
        """
        set_mock_response(mock_requests, text=json_data)

        self.run_task()

        action_item = libpackage.action_items.all()[0]
        action_item_log_url = action_item.extra_data['log']
        log_url = "https://ci.debian.net/data/packages/unstable/amd64/libp/" + \
            "libpackage/latest-autopkgtest/log.gz"

        self.assertEqual(action_item_log_url, log_url)


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateAutoRemovalsStatsTaskTest(TestCase):

    """
    Tests for the :class:`distro_tracker.vendor.debian.tracker_tasks
    .UpdateAutoRemovalsStatsTask` task.
    """

    def setUp(self):
        self.dummy_package = SourcePackageName.objects.create(
            name='dummy-package')
        self.other_package = SourcePackageName.objects.create(
            name='other-package')
        self.autoremovals_data = """
        dummy-package:
            bugs:
            - '12345'
            removal_date: 2014-08-24 10:20:00
        dummy-package2:
            bugs:
            - '123456'
            removal_date: 2014-08-25 12:00:00
        """

    def run_task(self):
        """
        Runs the autoremovals status update task.
        """
        task = UpdateAutoRemovalsStatsTask()
        task.execute()

    def test_action_item_when_in_list(self, mock_requests):
        """
        Tests that an ActionItem is created for a package reported by
        autoremovals.
        """
        set_mock_response(mock_requests, text=self.autoremovals_data)

        self.run_task()
        self.assertEqual(1, self.dummy_package.action_items.count())

    def test_no_action_item_when_not_in_list(self, mock_requests):
        """
        Tests that no ActionItem is created for a package not reported by
        autoremovals.
        """
        set_mock_response(mock_requests, text=self.autoremovals_data)

        self.run_task()
        self.assertEqual(0, self.other_package.action_items.count())

    def test_action_item_is_dropped_when_autoremovals_reports_nothing_again(
            self, mock_requests):
        """
        Tests that ActionItems are dropped when a package was previousy
        reported but is now not reported anymore.
        """
        set_mock_response(mock_requests, text=self.autoremovals_data)
        self.run_task()
        self.assertEqual(1, self.dummy_package.action_items.count())

        autoremovals_data = """
        dummy-package3:
            bugs:
            - '1234567'
            removal_date: 2014-08-22 12:21:00
        """
        set_mock_response(mock_requests, text=autoremovals_data)

        self.run_task()
        self.assertEqual(0, self.dummy_package.action_items.count())


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdatePackageScreenshotsTaskTest(TestCase):
    """
    Tests for the:class:`distro_tracker.vendor.debian.tracker_tasks.
    UpdatePackageScreenshotsTask` task.
    """
    def setUp(self):
        self.dummy_package = SourcePackageName.objects.create(name='dummy')
        self.json_data = """{
            "packages": [{
                "maintainer": "Jane Doe",
                "name": "dummy",
                "url": "https://screenshots.debian.net/package/dummy",
                "section": "universe/games",
                "maintainer_email": "jane@example.com",
                "homepage": "http://example.com/packages/dummy",
                "description": "a game that you can play"
            }]}
        """
        PackageData.objects.create(
            package=self.dummy_package,
            key='general',
            value={
                'name': 'dummy',
                'maintainer': {
                    'email': 'jane@example.com',
                }
            }
        )
        self.other_json_data = """{
            "packages": [{
                "maintainer": "John Doe",
                "name": "other",
                "url": "https://screenshots.debian.net/package/other",
                "section": "universe/games",
                "maintainer_email": "john@example.com",
                "homepage": "http://example.com/packages/other",
                "description": "yet another game that you can play"
            }]}
        """

    def run_task(self):
        """
        Runs the screenshots status update task.
        """
        task = UpdatePackageScreenshotsTask()
        task.execute()

    def test_packagedata_item_for_without_screenshot(self, mock_requests):
        """
        Tests that packages without screenshots don't claim to have them.
        """
        set_mock_response(mock_requests, text=self.json_data)
        other_package = SourcePackageName.objects.create(name='other-package')

        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            other_package.data.get(key='screenshots')

    def test_no_packagedata_for_unknown_package(self, mock_requests):
        """
        Tests that UpdatePackageScreenshotsTask doesn't fail with an unknown
        package.
        """
        data = """{
            "packages": [{
                "maintainer": "John Doe",
                "name": "other",
                "url": "https://screenshots.debian.net/package/other",
                "section": "universe/games",
                "maintainer_email": "john@example.com",
                "homepage": "http://example.com/packages/other",
                "description": "yet another game that you can play"
            }]}
        """
        set_mock_response(mock_requests, text=data)

        self.run_task()

        count = PackageData.objects.filter(key='screenshots').count()
        self.assertEqual(0, count)

    def test_packagedata_for_package_with_screenshots(self, mock_requests):
        """
        Tests that PackageData for a package with a screenshot is
        correct.
        """
        set_mock_response(mock_requests, text=self.json_data)

        self.run_task()

        info = self.dummy_package.data.get(key='screenshots')

        self.assertEqual(info.value['screenshots'], 'true')

    def test_packagedata_is_dropped_when_no_more_screenshot(self,
                                                            mock_requests):
        """
        Tests that PackageData is dropped if screenshot goes away.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()

        set_mock_response(mock_requests, text=self.other_json_data)
        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            self.dummy_package.data.get(key='screenshots')

    def test_other_packagedata_keys_not_dropped(self, mock_requests):
        """
        Ensure that other PackageData keys are not dropped when
        deleting the screenshot key.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()

        set_mock_response(mock_requests, text=self.other_json_data)
        self.run_task()

        info = self.dummy_package.data.get(key='general')

        self.assertEqual(info.value['name'], 'dummy')


@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateBuildReproducibilityTaskTest(TestCase):
    """
    Tests for the:class:`distro_tracker.vendor.debian.tracker_tasks.
    UpdateBuildReproducibilityTask` task.
    """
    def setUp(self):
        self.json_data = """
            [{
                "package": "dummy",
                "version": "1.2-3",
                "status": "unreproducible",
                "suite": "sid"
            }]
        """
        self.other_json_data = """
        [{
            "package": "other",
            "version": "1.2-3",
            "status": "unreproducible",
            "suite": "sid"
        }]
        """
        self.dummy_package = SourcePackageName.objects.create(name='dummy')
        PackageData.objects.create(
            package=self.dummy_package,
            key='general',
            value={
                'name': 'dummy',
                'maintainer': {
                    'email': 'jane@example.com',
                }
            }
        )

    def run_task(self):
        """
        Runs the build reproducibility status update task.
        """
        task = UpdateBuildReproducibilityTask()
        task.execute()

    def test_packagedata_without_reproducibility(self, mock_requests):
        """
        Tests that packages without reproducibility info don't claim to have
        them.
        """
        set_mock_response(mock_requests, text=self.json_data)
        other_package = SourcePackageName.objects.create(name='other-package')

        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            other_package.data.get(key='reproducibility')

    def test_no_packagedata_for_unknown_package(self, mock_requests):
        """
        Tests that BuildReproducibilityTask doesn't fail with an unknown
        package.
        """
        set_mock_response(mock_requests, text=self.other_json_data)

        self.run_task()

        count = PackageData.objects.filter(key='reproducibility').count()
        self.assertEqual(0, count)

    def test_packagedata_with_reproducibility(self, mock_requests):
        """
        Tests that PackageData for a package with reproducibility info
        is correct.
        """
        set_mock_response(mock_requests, text=self.json_data)

        self.run_task()

        info = self.dummy_package.data.get(key='reproducibility')

        self.assertEqual(info.value['reproducibility'], 'unreproducible')
        action_items = self.dummy_package.action_items
        self.assertEqual(action_items.count(), 1)
        self.assertEqual(action_items.first().item_type.type_name,
                         UpdateBuildReproducibilityTask.ACTION_ITEM_TYPE_NAME)

    def test_packagedata_is_dropped_when_data_is_gone(self, mock_requests):
        """
        Tests that PackageData is dropped if reproducibility info
        goes away.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()

        set_mock_response(mock_requests, text=self.other_json_data)
        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            self.dummy_package.data.get(key='reproducibility')
        self.assertEqual(self.dummy_package.action_items.count(), 0)

    def test_action_item_is_dropped_when_status_is_reproducible(self,
                                                                mock_requests):
        """
        Ensure the action item is dropped when status switches from
        unreproducible to reproducible.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()
        self.assertEqual(self.dummy_package.action_items.count(), 1)
        json_data = """
            [{
                "package": "dummy",
                "version": "1.2-3",
                "status": "reproducible",
                "suite": "sid"
            }]
        """
        set_mock_response(mock_requests, text=json_data)
        self.run_task()

        self.assertEqual(self.dummy_package.action_items.count(), 0)

    def test_other_packagedata_keys_not_dropped(self, mock_requests):
        """
        Ensure that other PackageData keys are not dropped when
        deleting the reproducibility key.
        """
        set_mock_response(mock_requests, text=self.json_data)
        self.run_task()

        set_mock_response(mock_requests, text=self.other_json_data)
        self.run_task()

        info = self.dummy_package.data.get(key='general')

        self.assertEqual(info.value['name'], 'dummy')


class UpdateVcsWatchTaskTest(TestCase):
    """
    Tests for the:class:`distro_tracker.vendor.debian.tracker_tasks.
    UpdateVcsWatchTask` task.
    """
    def setUp(self):
        # Patch get_resource_content() to return our vcswatch_data
        def compute_json(*args, **kwargs):
            return json.dumps(self.vcswatch_data).encode('utf-8')
        patcher = mock.patch(
            'distro_tracker.core.utils.http.get_resource_content')
        get_resource_content = patcher.start()
        get_resource_content.side_effect = compute_json
        self.addCleanup(patcher.stop)

        # Setup default data
        self.vcswatch_data = [
            {
                "commits": 46,
                "package": "dummy",
                "error": None,
                "status": "COMMITS",
                "changelog_version": "0.12.1-2",
                "package_version": "0.12.1-2",
                "changelog_distribution": "unstable",
            },
        ]

        self.dummy_package = SourcePackageName.objects.create(name='dummy')
        self.other_dummy_package = SourcePackageName.objects.create(
            name='other-dummy')

        # Useful for last test
        PackageData.objects.create(
            package=self.dummy_package,
            key='general',
            value={
                'name': 'dummy',
                'maintainer': {
                    'email': 'jane@example.com',
                }
            }
        )

    def run_task(self):
        task = UpdateVcsWatchTask()
        task.execute()

    def check_package_info(self, key, theoretical_package_info={}):
        info = self.dummy_package.data.get(key=key)
        self.assertDictEqual(info.value, theoretical_package_info)

    def test_packagedata_without_vcswatch(self):
        """
        Tests that packages without vcswatch info don't claim to have them.
        """
        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            self.other_dummy_package.data.get(key='vcs_extra_links')

    def test_no_packagedata_for_unknown_package(self):
        """
        Tests that the task doesn't fail with an unknown package.
        """
        self.vcswatch_data[0]['package'] = 'unknown'

        self.run_task()

        count = PackageData.objects.filter(key='vcs_extra_links').count()
        self.assertEqual(0, count)

    def test_packagedata_with_vcswatch(self):
        """
        Tests that PackageData for a package with vcswatch info
        is correct.
        """
        self.run_task()

        theoretical_extra_data = {
            'name': 'dummy',
            'status': 'COMMITS',
            'error': None,
            'url': (
                'https://qa.debian.org/cgi-bin/vcswatch?package=dummy'
            ),
            'commits': 46,
        }
        theoretical_vcs_extra_links_package_info = {
            "checksum": 'bb2db81183608a0f02853a0d1087cfef',
            "QA": 'https://qa.debian.org/cgi-bin/vcswatch?package=dummy',
        }
        theoretical_vcswatch_package_info = {
            "checksum": '6ca379c61ff0c003bb8c9379a9d401d0',
            "changelog_version": "0.12.1-2",
            "package_version": "0.12.1-2",
            "changelog_distribution": "unstable",
        }

        self.check_package_info(
            'vcs_extra_links', theoretical_vcs_extra_links_package_info)
        self.check_package_info('vcswatch', theoretical_vcswatch_package_info)

        action_items = self.dummy_package.action_items
        self.assertEqual(action_items.count(), 1)
        action_item = action_items.first()
        self.assertEqual(action_item.item_type.type_name,
                         UpdateVcsWatchTask.ACTION_ITEM_TYPE_NAME)
        self.assertDictEqual(action_item.extra_data, theoretical_extra_data)

    def test_packagedata_is_updated_if_needed(self):
        """
        Tests that PackageData is updated if vcswatch_url changes.
        """
        self.run_task()

        # Alters the info so that it's not destroyed when we
        # remove vcswatch data.
        dummy_pi = self.dummy_package.data.get(key='vcs_extra_links')
        dummy_pi.value['test_useless_entry'] = True

        # No need to change the checksum as we test a case where it's
        # re-computed.
        dummy_pi.save()

        # Now it should be good.
        initial_data = self.vcswatch_data
        self.vcswatch_data = []

        self.run_task()

        # Normally, no watch_url in the package
        dummy_pi = self.dummy_package.data.get(key='vcs_extra_links')
        self.assertEqual('QA' not in dummy_pi.value, True)

        # This part will test another part of the code.
        self.vcswatch_data = initial_data
        self.vcswatch_data[0]['changelog_version'] = "0.12.1-3"
        self.run_task()

        dummy_pi = self.dummy_package.data.get(key='vcs_extra_links').value
        self.assertTrue('QA' in dummy_pi)
        self.assertEqual(dummy_pi['QA'],
                         'https://qa.debian.org/cgi-bin/vcswatch?package=dummy')

        dummy_pi = self.dummy_package.data.get(key='vcswatch').value
        self.assertEqual(dummy_pi['package_version'], '0.12.1-2')
        self.assertEqual(dummy_pi['changelog_version'], '0.12.1-3')
        self.assertEqual(dummy_pi['changelog_distribution'], 'unstable')

    def test_packagedata_is_dropped_when_data_is_gone(self):
        """
        Tests that PackageData is dropped if vcswatch info
        goes away.
        """
        self.run_task()

        self.vcswatch_data = []
        self.run_task()

        with self.assertRaises(PackageData.DoesNotExist):
            self.dummy_package.data.get(key='vcs_extra_links')

    def test_action_item_is_dropped_when_status_is_ok(self):
        """
        Ensure the action item is dropped when status switches from
        not "OK" to "OK".
        """
        self.run_task()
        self.assertEqual(self.dummy_package.action_items.count(), 1)

        self.vcswatch_data[0]['status'] = 'OK'
        self.run_task()

        self.assertEqual(self.dummy_package.action_items.count(), 0)

    def test_action_item_is_updated_when_extra_data_changes(self):
        """
        Ensures that the action item is updated when extra_data changes.
        """
        self.run_task()

        ai = self.dummy_package.action_items.first()
        self.assertEqual(ai.extra_data['commits'], 46)

        self.vcswatch_data[0]['commits'] += 1
        self.run_task()

        ai = self.dummy_package.action_items.first()
        self.assertEqual(ai.extra_data['commits'], 47)

    def test_other_packagedata_keys_not_dropped(self):
        """
        Ensure that other PackageData keys are not dropped when
        deleting the vcs key.
        """
        self.run_task()

        self.vcswatch_data = []
        self.run_task()

        info = self.dummy_package.data.get(key='general')

        self.assertEqual(info.value['name'], 'dummy')


class AdditionalPrefetchRelatedLookupsTest(SimpleTestCase):
    def test_additional_prefetch_related_lookups(self):
        """
        Tests the addition of prefetch related lookups for table
        """
        data = additional_prefetch_related_lookups()
        self.assertTrue(type(data) is list)
        self.assertEqual(len(data), 2)


class GetVcsDataTest(TestCase):
    def test_get_vcs_data(self):
        """
        Tests getting extra vcs data provided for VcsTableField
        """
        package = SourcePackageName.objects.create(name='dummy-package')
        item_type = ActionItemType.objects.get_or_create(
            type_name='vcswatch-warnings-and-errors')[0]
        ActionItem.objects.create(
            package=package,
            item_type=item_type,
            short_description="Short description...",
        )
        package.vcswatch_data = []
        context = get_vcs_data(package)
        self.assertIsNotNone(context['action_item'])
        self.assertIsNotNone(context['action_item']['url'])
        self.assertIsNotNone(context['action_item']['severity']['name'])
        self.assertIsNotNone(context['action_item']['severity']['label_type'])

    def test_get_vcs_data_for_package_without_vcs_watch_warning(self):
        """
        Tests getting extra vcs data for a package that does not have
        VCS Watch warnings
        """
        package = SourcePackageName.objects.create(name='dummy-package')
        package.vcswatch_data = []
        context = get_vcs_data(package)
        self.assertDictEqual(context, {})


@override_settings(
    DISTRO_TRACKER_VENDOR_RULES='distro_tracker.vendor.debian.rules')
class BugStatsTableFieldTests(TestCase):
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        stats = {}
        stats['bugs'] = [
            {'bug_count': 3, 'merged_count': 0, 'category_name': 'rc'},
            {'bug_count': 7, 'merged_count': 7, 'category_name': 'normal'},
            {'bug_count': 1, 'merged_count': 1, 'category_name': 'wishlist'},
        ]
        PackageBugStats.objects.create(
            package=self.package, stats=stats['bugs'])
        self.field = BugStatsTableField()

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context(self.package)
        self.assertTrue(context['all'])
        self.assertEqual(context['all'], 11)
        self.assertEqual(len(context['bugs']), 4)
        for bug in context['bugs']:
            self.assertIn('bug_count', bug)
            self.assertIn('category_name', bug)
            self.assertIsNotNone(bug['url'])
        self.assertIsNotNone(context['bts_url'])
        self.assertEqual(context['rc_bugs'], 3)

    def test_text_color_based_on_available_bugs_categories(self):
        """
        Tests text color of the field based on available bugs categories
        """
        bug_stats = self.package.bug_stats
        context = self.field.context(self.package)
        self.assertEqual(context['text_color'], 'text-danger')

        bug_stats.stats = [
            {'bug_count': 0, 'merged_count': 0, 'category_name': 'rc'},
            {'bug_count': 7, 'merged_count': 7, 'category_name': 'normal'},
        ]
        bug_stats.save()
        context = self.field.context(self.package)
        self.assertEqual(context['text_color'], 'text-warning')

        bug_stats.stats = [
            {'bug_count': 1, 'merged_count': 1, 'category_name': 'patch'},
        ]
        bug_stats.save()
        context = self.field.context(self.package)
        self.assertEqual(context['text_color'], 'text-info')

        bug_stats.stats = [
            {'bug_count': 1, 'merged_count': 1, 'category_name': 'wishlist'},
        ]
        bug_stats.save()
        context = self.field.context(self.package)
        self.assertEqual(context['text_color'], 'text-default')

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(
            self.field.template_name,
            'debian/package-table-fields/bugs.html')

    def test_get_bug_stat_data_for_package_without_bug(self):
        """
        Tests getting extra bug stats data for a package that does not have
        bug stats records
        """
        package = SourcePackageName.objects.create(name='another-package')
        context = self.field.context(package)
        self.assertIsNotNone(context['bts_url'])
        self.assertNotIn('rc_bugs', context)
        self.assertEqual(len(context['bugs']), 1)


class UpstreamTableFieldTests(TestCase):
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.data = PackageData(package=self.package, key='general')
        self.data.value = {
            'upstream': {
                'url': 'https://www.dummy.org/dummy-2.17.1.tar.xz',
                'version': '2.17.1'
            }
        }
        self.data.save()
        self.package.general_data = self.package.data.filter(
            key='general')
        self.field = UpstreamTableField()

    def test_field_context(self):
        """
        Tests field contex content
        """
        context = self.field.context(self.package)
        self.assertTrue(context['version'])
        self.assertTrue(context['url'])

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Upstream')
        self.assertEqual(
            self.field.template_name,
            'debian/package-table-fields/upstream.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)


class TagPackagesWithRcBugsTest(TestCase):
    """
    Tests for the
    :class:`distro_tracker.vendor.debian.tracker_tasks.TagPackagesWithRcBugs`
    task.
    """

    def setUp(self):
        self.tag = 'tag:rc-bugs'
        self.package_with_rc_bug = PackageName.objects.create(
            name='package-with-rc-bug')
        self.package_without_rc_bug = PackageName.objects.create(
            name='package-without-rc-bug')
        self.package_without_bug = PackageName.objects.create(
            name='package-without-bug')
        PackageBugStats.objects.create(
            package=self.package_with_rc_bug,
            stats=[
                {'bug_count': 1, 'merged_count': 0, 'category_name': 'rc'},
                {'bug_count': 2, 'merged_count': 0, 'category_name': 'normal'},
            ]
        )
        PackageBugStats.objects.create(
            package=self.package_without_rc_bug,
            stats=[
                {'bug_count': 0, 'merged_count': 0, 'category_name': 'rc'},
                {'bug_count': 2, 'merged_count': 0, 'category_name': 'normal'},
            ]
        )

    def test_update_rc_bugs_tag_task(self):
        """
        Tests the default behavior of TagPackagesWithRcBugs task
        """
        # ensure that there is no PackageData entries with 'tag:bugs' key
        self.assertEqual(PackageData.objects.filter(key=self.tag).count(), 0)

        # execute the task
        task = TagPackagesWithRcBugs()
        task.execute()

        # check that the task worked as expected
        self.assertEqual(PackageData.objects.filter(key=self.tag).count(), 1)
        self.assertIsNotNone(
            PackageData.objects.get(
                key=self.tag, package=self.package_with_rc_bug)
        )
        with self.assertRaises(ObjectDoesNotExist):
            PackageData.objects.get(
                key=self.tag, package=self.package_without_rc_bug)
        with self.assertRaises(ObjectDoesNotExist):
            PackageData.objects.get(
                key=self.tag, package=self.package_without_bug)

    def test_task_remove_tag_from_package_without_no_more_rc_bugs(self):
        """
        Tests the removing of 'tag:rc-bugs' data from packages that no longer
        have RC bugs.
        """
        # add bug tag previously
        PackageData.objects.create(
            key=self.tag, package=self.package_with_rc_bug)
        # remove bugs from package
        self.package_with_rc_bug.bug_stats.delete()

        # check tag in package with rc bug
        self.assertIsNotNone(
            PackageData.objects.get(
                key=self.tag, package=self.package_with_rc_bug)
        )

        # execute the task
        task = TagPackagesWithRcBugs()
        task.execute()

        # check that the task removed the tag
        self.assertEqual(PackageData.objects.filter(key=self.tag).count(), 0)
        with self.assertRaises(ObjectDoesNotExist):
            PackageData.objects.get(
                key=self.tag, package=self.package_with_rc_bug)

    def test_task_keep_tag_for_package_that_still_have_rc_bugs(self):
        """
        Tests the maintenance of 'tag:rc-bugs' key for packages that still
        have RC bugs.
        """
        # add rc-bugs tag previously
        PackageData.objects.create(
            key=self.tag, package=self.package_with_rc_bug)

        # check tag in package with RC bug
        self.assertIsNotNone(
            PackageData.objects.get(
                key=self.tag, package=self.package_with_rc_bug)
        )

        # execute the task
        task = TagPackagesWithRcBugs()
        task.execute()

        # check that the task kept the tag
        self.assertEqual(PackageData.objects.filter(key=self.tag).count(), 1)
        self.assertIsNotNone(
            PackageData.objects.get(
                key=self.tag, package=self.package_with_rc_bug)
        )
