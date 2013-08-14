# -*- coding: utf-8 -*-

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
Tests for the PTS core panels.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.core.urlresolvers import reverse
from BeautifulSoup import BeautifulSoup as soup
from pts.core.models import SourcePackageName
from pts.core.models import SourcePackage
from pts.core.panels import VersionedLinks


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
        url = reverse('pts-package-page', kwargs={
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
