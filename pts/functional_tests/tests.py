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
from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from pts.core.models import SourcePackage, BinaryPackage

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys


class PackagePageTest(LiveServerTestCase):
    def setUp(self):
        self.browser = webdriver.Firefox()
        self.browser.implicitly_wait(3)

        self.package = SourcePackage.objects.create(name='dummy-package')
        SourcePackage.objects.create(name='second-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package',
            source_package=self.package)

    def tearDown(self):
        self.browser.quit()

    def get_absolute_url(self, relative):
        """
        Helper method which builds an absolute URL where the live_server_url is
        the root.
        """
        return self.live_server_url + relative

    def get_package_url(self, package_name):
        """
        Helper method returning the URL of the package with the given name.
        """
        return reverse('pts-package-page', kwargs={
            'package_name': package_name,
        })

    def send_text_to_package_search_form(self, text):
        """
        Helper function to send text input to the package search form.
        """
        search_form = self.browser.find_element_by_id('package-search-form')
        text_box = search_form.find_element_by_name('package_name')
        # Make sure any old text is removed.
        text_box.clear()
        text_box.send_keys(text)
        text_box.send_keys(Keys.ENTER)

    def assert_in_page_body(self, text):
        body = self.browser.find_element_by_tag_name('body')
        self.assertIn(text, body.text)

    def assert_element_with_id_in_page(self, element_id, custom_message=None):
        """
        Helper method which asserts that the element with the given ID can be
        found in the current browser page.
        """
        if custom_message is None:
            custom_message = element_id + " not found in the page."
        try:
            self.browser.find_element_by_id(element_id)
        except NoSuchElementException:
            self.fail(custom_message)

    def test_access_source_package_page_by_url(self):
        """
        Tests that users can get to a package's page by going straight to its
        URL.
        """
        # The user tries to visit a package's page.
        self.browser.get(
            self.get_absolute_url(self.get_package_url(self.package.name)))

        # He has reached the package's page which is indicated in the tab's
        # title.
        self.assertIn(self.package.name, self.browser.title)
        # It is displayed in the content, as well.
        package_name_element = self.browser.find_element_by_tag_name('h1')
        self.assertEqual(package_name_element.text, self.package.name)

        # The user sees a footer with general information about PTS
        self.assert_element_with_id_in_page('footer')

        # There is a header with a form with a text box where the user can
        # type in the name of a package to get to its page.
        self.assert_element_with_id_in_page('package-search-form',
                                            "Form not found")

        # So, the uer types the name of another source package...
        self.send_text_to_package_search_form('second-package')

        # This causes the new pacakge's page to open.
        self.assertEqual(
            self.browser.current_url,
            self.get_absolute_url(self.get_package_url('second-package')))

        # The user would like to see the source package page for a binary
        # package that he types in the search form.
        self.send_text_to_package_search_form('binary-package')
        self.assertEqual(
            self.browser.current_url,
            self.get_absolute_url(self.get_package_url(self.package.name)))

        # However, when the user tries a package name which does not exist,
        # he expects to see a page informing him of this
        self.send_text_to_package_search_form('no-exist')
        self.assert_in_page_body('Package no-exist does not exist')

    def test_access_package_page_from_index(self):
        """
        Tests that the user can access a package page starting from the index
        and using the provided form.
        """
        # The user opens the start page of the PTS
        self.browser.get(self.get_absolute_url('/'))

        # He sees it is the index page of the PTS
        self.assertIn('Package Tracking System', self.browser.title)

        # There is a form which he can use for access to pacakges.
        self.assert_element_with_id_in_page('package-search-form')

        # He types in a name of a known source package...
        self.send_text_to_package_search_form(self.package.name)
        # ...and expects to see the package page open.
        self.assertEqual(
            self.browser.current_url,
            self.get_absolute_url(self.package.get_absolute_url()))

        # The user goes back to the index...
        self.browser.back()
        # ...and tries using the form to access a package page, but the package
        # does not exist.
        self.send_text_to_package_search_form('no-exist')
        self.assert_in_page_body('Package no-exist does not exist')

    @override_settings(PTS_PACKAGE_PAGE_PANELS={
        'left': ('pts.functional_tests.tests.TestPanel',)
    })
    def test_include_panel_left(self):
        """
        Tests whether a package page includes a panel in the left side column.
        """
        self.browser.get(
            self.get_absolute_url(self.get_package_url(self.package.name)))

        self.assert_element_with_id_in_page('pts-package-left')
        column = self.browser.find_element_by_id('pts-package-left')
        self.assertIn("Hello, world", column.text)

    @override_settings(PTS_PACKAGE_PAGE_PANELS={
        'center': ('pts.functional_tests.tests.TestPanel',)
    })
    def test_include_panel_center(self):
        """
        Tests whether a package page includes a panel in the center column.
        """
        self.browser.get(
            self.get_absolute_url(self.get_package_url(self.package.name)))

        self.assert_element_with_id_in_page('pts-package-center')
        column = self.browser.find_element_by_id('pts-package-center')
        self.assertIn("Hello, world", column.text)

    @override_settings(PTS_PACKAGE_PAGE_PANELS={
        'right': ('pts.functional_tests.tests.TestPanel',)
    })
    def test_include_panel_right(self):
        """
        Tests whether a package page includes a panel in the right side column.
        """
        self.browser.get(
            self.get_absolute_url(self.get_package_url(self.package.name)))

        self.assert_element_with_id_in_page('pts-package-right')
        column = self.browser.find_element_by_id('pts-package-right')
        self.assertIn("Hello, world", column.text)


from pts.core.panels import BasePanel
class TestPanel(BasePanel):
    html_output = "Hello, world"
