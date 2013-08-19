# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""The URL routes for the PTS project."""

from __future__ import unicode_literals
from django.conf.urls import patterns, include, url
from django.views.generic import TemplateView
from pts.core.views import PackageSearchView, PackageAutocompleteView
from pts.core.views import ActionItemJsonView, ActionItemView
from pts.core.news_feed import PackageNewsFeed

from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Redirects for the old PTS package page URLs
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)\.html$',
        'pts.core.views.legacy_package_url_redirect'),

    # Permanent redirect for the old RSS URL
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)/news\.rss20\.xml$',
        'pts.core.views.legacy_rss_redirect'),

    url(r'^search$', PackageSearchView.as_view(),
        name='pts-package-search'),

    url(r'^api/package/search/autocomplete$', PackageAutocompleteView.as_view(),
        name='pts-api-package-autocomplete'),

    url(r'^api/action-items/(?P<item_pk>\d+)$', ActionItemJsonView.as_view(),
        name='pts-api-action-item'),

    url(r'^admin/', include(admin.site.urls)),
    url(r'^news/(?P<news_id>\d+)$', 'pts.core.views.news_page',
        name='pts-news-page'),
    url(r'^action-items/(?P<item_pk>\d+)$', ActionItemView.as_view(),
        name='pts-action-item'),

    # RSS news feed
    url(r'^(?P<package_name>.+)/rss$', PackageNewsFeed(),
        name='pts-package-rss-news-feed'),

    # The package page view. It must be listed *after* the admin URL so that
    # the admin URL is not interpreted as a package named "admin".
    url(r'^(?P<package_name>.+)$', 'pts.core.views.package_page',
        name='pts-package-page'),

    url(r'^$', TemplateView.as_view(template_name='core/index.html'),
        name='pts-index'),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
)


from django.conf import settings
if settings.DEBUG:
    urlpatterns = patterns('',
        (r'^media/(?P<path>.*)$',
         'django.views.static.serve', {
            'document_root': settings.MEDIA_ROOT
          }
        ),
    ) + urlpatterns
