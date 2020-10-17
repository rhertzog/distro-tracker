# Copyright 2020 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Utilities for generating URLs of various kinds
"""

from django.utils.http import urlencode


def RepologyUrl(target_page, repo, package):
    query = urlencode({
        'name_type': 'srcname',
        'noautoresolve': 'on',
        'repo': repo,
        'target_page': target_page,
        'name': package,
    })
    return 'https://repology.org/tools/project-by?' + query


def RepologyVersionsUrl(repo, package):
    return RepologyUrl('project_versions', repo, package)


def RepologyPackagesUrl(repo, package):
    return RepologyUrl('project_packages', repo, package)
