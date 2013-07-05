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
from pts.core.models import SourcePackage, BinaryPackage
from pts.core.panels import BasePanel

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from django.utils.six.moves import mock


class SeleniumTestCase(LiveServerTestCase):
    """
    A class which includes some common functionality for all tests which use
    Selenium.
    """
    def setUp(self):
        self.browser = webdriver.Firefox()
        self.browser.implicitly_wait(3)

    def tearDown(self):
        self.browser.close()

    def get_page(self, relative):
        """
        Helper method which points the browser to the absolute URL based on the
        given relative URL and the server's live_server_url.
        """
        self.browser.get(self.absolute_url(relative))

    def absolute_url(self, relative):
        """
        Helper method which builds an absolute URL where the live_server_url is
        the root.
        """
        return self.live_server_url + relative

    def input_to_element(self, id, text):
        """
        Helper method which sends the text to the element with the given ID.
        """
        element = self.browser.find_element_by_id(id)
        element.send_keys(text)

    def click_link(self, link_text):
        """
        Helper method which clicks on the link with the given text.
        """
        element = self.browser.find_element_by_link_text(link_text)
        element.click()

    def send_enter(self, id):
        """
        Helper method which sends the enter key to the element with the given
        ID.
        """
        element = self.browser.find_element_by_id(id)
        element.send_keys(Keys.ENTER)

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

    def set_mock_http_response(self, mock_requests, text, status_code=200):
        mock_response = mock_requests.models.Response()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_requests.get.return_value = mock_response


def create_test_panel(panel_position):
    """
    Helper test decorator which creates a TestPanel before running the test and
    unregisters it when it completes, making sure all tests are ran in
    isolation.
    """
    def decorator(func):
        def wrap(self):
            class TestPanel(BasePanel):
                html_output = "Hello, world"
                position = panel_position
            try:
                ret = func(self)
            finally:
                TestPanel.unregister_plugin()
            return ret

        return wrap

    return decorator


class PackagePageTest(SeleniumTestCase):
    def setUp(self):
        super(PackagePageTest, self).setUp()
        self.package = SourcePackage.objects.create(name='dummy-package')
        SourcePackage.objects.create(name='second-package')
        self.binary_package = BinaryPackage.objects.create(
            name='binary-package',
            source_package=self.package)

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

    def test_access_source_package_page_by_url(self):
        """
        Tests that users can get to a package's page by going straight to its
        URL.
        """
        # The user tries to visit a package's page.
        self.get_page(self.get_package_url(self.package.name))

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
            self.absolute_url(self.get_package_url('second-package')))

        # The user would like to see the source package page for a binary
        # package that he types in the search form.
        self.send_text_to_package_search_form('binary-package')
        self.assertEqual(
            self.browser.current_url,
            self.absolute_url(self.get_package_url(self.package.name)))

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
        self.get_page('/')

        # He sees it is the index page of the PTS
        self.assertIn('Package Tracking System', self.browser.title)

        # There is a form which he can use for access to pacakges.
        self.assert_element_with_id_in_page('package-search-form')

        # He types in a name of a known source package...
        self.send_text_to_package_search_form(self.package.name)
        # ...and expects to see the package page open.
        self.assertEqual(
            self.browser.current_url,
            self.absolute_url(self.package.get_absolute_url()))

        # The user goes back to the index...
        self.browser.back()
        # ...and tries using the form to access a package page, but the package
        # does not exist.
        self.send_text_to_package_search_form('no-exist')
        self.assert_in_page_body('Package no-exist does not exist')

    @create_test_panel('left')
    def test_include_panel_left(self):
        """
        Tests whether a package page includes a panel in the left side column.
        """
        self.get_page(self.get_package_url(self.package.name))

        self.assert_element_with_id_in_page('pts-package-left')
        column = self.browser.find_element_by_id('pts-package-left')
        self.assertIn("Hello, world", column.text)

    @create_test_panel('center')
    def test_include_panel_center(self):
        """
        Tests whether a package page includes a panel in the center column.
        """
        self.get_page(self.get_package_url(self.package.name))

        self.assert_element_with_id_in_page('pts-package-center')
        column = self.browser.find_element_by_id('pts-package-center')
        self.assertIn("Hello, world", column.text)

    @create_test_panel('right')
    def test_include_panel_right(self):
        """
        Tests whether a package page includes a panel in the right side column.
        """
        self.get_page(self.get_package_url(self.package.name))

        self.assert_element_with_id_in_page('pts-package-right')
        column = self.browser.find_element_by_id('pts-package-right')
        self.assertIn("Hello, world", column.text)


from django.contrib.auth.models import User


class RepositoryAdminTest(SeleniumTestCase):
    def setUp(self):
        super(RepositoryAdminTest, self).setUp()
        # Create a superuser which will be used for the tests
        User.objects.create_superuser(
            username='admin',
            password='admin',
            email='admin@localhost'
        )

    def login_to_admin(self, username='admin', password='admin'):
        """
        Helper method which logs the user with the given credentials to the
        admin console.
        """
        self.get_page('/admin/')
        self.input_to_element('id_username', username)
        self.input_to_element('id_password', password)
        self.send_enter('id_password')

    @mock.patch('pts.core.retrieve_data.requests')
    def test_repository_add(self, mock_requests):
        """
        Tests that an admin user is able to add a new repository.
        """
        # The user first logs in to the admin panel.
        self.login_to_admin()

        # He expects to be able to successfully access it with his credentials.
        self.assertIn('Site administration', self.browser.title)

        # He now wants to go to the repositories management page.
        # The necessary link can be found in the page.
        try:
            self.browser.find_element_by_link_text("Repositories")
        except NoSuchElementException:
            self.fail("Link for repositories management not found in the admin")

        # Clicking on it opens a new page to manage repositories.
        self.click_link("Repositories")
        self.assertIn(
            'Repositories',
            self.browser.find_element_by_class_name('breadcrumbs').text
        )

        # He now wants to create a new repository...
        self.click_link("Add repository")
        self.assert_in_page_body("Add repository")
        try:
            save_button = self.browser.find_element_by_css_selector(
                'input.default')
        except NoSuchElementException:
            self.fail("Could not find the save button")

        # The user tries clicking the save button immediately
        save_button.click()
        # But this causes an error since there are some required fields...
        self.assert_in_page_body('Please correct the errors below')

        # He enters a name and shorthand for the repository
        self.input_to_element('id_name', 'stable')
        self.input_to_element('id_shorthand', 'stable')
        # He wants to create the repository by using a sources.list entry
        self.input_to_element(
            'id_sources_list_entry',
            'deb http://ftp.ba.debian.org/debian stable'
        )
        ## Make sure that no actual HTTP requests are sent out
        self.set_mock_http_response(mock_requests,
            'Suite: stable\n'
            'Codename: wheezy\n'
            'Architectures: amd64 armel armhf i386 ia64 kfreebsd-amd64'
            ' kfreebsd-i386 mips mipsel powerpc s390 s390x sparc\n'
            'Components: main contrib non-free\n'
            'Version: 7.1\n'
            'Description: Debian 7.1 Released 15 June 2013\n'
        )
        # The user decides to save by hitting the enter key
        self.send_enter('id_sources_list_entry')
        # The user sees a message telling him the repository has been added.
        self.assert_in_page_body("added successfully")
        # He also sees the information of the newly added repository
        self.assert_in_page_body('Codename')
        self.assert_in_page_body('wheezy')
        self.assert_in_page_body('Components')
        self.assert_in_page_body('main contrib non-free')

        # The user now wants to add another repository
        self.click_link("Add repository")
        # This time, he wants to enter all the necessary data manually.
        self.input_to_element('id_name', 'testing')
        self.input_to_element('id_shorthand', 'testing')
        self.input_to_element('id_uri', 'http://ftp.ba.debian.org/debian')
        self.input_to_element('id_suite', 'testing')
        self.input_to_element('id_codename', 'jessie')
        self.input_to_element('id_components', '["main", "non-free"]')
        self.input_to_element('id_architectures', '["amd64"]')
        # Finally the user clicks the save button
        self.browser.find_element_by_css_selector('input.default').click()

        # He sees that the new repository has also been created.
        self.assert_in_page_body("added successfully")
        # He also sees the information of the newly added repository
        self.assert_in_page_body('jessie')
        self.assert_in_page_body('main non-free')
