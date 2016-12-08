# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

import collections

from debian.debian_support import version_compare, BaseVersion

CATEGORIES_VERSION_COMPARISON = {
    'missing_pkg': 'Packages missing in the derivative',
    'older_version': 'Packages with older upstream version',
    'older_revision': 'Packages with older Debian revision',
    'new_pkg': 'Packages specific to the derivative',
    'newer_version': 'Packages with newer upstream version',
    'newer_revision': 'Packages with newer Debian revision'
}

CATEGORIES_PRIORITY = {
    'older_version': 1,
    'older_revision': 2,
    'missing_pkg': 3,
    'new_pkg': 4,
    'newer_version': 5,
    'newer_revision': 6
}


def categorize_version_comparison(a, b):
    """Returns an identifier that categorizes the difference
    between a and b. The identifier can be looked up in
    CATEGORIES_VERSION_COMPARISON to have a long description."""
    if a == b:
        return 'equal'
    if a is None:
        return 'missing_pkg'
    if b is None:
        return 'new_pkg'

    deriv_epoch, deriv_upstream, deriv_revision = split_version(a)
    parent_epoch, parent_upstream, parent_revision = split_version(b)

    if deriv_epoch == parent_epoch:
        if deriv_upstream == parent_upstream:
            if version_compare(deriv_revision, parent_revision) < 0:
                return 'older_revision'
            else:
                return 'newer_revision'
        elif version_compare(deriv_upstream, parent_upstream) < 0:
            return 'older_version'
        else:
            return 'newer_version'
    elif version_compare(deriv_epoch, parent_epoch) < 0:
        return 'older_version'
    else:
        return 'newer_version'


def compare_repositories(deriv_repository, parent_repository):
    # create a dict with all source packages and versions
    all_pkgs = collections.defaultdict(lambda: {})
    for name, version in deriv_repository.source_entries.values_list(
            'source_package__source_package_name__name',
            'source_package__version'):
        all_pkgs[name]['deriv_version'] = version
    for name, version in parent_repository.source_entries.values_list(
            'source_package__source_package_name__name',
            'source_package__version'):
        all_pkgs[name]['parent_version'] = version

    for pkg in all_pkgs:
        all_pkgs[pkg]['name'] = pkg
        all_pkgs[pkg]['category'] = categorize_version_comparison(
            all_pkgs[pkg].get('deriv_version'),
            all_pkgs[pkg].get('parent_version'))

    pkglist = [v for v in all_pkgs.values() if v['category'] != 'equal']

    # Sort by category first, and then by name
    pkglist.sort(key=lambda x: (CATEGORIES_PRIORITY[x['category']], x['name']))

    return pkglist


def split_version(version):
    baseversion = BaseVersion(version)
    return (baseversion.epoch or '~', baseversion.upstream_version or '~',
            baseversion.debian_revision or '~')
