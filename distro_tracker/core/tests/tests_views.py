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
Tests for the Distro Tracker core views.
"""
from __future__ import unicode_literals
from distro_tracker.test import TestCase
from django.test.utils import override_settings
from distro_tracker.core.models import PackageName, BinaryPackageName
from distro_tracker.core.models import SourcePackageName, SourcePackage
from distro_tracker.core.models import PseudoPackageName
from distro_tracker.core.models import ActionItem, ActionItemType
import json

from django.core.urlresolvers import reverse
from django.conf import settings

import os


class PackageViewTest(TestCase):
    """
    Tests for the package view.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.binary_package = BinaryPackageName.objects.create(
            name='binary-package')
        self.pseudo_package = PseudoPackageName.objects.create(name='pseudo-pkg')
        src_pkg = SourcePackage.objects.create(
            source_package_name=self.package, version='1.0.0')
        src_pkg.binary_packages = [self.binary_package]
        src_pkg.save()

    def get_package_url(self, package_name):
        """
        Helper method which returns the URL for the package with the given name
        """
        return reverse('dtracker-package-page', kwargs={
            'package_name': package_name
        })

    def test_source_package_page(self):
        """
        Tests that when visiting the package page for an existing package, a
        response based on the correct template is returned.
        """
        url = self.get_package_url(self.package.name)
        response = self.client.get(url)

        self.assertTemplateUsed(response, 'core/package.html')

    def test_source_package_page_with_plus_it_its_name(self):
        """
        Tests that we can visit the page for a package which contains
        a plus its name (non-regression test for bug #754497).
        """
        pkg = SourcePackageName.objects.create(name='libti++')
        url = self.get_package_url(pkg.name)

        response = self.client.get(url)

        self.assertTemplateUsed(response, 'core/package.html')

    def test_binary_package_redirects_to_source(self):
        """
        Tests that when visited a binary package URL, the user is redirected
        to the corresponding source package page.
        """
        url = self.get_package_url(self.binary_package.name)
        response = self.client.get(url)

        self.assertRedirects(response, self.get_package_url(self.package.name))

    def test_pseudo_package_page(self):
        """
        Tests that when visiting a page for a pseudo package the correct
        template is used.
        """
        url = self.get_package_url(self.pseudo_package.name)
        response = self.client.get(url)

        self.assertTemplateUsed(response, 'core/package.html')

    def test_non_existent_package(self):
        """
        Tests that a 404 is returned when the given package does not exist.
        """
        url = self.get_package_url('no-exist')
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_subscriptions_only_package(self):
        """
        Tests that a 404 is returned when the given package is a "subscriptions
        only" package.
        """
        package_name = 'sub-only-pkg'
        # Make sure the package actually exists.
        PackageName.objects.create(name=package_name)

        url = self.get_package_url(package_name)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_legacy_url_redirects(self):
        """
        Tests that the old PTS style package URLs are correctly redirected.
        """
        url_template = '/{hash}/{package}.html'

        # Redirects for packages that do not start with "lib"
        url = url_template.format(hash=self.package.name[0],
                                  package=self.package.name)
        response = self.client.get(url)
        self.assertRedirects(response, self.get_package_url(self.package.name),
                             status_code=301)

        # No redirect when the hash does not match the package
        url = url_template.format(hash='q', package=self.package.name)
        self.assertEqual(self.client.get(url).status_code, 404)

        # Redirect when the package name starts with "lib"
        lib_package = 'libpackage'
        SourcePackageName.objects.create(name=lib_package)
        url = url_template.format(hash='libp', package=lib_package)
        self.assertRedirects(self.client.get(url),
                             self.get_package_url(lib_package),
                             status_code=301)

    def test_catchall_redirect(self):
        """
        Tests that requests made to the root domain are redirected to a package
        page when possible and when it does not conflict with another URL rule.
        """
        url = '/{}'.format(self.package.name)
        response = self.client.get(url, follow=True)
        # User redirected to the existing package page
        self.assertRedirects(response, self.get_package_url(self.package.name))

        # Trailing slash
        url = '/{}/'.format(self.package.name)
        response = self.client.get(url, follow=True)
        # User redirected to the existing package page
        self.assertRedirects(response, self.get_package_url(self.package.name))

        # Admin URLs have precedence to the catch all package redirect
        url = reverse('admin:index')
        response = self.client.get(url, follow=True)
        # No redirects - went directly to the admin
        self.assertEqual(0, len(response.redirect_chain))

        # Non existing package
        url = '/{}'.format('no-exist')
        response = self.client.get(url, follow=True)
        self.assertEqual(404, response.status_code)


class PackageSearchViewTest(TestCase):
    def setUp(self):
        self.pseudo_package = PseudoPackageName.objects.create(name='pseudo-package')
        self.source_package = SourcePackageName.objects.create(name='dummy-package')
        self.binary_package = BinaryPackageName.objects.create(
            name='binary-package')
        src_pkg = SourcePackage.objects.create(
            source_package_name=self.source_package, version='1.0.0')
        src_pkg.binary_packages = [self.binary_package]
        src_pkg.save()

    def test_package_search_source_package(self):
        """
        Tests the package search when the given package is an existing source
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.source_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_search_pseudo_package(self):
        """
        Tests the package search when the given package is an existing pseudo
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.pseudo_package.name
        })

        self.assertRedirects(response, self.pseudo_package.get_absolute_url())

    def test_package_search_binary_package(self):
        """
        Tests the package search when the given package is an existing binary
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.binary_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_does_not_exist(self):
        """
        Tests the package search when the given package does not exist.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': 'no-exist'
        })

        self.assertTemplateUsed('core/package_search.html')
        self.assertIn('package_name', response.context)
        self.assertEqual(response.context['package_name'], 'no-exist')


class OpenSearchDescriptionTest(TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.OpenSearchDescription`.
    """

    def test_html_head_contains_opensearch_link_entry(self):
        osd_uri = reverse('dtracker-opensearch-description')
        header = '<link type="application/opensearchdescription+xml" title="'
        header += "%s Package Tracker Search" % \
            settings.DISTRO_TRACKER_VENDOR_NAME
        header += '" rel="search" href="' + osd_uri + '"/>'

        response = self.client.get(reverse('dtracker-index'))

        self.assertContains(response, header, html=True)

    def test_opensearch_description_url(self):
        response = self.client.get(reverse('dtracker-opensearch-description'))
        self.assertTemplateUsed(response, 'core/opensearch-description.xml')

    def test_opensearch_description_contains_relevant_urls(self):
        response = self.client.get(reverse('dtracker-opensearch-description'))
        self.assertContains(response, reverse('dtracker-favicon'))
        self.assertContains(response, reverse('dtracker-package-search') +
                            '?package_name={searchTerms}')


class IndexViewTest(TestCase):
    def test_index(self):
        """
        Tests that the correct template is rendered when the index page is
        accessed.
        """
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'core/index.html')


class PackageAutocompleteViewTest(TestCase):
    def setUp(self):
        SourcePackageName.objects.create(name='dummy-package')
        SourcePackageName.objects.create(name='d-package')
        SourcePackageName.objects.create(name='package')
        PseudoPackageName.objects.create(name='pseudo-package')
        PseudoPackageName.objects.create(name='zzz')
        BinaryPackageName.objects.create(name='package-dev')
        BinaryPackageName.objects.create(name='libpackage')
        PackageName.objects.create(name='ppp')

    def test_source_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for source
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'source',
            'q': 'd',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'd')
        self.assertEqual(len(response[1]), 2)
        self.assertIn('dummy-package', response[1])
        self.assertIn('d-package', response[1])

        # No packages given when there are no matching source packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'source',
            'q': 'z',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'z')
        self.assertEqual(len(response[1]), 0)

    def test_binary_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for binary
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'binary',
            'q': 'p',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 1)
        self.assertIn('package-dev', response[1])

        # No packages given when there are no matching binary packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'binary',
            'q': 'z',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'z')
        self.assertEqual(len(response[1]), 0)

    def test_pseudo_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for pseudo
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'pseudo',
            'q': 'p',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 1)
        self.assertIn('pseudo-package', response[1])

        # No packages given when there are no matching pseudo packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'pseudo',
            'q': '-',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], '-')
        self.assertEqual(len(response[1]), 0)

    def test_all_packages_autocomplete(self):
        """
        Tests the autocomplete functionality when the client does not specify
        the type of package.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'q': 'p',
        })

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 3)
        self.assertIn('package', response[1])
        self.assertIn('package-dev', response[1])
        self.assertIn('pseudo-package', response[1])

        # No packages given when there are no matching packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'q': '-',
        })
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], '-')
        self.assertEqual(len(response[1]), 0)

    def test_no_query_given(self):
        """
        Tests the autocomplete when there is no query parameter given.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'), {
            'package_type': 'source',
        })

        self.assertEqual(response.status_code, 404)


@override_settings(TEMPLATE_DIRS=(os.path.join(
    os.path.dirname(__file__),
    'tests-data/tests-templates'),))
class ActionItemJsonViewTest(TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.ActionItemJsonView`.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.action_type = ActionItemType.objects.create(
            type_name='test',
            full_description_template='action-item-test.html')

    def test_item_exists(self):
        """
        Tests that the JSON response correctly returns an item's content.
        """
        expected_short_description = 'Short description of item'
        action_item = ActionItem.objects.create(
            package=self.package,
            item_type=self.action_type,
            short_description=expected_short_description)
        response = self.client.get(reverse('dtracker-api-action-item', kwargs={
            'item_pk': action_item.pk,
        }))

        response = json.loads(response.content.decode('utf-8'))
        # Correct short description
        self.assertEqual(
            expected_short_description,
            response['short_description'])
        # Package name included
        self.assertEqual(
            'dummy-package',
            response['package']['name'])
        # Full description from rendered template
        self.assertIn("Item's PK is", response['full_description'])
        # Template name NOT included
        self.assertNotIn('full_description_template', response)

    def test_item_does_not_exist(self):
        """
        Tests that the JSON ActionItem view returns 404 when the item does not
        exist.
        """
        does_not_exist = 100
        # Sanity check - the PK actually does not exist
        self.assertEqual(0, ActionItem.objects.filter(pk=does_not_exist).count())
        response = self.client.get(reverse('dtracker-api-action-item', kwargs={
            'item_pk': does_not_exist,
        }))

        self.assertEqual(response.status_code, 404)
