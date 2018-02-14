# Copyright 2013-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements the RSS news feed."""

from itertools import chain
import re

from django.conf import settings
from django.http import Http404
from django.contrib.syndication.views import Feed

from distro_tracker.core.models import get_web_package
from distro_tracker.core.models import News
from distro_tracker.core.models import NewsRenderer
from distro_tracker.core.models import ActionItem


def filter_control_chars(method):
    # We have to filter out control chars otherwise the FeedGenerator
    # raises UnserializableContentError (see django/utils/xmlutils.py)
    def wrapped(self, obj):
        result = method(self, obj)
        return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', result)
    return wrapped


class PackageNewsFeed(Feed):
    _DEFAULT_LIMIT = 30

    def get_object(self, request, package_name):
        package = get_web_package(package_name)
        if package is None:
            raise Http404

        return package

    @filter_control_chars
    def title(self, obj):
        return "{vendor} package news for {pkg}".format(
            vendor=settings.DISTRO_TRACKER_VENDOR_NAME,
            pkg=obj.name)

    @filter_control_chars
    def link(self, obj):
        return obj.get_absolute_url()

    @filter_control_chars
    def description(self, obj):
        return (
            "Latest developer's news for {vendor} source package {pkg}"
            .format(vendor=settings.DISTRO_TRACKER_VENDOR_NAME, pkg=obj.name)
        )

    def items(self, obj):
        item_limit = getattr(settings, 'DISTRO_TRACKER_RSS_ITEM_LIMIT',
                             self._DEFAULT_LIMIT)

        news = obj.news_set.all()
        action_items = obj.action_items.all()

        def item_key(item):
            if isinstance(item, ActionItem):
                return item.last_updated_timestamp
            elif isinstance(item, News):
                return item.datetime_created

        all_items = chain(news, action_items)
        return sorted(all_items, key=item_key, reverse=True)[:item_limit]

    @filter_control_chars
    def item_title(self, item):
        if isinstance(item, News):
            return item.title
        elif isinstance(item, ActionItem):
            return item.short_description

    @filter_control_chars
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
