# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

import collections

from debian.debian_support import version_compare, BaseVersion

from django.shortcuts import render_to_response
from django.shortcuts import get_list_or_404, get_object_or_404

from distro_tracker.core.models import RepositoryRelation
from distro_tracker.core.models import Repository

CATEGORIES_VERSION_COMPARISON = {
    'missing_pkg': 'Missing packages',
    'older_version': 'Packages with older version',
    'older_revision': 'Packages with older revision',
    'new_pkg': 'Packages not in initial distribution',
    'newer_version': 'Packages with newer version',
    'newer_revision': 'Packages with newer revision'
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
    deriv_version = divide(a)
    initial_version = divide(b)

    if deriv_version['epoch'] == initial_version['epoch']:
        if deriv_version['upstream'] == initial_version['upstream']:
            if version_compare(deriv_version['debian_rev'],
                               initial_version['debian_rev']) < 0:
                return 'older_revision'
            else:
                return 'newer_revision'
        elif version_compare(deriv_version['upstream'],
                             initial_version['upstream']) < 0:
            return 'older_version'
        else:
            return 'newer_version'
    elif version_compare(deriv_version['epoch'],
                         initial_version['epoch']) < 0:
        return 'older_version'
    else:
        return 'newer_version'


def generatediff(relation):
    # identify the initial repo
    deriv_repository = relation.repository
    parent_repository = relation.target_repository

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

    def comparison_key(x):
        return (CATEGORIES_PRIORITY[x['category']], x['name'])

    # Sort by category first, and then by name
    pkglist.sort(key=comparison_key)

    return pkglist


def divide(version):
    baseversion = BaseVersion(version)
    divided_version = {}
    if baseversion.epoch is None:
        divided_version['epoch'] = '~'
    else:
        divided_version['epoch'] = baseversion.epoch

    if baseversion.upstream_version is None:
        divided_version['upstream'] = '~'
    else:
        divided_version['upstream'] = baseversion.upstream_version

    if baseversion.debian_revision is None:
        divided_version['debian_rev'] = '~'
    else:
        divided_version['debian_rev'] = baseversion.debian_revision
    return divided_version


def index(request):
    list_derivatives = get_list_or_404(RepositoryRelation, name='derivative')
    return render_to_response('derivative/index.html',
                              {'list_derivatives': list_derivatives})


def comparison(request, distribution):
    repository = get_object_or_404(Repository, shorthand=distribution)
    relation = get_object_or_404(repository.relations, name='derivative')
    pkglist = generatediff(relation)
    context = {
        'pkglist': pkglist,
        'categories': CATEGORIES_VERSION_COMPARISON,
        'repository': repository,
        'target_repository': relation.target_repository,
    }
    return render_to_response('derivative/comparison.html', context)
