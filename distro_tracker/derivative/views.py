# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Django views for the distro_tracker.derivative application."""

from django.shortcuts import get_list_or_404, get_object_or_404, render

from distro_tracker.core.models import Repository, RepositoryRelation

from .utils import CATEGORIES_VERSION_COMPARISON, compare_repositories


def index(request):
    """Default view."""
    list_derivatives = get_list_or_404(RepositoryRelation, name='derivative')
    return render(request, 'derivative/index.html',
                  {'list_derivatives': list_derivatives})


def comparison(request, distribution):
    """View comparing a distribution with its parent distribution."""
    repository = get_object_or_404(Repository, shorthand=distribution)
    relation = get_object_or_404(repository.relations, name='derivative')
    pkglist = compare_repositories(repository, relation.target_repository)
    context = {
        'pkglist': pkglist,
        'categories': CATEGORIES_VERSION_COMPARISON,
        'repository': repository,
        'target_repository': relation.target_repository,
    }
    return render(request, 'derivative/comparison.html', context)
