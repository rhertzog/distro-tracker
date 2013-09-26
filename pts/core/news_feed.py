# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements the RSS news feed."""

from __future__ import unicode_literals
from django.conf import settings
from django.http import Http404
from django.contrib.syndication.views import Feed
from pts.core.models import get_web_package
from pts.core.models import News
from pts.core.models import NewsRenderer
from pts.core.models import ActionItem
from itertools import chain


class PackageNewsFeed(Feed):
    _DEFAULT_LIMIT = 30

    def get_object(self, request, package_name):
        package = get_web_package(package_name)
        if package is None:
            raise Http404

        return package

    def title(self, obj):
        return "{vendor} PTS news for {pkg}".format(
            vendor=settings.PTS_VENDOR_NAME,
            pkg=obj.name)

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return "Latest developer's news for {vendor} source package {pkg}".format(
            vendor=settings.PTS_VENDOR_NAME,
            pkg=obj.name)

    def items(self, obj):
        item_limit = getattr(settings, 'PTS_RSS_ITEM_LIMIT', self._DEFAULT_LIMIT)

        news = obj.news_set.all()
        action_items = obj.action_items.all()

        def item_key(item):
            if isinstance(item, ActionItem):
                return item.last_updated_timestamp
            elif isinstance(item, News):
                return item.datetime_created

        all_items = chain(news, action_items)
        return sorted(all_items, key=item_key, reverse=True)[:item_limit]

    def item_title(self, item):
        if isinstance(item, News):
            return item.title
        elif isinstance(item, ActionItem):
            return item.short_description

    def item_description(self, item):
        if isinstance(item, News):
            renderer_class = NewsRenderer.get_renderer_for_content_type(
                item.content_type)
            if renderer_class is None:
                renderer_class = NewsRenderer.get_renderer_for_content_type(
                    'text/plain')
            renderer = renderer_class(item)

            return renderer.render_to_string()
        elif isinstance(item, ActionItem):
            return item.full_description


    def item_pubdate(self, item):
        if isinstance(item, ActionItem):
            return item.last_updated_timestamp
        elif isinstance(item, News):
            return item.datetime_created
