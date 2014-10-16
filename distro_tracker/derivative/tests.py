# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for the :mod:`distro_tracker.related_repositories` app.
"""

from django.test import TestCase

from distro_tracker.core.models import Repository
from distro_tracker.core.models import RepositoryRelation
from distro_tracker.core.models import SourcePackageName
from distro_tracker.derivative.views import generatediff
from distro_tracker.derivative.views import divide
from distro_tracker.derivative.views import categorize_version_comparison


class GenerateComparatingListTest(TestCase):
    def add_package(self, name, v1, v2):
        """Create package with v1 in derivative and v2 in parent."""
        pkgname = SourcePackageName.objects.create(name=name)
        for version, repo in ((v1, self.derivative_repo),
                              (v2, self.target_repo)):
            if not version:
                continue
            srcpkg = pkgname.source_package_versions.create(version=version)
            srcpkg.repository_entries.create(repository=repo)

    def setUp(self):
        self.derivative_repo = Repository.objects.create(
            name='derivative_repo', shorthand='derivative_repo',
            codename='derivative_codename', suite='derivative_suite')
        self.target_repo = Repository.objects.create(
            name='target_repo', shorthand='target_repo',
            codename='initial_codename', suite='initial_suite')

        self.relation = RepositoryRelation.objects.create(
            repository=self.derivative_repo,
            target_repository=self.target_repo,
            name='derivative')

        self.add_package('pkg1', '1.0.0', '2.0.0')
        self.add_package('pkg2', '1.0.0', '1.0.1')
        self.add_package('foopkg', '1.0.0', '1.0.1')

    def test_generatediff_same_categories(self):
        # Test that the list is correctly sorted by package name as all packages
        # are in the same category
        pkglist = generatediff(self.relation)
        self.assertEqual(pkglist[0]['name'], 'foopkg')
        self.assertEqual(pkglist[1]['name'], 'pkg1')
        self.assertEqual(pkglist[0]['category'], pkglist[2]['category'])
        self.assertEqual(pkglist[0]['category'], 'older_version')

    def test_generatediff_different_categories(self):
        # Test that the list is sorted by category then by name
        self.add_package('foopkg2', None, '1.0.1')
        self.add_package('firstpkg', None, '1.0')

        pkglist = generatediff(self.relation)

        self.assertEqual(pkglist[0]['name'], 'foopkg')
        self.assertEqual(pkglist[1]['name'], 'pkg1')
        self.assertEqual(pkglist[0]['category'], pkglist[2]['category'])
        self.assertEqual(pkglist[0]['category'], 'older_version')
        self.assertEqual(pkglist[3]['category'], 'missing_pkg')
        self.assertEqual(pkglist[4]['name'], 'foopkg2')


class CategorizeVersionComparisonTest(TestCase):
    def test_version_equal(self):
        a = '2.1.0-1'
        b = '2.1.0-1'
        self.assertEqual('equal', categorize_version_comparison(a, b))

    def test_first_version_is_None(self):
        a = None
        b = '2.1.0-1'
        self.assertEqual('missing_pkg', categorize_version_comparison(a, b))

    def test_second_version_is_missing(self):
        a = '2.1.0-1'
        b = None
        self.assertEqual('new_pkg', categorize_version_comparison(a, b))

    def test_epoch_is_older(self):
        a = '0:2.1.0.0'
        b = '1:1.0.1-4'
        self.assertEqual('older_version', categorize_version_comparison(a, b))

    def test_older_version(self):
        a = '1:2.1.3-4'
        b = '1:2.1.6'
        self.assertEqual('older_version', categorize_version_comparison(a, b))

    def test_newer_version(self):
        a = '1:2.1.6'
        b = '1:2.1.3-4'
        self.assertEqual('newer_version', categorize_version_comparison(a, b))

    def test_older_revision(self):
        a = '1:2.1.3-4'
        b = '1:2.1.3-6'
        self.assertEqual('older_revision', categorize_version_comparison(a, b))

    def test_newer_revision(self):
        a = '2.1.3-8'
        b = '2.1.3-6'
        self.assertEqual('newer_revision', categorize_version_comparison(a, b))


class DivideVersionTest(TestCase):
    def test_with_epoch_and_revision(self):
        version = '4:9.3.4-1-12'
        divide_version = divide(version)
        self.assertEqual(divide_version['epoch'], '4')
        self.assertEqual(divide_version['upstream'], '9.3.4-1')
        self.assertEqual(divide_version['debian_rev'], '12')

    def test_without_epoch_but_revision(self):
        version = '9.3.4-12'
        divide_version = divide(version)
        self.assertEqual(divide_version['epoch'], '~')
        self.assertEqual(divide_version['upstream'], '9.3.4')
        self.assertEqual(divide_version['debian_rev'], '12')

    def test_without_epoch_and_revision(self):
        version = '9.3.4'
        divide_version = divide(version)
        self.assertEqual(divide_version['epoch'], '~')
        self.assertEqual(divide_version['upstream'], '9.3.4')
        self.assertEqual(divide_version['debian_rev'], '~')
