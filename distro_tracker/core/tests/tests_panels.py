# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core panels.
"""
from __future__ import unicode_literals
from django.core.urlresolvers import reverse
from bs4 import BeautifulSoup as soup

from distro_tracker.test import TestCase
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import PseudoPackageName
from distro_tracker.core.models import PackageName
from distro_tracker.core.models import SourcePackage
from distro_tracker.core.models import Repository, SourcePackageRepositoryEntry
from distro_tracker.core.panels import VersionedLinks, DeadPackageWarningPanel


class VersionedLinksPanelTests(TestCase):
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')
        self.repo1 = Repository.objects.create(name='repo1', shorthand='repo1')
        self.repo1.source_entries.create(source_package=self.package)
        self.panel = VersionedLinks(self.package_name, None)
        # Clear any registered link providers to let the test control which
        # ones exist.
        VersionedLinks.LinkProvider.plugins = []

    def add_link_provider(self, icons):
        type(str('TestProvider'),
             (VersionedLinks.LinkProvider,),
             {'icons': icons})

    def get_package_page_response(self):
        url = reverse('dtracker-package-page', kwargs={
            'package_name': self.package.name,
        })
        return self.client.get(url)

    def panel_is_in_response(self, response):
        """
        Checks whether the versioned links panel is found in the rendered HTML
        response.
        """
        html = soup(response.content)
        panels = html.findAll("div", {'class': 'panel-heading'})
        for panel in panels:
            if 'versioned links' in str(panel):
                return True
        return False

    def test_panel_not_displayed(self):
        """
        Tests that the panel is not displayed in the package page when there
        are no items to be displayed.
        """
        response = self.get_package_page_response()

        self.assertFalse(self.panel_is_in_response(response))

    def test_panel_displayed(self):
        """
        Tests that the panel is displayed when there is at least one icon
        provider.
        """
        self.add_link_provider(['icon1'])

        response = self.get_package_page_response()

        self.assertTrue(self.panel_is_in_response(response))

    def test_context_returns_something(self):
        """Tests that the context returns data for the source package
        version we have."""
        self.add_link_provider(['icon1'])

        context = self.panel.context

        self.assertEqual(len(context), 1)

    def test_context_does_not_contain_hidden_versions(self):
        """Tests that the context doesn't return data for source
        package versions that are only in hidden repositories."""
        self.repo1.flags.create(name='hidden', value=True)
        self.add_link_provider(['icon1'])

        context = self.panel.context

        self.assertEqual(len(context), 0)

    def test_context_returns_version_in_hidden_and_non_hidden_repo(self):
        """Tests that the context doesn't return data for source
        package versions that are only in hidden repositories."""
        self.repo1.flags.create(name='hidden', value=True)
        self.repo2 = Repository.objects.create(name='repo2', shorthand='repo2')
        self.repo2.source_entries.create(source_package=self.package)
        self.repo2.flags.create(name='hidden', value=False)
        self.add_link_provider(['icon1'])

        context = self.panel.context

        self.assertEqual(len(context), 1)


class GeneralInfoLinkPanelItemsTests(TestCase):
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.homepage = 'http://www.dummyhomepage.net'
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0',
            homepage=self.homepage)

    def get_package_page_response(self):
        url = reverse('dtracker-package-page', kwargs={
            'package_name': self.package.name,
        })
        return self.client.get(url)

    def get_general_info_link_panel(self, response):
        """
        Checks whether the links panel is found in the rendered HTML
        response.
        """
        html = soup(response.content)
        panels = html.findAll("div", {'class': 'panel-heading'})
        for panel in panels:
            if 'links' in str(panel) and 'versioned links' not in str(panel):
                return panel
        return False

    def homepage_is_in_linkspanel(self, response):
        """
        Checks whether the homepage link is displayed
        """
        html = soup(response.content)
        links = html.findAll("a")
        for l in links:
            if self.homepage in l['href']:
                return True
        return False

    def test_panel_displayed(self):
        """
        Tests that the panel is displayed when package has a homepage
        and that the homepage is displayed in that panel
        """
        response = self.get_package_page_response()
        self.assertTrue(self.get_general_info_link_panel(response))
        self.assertTrue(self.homepage_is_in_linkspanel(response))


class DeadPackageWarningPanelTests(TestCase):
    def setUp(self):
        self.pkgname = SourcePackageName.objects.create(name='dummy-package')
        self.srcpkg = SourcePackage.objects.create(
            source_package_name=self.pkgname, version='1.0.0')
        self.default_repo = \
            Repository.objects.create(name='default', shorthand='default',
                                      default=True)
        self.repo1 = Repository.objects.create(name='repo1', shorthand='repo1')
        self.panel = DeadPackageWarningPanel(self.pkgname, None)

    def test_has_content_pkg_in_no_repository(self):
        """The package is not in any repository. We should display the
        warning."""
        self.assertTrue(self.panel.has_content)

    def test_has_content_pkg_not_in_devel_repos(self):
        """The package is not in a development repository. We should display
        the warning."""
        SourcePackageRepositoryEntry.objects.create(
            source_package=self.srcpkg, repository=self.repo1)
        self.assertTrue(self.panel.has_content)

    def test_has_content_pkg_in_devel_repos(self):
        """The package is in at least one of the development repositories.
        We should not display the warning."""
        SourcePackageRepositoryEntry.objects.create(
            source_package=self.srcpkg, repository=self.default_repo)
        self.assertFalse(self.panel.has_content)

    def test_has_content_for_pseudo_package(self):
        """A pseudo-package is never obsolete. No warning displayed."""
        pkgname = PseudoPackageName.objects.create(name='pseudo')
        panel = DeadPackageWarningPanel(pkgname, None)

        self.assertFalse(panel.has_content)

    def test_has_content_for_old_packages(self):
        """Old package only exists as PackageName. We should display the
        warning in this case."""
        pkgname = PackageName.objects.create(name='oldpkg')
        panel = DeadPackageWarningPanel(pkgname, None)

        self.assertTrue(panel.has_content)

    def test_context_pkg_disappeared_completely(self):
        """The package is not in any repository. The context exports this."""
        self.assertTrue(self.panel.context['disappeared'])

    def test_context_pkg_disappeared_from_devel_repository(self):
        """The package is in a few repositories. The context exports this."""
        SourcePackageRepositoryEntry.objects.create(
            source_package=self.srcpkg, repository=self.repo1)
        self.assertFalse(self.panel.context['disappeared'])
