# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.shortcuts import render, redirect
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.views.decorators.cache import cache_control
from pts.core.models import get_web_package
from pts.core.utils import render_to_json_response
from pts.core.models import SourcePackage, Package, PseudoPackage


def package_page(request, package_name):
    package = get_web_package(package_name)
    if not package:
        raise Http404
    if package.get_absolute_url() != request.path:
        return redirect(package)
    return render(request, 'core/package.html', {
        'package': package
    })


def legacy_package_url_redirect(request, package_hash, package_name):
    return redirect('pts-package-page', package_name=package_name, permanent=True)


class PackageSearchView(View):
    def get(self, request):
        if 'package_name' not in self.request.GET:
            raise Http404
        package_name = self.request.GET.get('package_name')

        package = get_web_package(package_name)
        if package is not None:
            return redirect(package)
        else:
            return render(request, 'core/package_search.html', {
                'package_name': package_name
            })


class PackageAutocompleteView(View):
    @method_decorator(cache_control(must_revalidate=True, max_age=3600))
    def get(self, request):
        if 'q' not in request.GET:
            raise Http404
        query_string = request.GET['q']
        package_type = request.GET.get('package_type', None)
        MANAGERS = {
            'pseudo': PseudoPackage.objects,
            'source': SourcePackage.objects,
        }
        # When no package type is given include both pseudo and source packages
        filtered = MANAGERS.get(
            package_type,
            Package.objects.exclude(
                package_type=Package.SUBSCRIPTION_ONLY_PACKAGE_TYPE)
        )
        filtered = filtered.filter(name__istartswith=query_string)
        # Extract only the name of the package.
        filtered = filtered.values('name')
        # Limit the number of packages returned from the autocomplete
        AUTOCOMPLETE_ITEMS_LIMIT = 10
        filtered = filtered[:AUTOCOMPLETE_ITEMS_LIMIT]
        return render_to_json_response([package['name'] for package in filtered])
