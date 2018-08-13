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
from unittest.mock import patch, mock_open

from bs4 import BeautifulSoup as soup
from django.template import Context

from distro_tracker.core.models import (
    PackageData,
    PackageBugStats,
    Team,
    SourcePackageName
)
from django_email_accounts.models import User
from distro_tracker.core.package_tables import (
    create_table,
    BasePackageTable,
    GeneralTeamPackageTable,
    GeneralInformationTableField,
    VcsTableField,
    ArchiveTableField,
    BugStatsTableField
)
from distro_tracker.test import TemplateTestsMixin, TestCase


class TestPackageTable(BasePackageTable):
    table_fields = (GeneralInformationTableField, ArchiveTableField)


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
        self.field = GeneralInformationTableField()

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context(self.package)
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
        self.assertEqual(
            self.field.template_name, 'core/package-table-fields/general.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 2)


class VcsTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        self.package.general_data = self.package.data.all()
        self.field = VcsTableField()

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context(self.package)
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
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/vcs.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)


class ArchiveTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        self.package.general_data = self.package.data.filter(
            key='general')
        self.package.versions = self.package.data.filter(
            key='versions')
        self.field = ArchiveTableField()

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context(self.package)
        self.assertTrue(context['version'])
        self.assertTrue(context['default_pool_url'])

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Archive')
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/archive.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 2)


class BugStatsTableFieldTests(TestCase):
    def setUp(self):
        self.package = create_source_package_with_data('dummy-package')
        create_package_bug_stats(self.package)
        self.field = BugStatsTableField()

    def test_field_context(self):
        """
        Tests field context content
        """
        context = self.field.context(self.package)
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
        self.assertEqual(
            self.field.template_name,
            'core/package-table-fields/bugs.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)


class BasePackageTableTests(TestCase):
    @patch('distro_tracker.core.package_tables.get_template')
    def test_get_template_content(self, get_template):
        '''get_template_content(t) returns the content of the underlying file'''
        get_template.return_value.origin.name = 'foobar'
        with patch('builtins.open', mock_open(read_data='YAY')):
            result = TestPackageTable.get_template_content('fake')
        self.assertEqual(result, 'YAY')

    def test_get_row_template(self):
        '''get_row_template() returns a template concatenating all cells'''
        table = TestPackageTable([])
        with patch.object(table, 'get_template_content') as get_content:
            get_content.side_effect = ['field1', 'field2']
            result = table.get_row_template()
        output = result.render(Context({}))
        self.assertTrue(output.startswith('<tr'))
        self.assertIn('<td', output)
        self.assertIn('field1</td>', output)
        self.assertIn('field2</td>', output)
        self.assertTrue(output.endswith('</tr>\n'))


class GeneralTeamPackageTableTests(TestCase, TemplateTestsMixin):
    def setUp(self):
        self.tested_instance = GeneralTeamPackageTable(None)
        self.user = User.objects.create_user(
            main_email='paul@example.com', password='pw4paul')
        self.team = Team.objects.create_with_slug(
            owner=self.user, name="Team name", public=True)
        self.package = create_source_package_with_data('dummy-package-1')
        create_package_bug_stats(self.package)
        self.team.packages.add(self.package)

    def get_team_page_response(self):
        return self.client.get(self.team.get_absolute_url())

    def get_general_package_table(self, response, title='All team packages'):
        """
        Checks whether the general package table is found in
        the rendered HTML response.
        """
        html = soup(response.content, 'html.parser')
        tables = html.findAll("div", {'class': 'package-table'})
        for table in tables:
            if title in str(table):
                return table
        return False

    def assert_number_of_queries(self, table, number_of_queries):
        with self.assertNumQueries(number_of_queries):
            for row in table.rows:
                for cell in row:
                    self.assertIsNotNone(cell)

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
        self.assert_number_of_queries(table, 5)

        new_package = create_source_package_with_data('another-dummy-package')
        create_package_bug_stats(new_package)
        self.team.packages.add(new_package)
        self.assert_number_of_queries(table, 5)

    def test_table_limit_of_packages(self):
        """
        Tests table with a limited number of packages
        """
        new_package = create_source_package_with_data('dummy-package-2')
        self.team.packages.add(new_package)
        table = GeneralTeamPackageTable(self.team, limit=1)

        self.assertEqual(table.number_of_packages, 2)
        self.assertEqual(len(table.rows), 1)
        # Get the first row
        table_field = table.rows[0]
        self.assertIn(self.package.name, table_field)

        table.limit = 2
        # Get the first row
        table_field = table.rows[0]
        self.assertIn(self.package.name, table_field)
        self.assertNotIn(new_package.name, table_field)
        # Get the the second row
        table_field = table.rows[1]
        self.assertIn(new_package.name, table_field)

    def test_table_with_tag(self):
        """
        Tests table with tag
        """
        tag = 'tag:bugs'
        new_package = create_source_package_with_data('dummy-package-2')
        value = {
            'table_title': 'Packages with bugs'
        }
        PackageData.objects.create(key=tag, package=new_package, value=value)
        self.team.packages.add(new_package)

        # Tag without prefix
        table = GeneralTeamPackageTable(self.team, tag='bugs')
        self.assertEqual(table.title, 'Packages with bugs')
        self.assertTrue(table.relative_url.endswith('?tag=bugs'))

        # Tag with tag prefix
        table = GeneralTeamPackageTable(self.team, tag='tag:bugs')
        self.assertEqual(table.title, 'Packages with bugs')
        self.assertTrue(table.relative_url.endswith('?tag=bugs'))

        # Non-existing tag name
        table = GeneralTeamPackageTable(self.team, tag='does-not-exist')
        self.assertEqual(table.title, table.default_title)
        self.assertEqual(len(table.rows), 0)
        self.assertTrue(table.relative_url.endswith('?tag=does-not-exist'))

    def test_table_for_bugs_tag(self):
        """
        Tests table to display packages with bugs
        """
        tag = 'tag:bugs'
        new_package = create_source_package_with_data('dummy-package-2')
        value = {
            'table_title': 'Packages with bugs'
        }
        PackageData.objects.create(key=tag, package=new_package, value=value)
        self.team.packages.add(new_package)

        response = self.get_team_page_response()
        table = self.get_general_package_table(response, "Packages with bugs")

        self.assertIn("Packages with bugs", str(table))
        self.assertIn(new_package.name, str(table))
        self.assertNotIn(self.package.name, str(table))


class CreateTableFunctionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            main_email='paul@example.com', password='pw4paul')
        self.team = Team.objects.create_with_slug(
            owner=self.user, name="Team name", public=True)
        self.team.packages.add(
            create_source_package_with_data('dummy-package-1'))
        self.team.packages.add(
            create_source_package_with_data('dummy-package-2'))

    def test_create_table_with_valid_params(self):
        """
        Tests table creation for general table and valid params
        """
        # Basic usage
        table = create_table('general', self.team)
        self.assertIsNotNone(table)
        self.assertEqual(table.title, table.default_title)
        self.assertEqual(len(table.rows), 2)

        # With limit
        table = create_table('general', self.team, limit=1)
        self.assertIsNotNone(table)
        self.assertEqual(len(table.rows), 1)

        # With a new title
        table = create_table('general', self.team, title="New title", limit=0)
        self.assertIsNotNone(table)
        self.assertEqual(table.title, "New title")

    def test_create_table_with_invalid_slug(self):
        """
        Tests table creation for a non-existing slug
        """
        # Basic usage
        table = create_table('does-not-exist', self.team)
        self.assertIsNone(table)
