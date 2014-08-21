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
from distro_tracker.test import TestCase
from django.core.urlresolvers import reverse
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import SourcePackage
from distro_tracker.core.panels import VersionedLinks
from distro_tracker.core.utils.soup import soup


class VersionedLinksPanelTests(TestCase):
    def setUp(self):
        self.package_name = SourcePackageName.objects.create(
            name='dummy-package')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='1.0.0')
        # Clear any registered link providers to let the test control which
        # ones exist.
        VersionedLinks.LinkProvider.plugins = []

    def add_link_provider(self, icons):
        type(str('TestProvider'), (VersionedLinks.LinkProvider,), {'icons': icons})

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
            if 'links' in str(panel) and not 'versioned links' in str(panel):
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
