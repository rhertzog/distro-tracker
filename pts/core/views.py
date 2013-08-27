# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Views for the :mod:`pts.core` app."""
from __future__ import unicode_literals
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.views.decorators.cache import cache_control
from pts.core.models import get_web_package
from pts.core.utils import render_to_json_response
from pts.core.models import SourcePackageName, PackageName, PseudoPackageName
from pts.core.models import ActionItem
from pts.core.models import News, NewsRenderer
from pts.core.panels import get_panels_for_package


def package_page(request, package_name):
    """
    Renders the package page.
    """
    package = get_web_package(package_name)
    if not package:
        raise Http404
    if package.get_absolute_url() != request.path:
        return redirect(package)

    return render(request, 'core/package.html', {
        'package': package,
        'panels': get_panels_for_package(package),
    })


def package_page_redirect(request, package_name):
    """
    Catch-all view which tries to redirect the user to a package page
    """
    return redirect('pts-package-page', package_name=package_name)


def legacy_package_url_redirect(request, package_hash, package_name):
    """
    Redirects access to URLs in the form of the "old" PTS package URLs to the
    new package URLs.

    .. note::
       The "old" package URL is: /<hash>/<package_name>.html
    """
    return redirect('pts-package-page', package_name=package_name, permanent=True)


class PackageSearchView(View):
    """
    A view which responds to package search queries.
    """
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
    """
    A view which responds to package auto-complete queries.

    Renders a JSON list of package names matching the given query, meaning
    their name starts with the given query parameter.
    """
    @method_decorator(cache_control(must_revalidate=True, max_age=3600))
    def get(self, request):
        if 'q' not in request.GET:
            raise Http404
        query_string = request.GET['q']
        package_type = request.GET.get('package_type', None)
        MANAGERS = {
            'pseudo': PseudoPackageName.objects,
            'source': SourcePackageName.objects,
        }
        # When no package type is given include both pseudo and source packages
        filtered = MANAGERS.get(
            package_type,
            PackageName.objects.exclude(
                package_type=PackageName.SUBSCRIPTION_ONLY_PACKAGE_TYPE)
        )
        filtered = filtered.filter(name__istartswith=query_string)
        # Extract only the name of the package.
        filtered = filtered.values('name')
        # Limit the number of packages returned from the autocomplete
        AUTOCOMPLETE_ITEMS_LIMIT = 10
        filtered = filtered[:AUTOCOMPLETE_ITEMS_LIMIT]
        return render_to_json_response([package['name'] for package in filtered])


def news_page(request, news_id):
    """
    Displays a news item's full content.
    """
    news = get_object_or_404(News, pk=news_id)

    renderer_class = NewsRenderer.get_renderer_for_content_type(news.content_type)
    if renderer_class is None:
        renderer_class = NewsRenderer.get_renderer_for_content_type('text/plain')

    renderer = renderer_class(news)
    print news.content_type
    return render(request, 'core/news.html', {
        'news_renderer': renderer,
        'news': news,
    })


class ActionItemJsonView(View):
    """
    View renders a :class:`pts.core.models.ActionItem` in a JSON response.
    """
    @method_decorator(cache_control(must_revalidate=True, max_age=3600))
    def get(self, request, item_pk):
        item = get_object_or_404(ActionItem, pk=item_pk)
        return render_to_json_response(item.to_dict())


class ActionItemView(View):
    """
    View renders a :class:`pts.core.models.ActionItem` in an HTML response.
    """
    def get(self, request, item_pk):
        item = get_object_or_404(ActionItem, pk=item_pk)
        return render(request, 'core/action-item.html', {
            'item': item,
        })


def legacy_rss_redirect(request, package_hash, package_name):
    """
    Redirects old package RSS news feed URLs to the new ones.
    """
    return redirect(
        'pts-package-rss-news-feed',
        package_name=package_name,
        permanent=True)
