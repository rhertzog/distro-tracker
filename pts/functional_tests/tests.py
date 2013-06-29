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
Functional tests for the Package Tracking System.
"""
from __future__ import unicode_literals
from django.test import LiveServerTestCase
from django.core.urlresolvers import reverse
from pts.core.models import SourcePackage

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException


class PackagePageTest(LiveServerTestCase):
    def setUp(self):
        self.browser = webdriver.Firefox()
        self.browser.implicitly_wait(3)

        self.package = SourcePackage.objects.create(name='dummy-package')

    def tearDown(self):
        self.browser.quit()

    def get_absolute_url(self, relative):
        """
        Helper method which builds an absolute URL where the live_server_url is
        the root.
        """
        return self.live_server_url + relative

    def test_access_source_package_page_by_url(self):
        """
        Tests that users can get to a package's page by going straight to its
        URL.
        """
        # The user tries to visit a package's page.
        self.browser.get(
            self.get_absolute_url(reverse('pts-package-page', kwargs={
                'package_name': self.package.name,
            }))
        )

        # He has reached the package's page which is indicated in the tab's
        # title.
        self.assertIn(self.package.name, self.browser.title)
        # It is displayed in the content, as well.
        package_name_element = self.browser.find_element_by_tag_name('h1')
        self.assertEqual(package_name_element.text, self.package.name)

        # The user sees a footer with general information about PTS
        try:
            self.browser.find_element_by_id('footer')
        except NoSuchElementException:
            self.fail("Footer not found")

        # There is a header with a form with a text box where the user can
        # type in the name of a package to get to its page.
        try:
            search_form = self.browser.find_element_by_id('package-search-form')
        except NoSuchElementException:
            self.fail("Form not found")
