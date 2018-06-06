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
Tests for the Distro Tracker core package tables.
"""
from bs4 import BeautifulSoup as soup

from distro_tracker.core.models import (
    PackageData,
    PackageBugStats,
    Team,
    SourcePackageName
)
from django_email_accounts.models import User
from distro_tracker.core.package_tables import (
    GeneralTeamPackageTable,
    GeneralInformationTableField,
    VcsTableField,
    ArchiveTableField,
    BugStatsTableField
)
from distro_tracker.test import TemplateTestsMixin, TestCase


def create_source_package_with_data(name):
    package = SourcePackageName.objects.create(
        name=name)
    create_package_data(package)
    return package


def create_package_data(package):
    PackageData.objects.create(
        package=package,
        key='general',
        value={
            'name': package.name,
            'maintainer': {
                'email': 'jane@example.com',
            },
            'vcs': {
                'type': 'git',
                'url': 'https://salsa.debian.org/qa/distro-tracker.git',
                'browser': 'https://salsa.debian.org/qa/distro-tracker',
            },
            'component': 'main',
            'version': '2.0.5-1',
        }
    )

    PackageData.objects.create(
        package=package,
        key='versions',
        value={
            'version_list': [],
            'default_pool_url': 'http://deb.debian.org/debian/pool/main/'
        }
    )


def create_package_bug_stats(package):
    bug_stats = [
        {'bug_count': 3, 'merged_count': 3, 'category_name': 'rc'},
        {'bug_count': 7, 'merged_count': 7, 'category_name': 'normal'},
        {'bug_count': 1, 'merged_count': 1, 'category_name': 'wishlist'},
    ]
    return PackageBugStats.objects.create(package=package, stats=bug_stats)


class GeneralInformationTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        self.package.general_data = self.package.data.filter(key='general')
        self.package.binaries_data = self.package.data.filter(key='binaries')
        self.field = GeneralInformationTableField(self.package)

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context
        self.assertEqual(context['url'], self.package.get_absolute_url)
        self.assertTrue(context['vcs'])
        self.assertIn('type', context['vcs'])
        self.assertIn('url', context['vcs'])
        self.assertIn('browser', context['vcs'])
        self.assertTrue(context['maintainer'])
        self.assertIn('email', context['maintainer'])
        self.assertEqual(context['binaries'], [])

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Package')
        self.assertTrue(self.field.has_content)
        self.assertIsNone(self.field.html_output)
        self.assertEqual(
            self.field.template_name, 'core/package-table-fields/general.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 2)


class VcsTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        self.package.general_vcs_data = self.package.data.all()
        self.field = VcsTableField(self.package)

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context
        self.assertTrue(context['vcs'])
        self.assertIn('type', context['vcs'])
        self.assertIn('url', context['vcs'])
        self.assertIn('browser', context['vcs'])
        self.assertIn('full_name', context['vcs'])

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'VCS')
        self.assertTrue(self.field.has_content)
        self.assertIsNone(self.field.html_output)
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/vcs.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)


class ArchiveTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        self.package.general_archive_data = self.package.data.filter(
            key='general')
        self.package.versions = self.package.data.filter(
            key='versions')
        self.field = ArchiveTableField(self.package)

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context
        self.assertTrue(context['version'])
        self.assertTrue(context['default_pool_url'])

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Archive')
        self.assertTrue(self.field.has_content)
        self.assertIsNone(self.field.html_output)
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/archive.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 2)


class BugStatsTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        create_package_bug_stats(self.package)
        self.field = BugStatsTableField(self.package)

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context
        self.assertTrue(context['all'])
        self.assertEqual(context['all'], 11)
        self.assertEqual(len(context['bugs']), 3)
        for bug in context['bugs']:
            self.assertIn('bug_count', bug)
            self.assertIn('category_name', bug)

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Bugs')
        self.assertTrue(self.field.has_content)
        self.assertIsNone(self.field.html_output)
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/bugs.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)


class GeneralTeamPackageTableTests(TestCase, TemplateTestsMixin):
    def setUp(self):
        self.tested_instance = GeneralTeamPackageTable(None)
        self.user = User.objects.create_user(
            main_email='paul@example.com', password='pw4paul')
        self.team = Team.objects.create_with_slug(
            owner=self.user, name="Team name", public=True)
        self.package = create_source_package_with_data('dummy-package')
        create_package_bug_stats(self.package)
        self.team.packages.add(self.package)

    def get_team_page_response(self):
        return self.client.get(self.team.get_absolute_url())

    def get_general_package_table(self, response):
        """
        Checks whether the general package table is found in
        the rendered HTML response.
        """
        html = soup(response.content, 'html.parser')
        tables = html.findAll("div", {'class': 'package-table'})
        for table in tables:
            if 'All team packages' in str(table):
                return table
        return False

    def assert_number_of_queries(self, table):
        number_of_queries = 1 + sum(
            len(f.prefetch_related_lookups) for f in table.table_fields)

        with self.assertNumQueries(number_of_queries):
            for row in table.rows:
                for field in row:
                    field.context

    def test_table_displayed(self):
        """
        Tests that the table is displayed in team's page and that
        its title is displayed
        """
        response = self.get_team_page_response()
        table = self.get_general_package_table(response)
        self.assertTrue(table)
        self.assertIn(self.tested_instance.title, str(table))

    def test_table_has_the_appropriate_column_names(self):
        """
        Tests that table has the appropriate column names
        """
        response = self.get_team_page_response()
        table = self.get_general_package_table(response)

        column_names = table.findAll('th')
        self.assertEqual(
            len(column_names), len(self.tested_instance.column_names))
        for name in column_names:
            self.assertIn(name.get_text(), self.tested_instance.column_names)

    def test_table_package_content(self):
        """
        Tests that table presents the team's package data
        """
        response = self.get_team_page_response()
        table = self.get_general_package_table(response)

        rows = table.tbody.findAll('tr')
        self.assertEqual(len(rows), self.team.packages.count())
        ordered_packages = self.team.packages.order_by(
            'name').prefetch_related('data', 'bug_stats')

        for index, row in enumerate(rows):
            self.assertIn(ordered_packages[index].name, str(row))
            general = ordered_packages[index].data.get(key='general').value
            self.assertIn(general['vcs']['browser'], str(row))
            self.assertIn('bugs-field', str(row))

    def test_table_popover_components(self):
        """
        Tests that the table displays component popover
        """
        response = self.get_team_page_response()
        table = self.get_general_package_table(response)

        component = table.find('span', attrs={'id': 'general-field'})
        self.assertIn('popover-hover', component['class'])

    def test_number_of_queries(self):
        """
        Tests that the table is being constructed with a fixed number of
        queries regardless of the number of packages
        """
        table = GeneralTeamPackageTable(self.team)
        self.assert_number_of_queries(table)

        new_package = create_source_package_with_data('another-dummy-package')
        create_package_bug_stats(new_package)
        self.team.packages.add(new_package)
        self.assert_number_of_queries(table)
