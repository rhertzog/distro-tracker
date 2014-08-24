# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the :mod:`distro_tracker.core.news_feed` module.
"""
from __future__ import unicode_literals
from distro_tracker.test import TestCase
from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from distro_tracker.core.models import PackageName
from distro_tracker.core.models import ActionItemType
from distro_tracker.core.models import ActionItem
from distro_tracker.core.models import News

from xml.dom import minidom
from datetime import datetime
import os


@override_settings(TEMPLATE_DIRS=(os.path.join(
    os.path.dirname(__file__),
    'tests-data/tests-templates'),))
class NewsFeedTests(TestCase):
    """
    Tests the generation of the package news feed.
    """
    def setUp(self):
        self.package = PackageName.objects.create(
            source=True,
            name='dummy-package')

    def get_package_news_feed_url(self, package_name):
        return reverse('dtracker-package-rss-news-feed', kwargs={
            'package_name': package_name,
        })

    def get_rss_feed_response(self, package_name):
        news_feed_url = self.get_package_news_feed_url(package_name)
        return self.client.get(news_feed_url)

    def get_item_dom_element(self, item_title, content):
        """
        :returns: The XML DOM element with the given title is converted to
            a dict.
            ``None`` if an item with the given title cannot be found in the
            news feed.
        :rtype: :class:`dict`
        """
        xmldoc = minidom.parseString(content)

        items = xmldoc.getElementsByTagName('item')

        def extract_child_value(item, name):
            return item.getElementsByTagName(name)[0].childNodes[0].toxml()

        for item in items:
            title = extract_child_value(item, 'title')
            if title == item_title:
                return {
                    'description': extract_child_value(item, 'description'),
                    'title': title,
                    'pubDate': extract_child_value(item, 'pubDate'),
                    'guid': extract_child_value(item, 'guid'),
                    'link': extract_child_value(item, 'link'),
                }

        return None

    def get_all_dom_items(self, content):
        """
        :returns: A list of XML DOM elements converted to a dict.
        :rtype: :class:`list`
        """
        xmldoc = minidom.parseString(content)

        items = xmldoc.getElementsByTagName('item')

        def extract_child_value(item, name):
            return item.getElementsByTagName(name)[0].childNodes[0].toxml()

        return [
            {
                'description': extract_child_value(item, 'description'),
                'title': extract_child_value(item, 'title'),
                'pubDate': extract_child_value(item, 'pubDate'),
                'guid': extract_child_value(item, 'guid'),
                'link': extract_child_value(item, 'link'),
            }
            for item in items
        ]

    def test_news_feed_exists(self):
        """
        Tests that the news feed for the package correctly responds when there
        are no news or action items.
        """
        response = self.get_rss_feed_response(self.package.name)

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.content.startswith(
            b'<?xml version="1.0" encoding="utf-8"?>'))

    def test_no_news_feed_for_non_existing_package(self):
        """
        Tests that there is no news feed for a package which does not exist.
        """
        response = self.get_rss_feed_response('no-exist')

        self.assertEqual(404, response.status_code)

    def test_news_feed_action_item(self):
        """
        Tests that :class:`ActionItem <distro_tracker.core.models.ActionItem>`
        instances are included in the news feed.
        """
        # Create an action item
        item_type = ActionItemType.objects.create(
            type_name='item-type',
            full_description_template='action-item-test.html')

        item = ActionItem.objects.create(
            item_type=item_type,
            package=self.package,
            short_description="This is a short description",
            extra_data=[
                'one', 'two',
            ])

        response = self.get_rss_feed_response(self.package.name)

        dom_item = self.get_item_dom_element(
            item.short_description, response.content)
        self.assertIsNotNone(dom_item)
        # The full description is correctly set?
        self.assertEqual(item.full_description, dom_item['description'])
        # The guid and url are set to the action item's url
        self.assertTrue(dom_item['guid'].endswith(item.get_absolute_url()))
        self.assertTrue(dom_item['link'].endswith(item.get_absolute_url()))
        # pubDate is the action item's last updated time?
        pub_date = datetime.strptime(
            dom_item['pubDate'],
            '%a, %d %b %Y %H:%M:%S +0000')
        self.assertTrue(pub_date, item.last_updated_timestamp)

    def test_news_feed_news_item(self):
        """
        Tests that :class:`News <distro_tracker.core.models.News>` instances are
        included in the news feed.
        """
        expected_content = 'Some content'
        title = 'Some title'
        news = News.objects.create(
            title=title,
            content=expected_content,
            package=self.package
        )

        response = self.get_rss_feed_response(self.package.name)

        dom_item = self.get_item_dom_element(
            news.title,
            response.content)
        self.assertIsNotNone(dom_item)
        self.assertIn(expected_content, dom_item['description'])
        self.assertTrue(dom_item['guid'].endswith(news.get_absolute_url()))
        self.assertTrue(dom_item['link'].endswith(news.get_absolute_url()))
        # pubDate is the news' created time?
        pub_date = datetime.strptime(
            dom_item['pubDate'],
            '%a, %d %b %Y %H:%M:%S +0000')
        self.assertTrue(pub_date, news.datetime_created)

    def test_action_items_and_news(self):
        """
        Tests that both action items and news are included in the same feed.
        """
        # Create a News item
        expected_content = 'Some content'
        title = 'Some title'
        news = News.objects.create(
            title=title,
            content=expected_content,
            package=self.package
        )
        # Create an action item
        item_type = ActionItemType.objects.create(
            type_name='item-type',
            full_description_template='action-item-test.html')

        item = ActionItem.objects.create(
            item_type=item_type,
            package=self.package,
            short_description="This is a short description",
            extra_data=[
                'one', 'two',
            ])

        response = self.get_rss_feed_response(self.package.name)

        # Both the news item and the action item are found in the feed?
        self.assertIsNotNone(self.get_item_dom_element(
            news.title, response.content))
        self.assertIsNotNone(self.get_item_dom_element(
            item.short_description, response.content))

    def test_action_item_and_news_sorted(self):
        """
        Tests that the news items are always sorted in decreasing date order,
        even when action items and news items are mixed.
        """
        # Create a News item
        expected_content = 'Some content'
        title = 'Some title'
        News.objects.create(
            title=title,
            content=expected_content,
            package=self.package
        )
        # Create an action item
        item_type = ActionItemType.objects.create(
            type_name='item-type',
            full_description_template='action-item-test.html')

        ActionItem.objects.create(
            item_type=item_type,
            package=self.package,
            short_description="This is a short description",
            extra_data=[
                'one', 'two',
            ])

        response = self.get_rss_feed_response(self.package.name)

        # The news items are sorted by pubDate
        dom_items = self.get_all_dom_items(response.content)
        self.assertEqual(
            dom_items,
            sorted(
                dom_items,
                key=lambda x: datetime.strptime(x['pubDate'],
                                                '%a, %d %b %Y %H:%M:%S +0000'),
                reverse=True))

        # Add two more items: news item and action item in different order
        # Create an action item
        other_type = ActionItemType.objects.create(
            type_name='item-type-2',
            full_description_template='action-item-test.html')

        ActionItem.objects.create(
            item_type=other_type,
            package=self.package,
            short_description="This is a short description",
            extra_data=[
                'one', 'two',
            ])
        # Create a News item
        News.objects.create(
            title=title,
            content=expected_content,
            package=self.package
        )

        response = self.get_rss_feed_response(self.package.name)

        # The items are still sorted by pubDate?
        dom_items = self.get_all_dom_items(response.content)

        self.assertEqual(
            dom_items,
            sorted(
                dom_items,
                key=lambda x: datetime.strptime(x['pubDate'],
                                                '%a, %d %b %Y %H:%M:%S +0000'),
                reverse=True))

    def test_action_item_news_limited(self):
        item_limit = 1
        with self.settings(DISTRO_TRACKER_RSS_ITEM_LIMIT=item_limit):
            # Create two news feed items
            # Create a News item
            expected_content = 'Some content'
            title = 'Some title'
            News.objects.create(
                title=title,
                content=expected_content,
                package=self.package
            )
            # Create an action item
            item_type = ActionItemType.objects.create(
                type_name='item-type',
                full_description_template='action-item-test.html')

            ActionItem.objects.create(
                item_type=item_type,
                package=self.package,
                short_description="This is a short description",
                extra_data=[
                    'one', 'two',
                ])

            response = self.get_rss_feed_response(self.package.name)

            dom_items = self.get_all_dom_items(response.content)
            self.assertEqual(item_limit, len(dom_items))

    def test_legacy_redirect(self):
        legacy_url = '/{h}/{pkg}/news.rss20.xml'.format(
            h=self.package.name[0],
            pkg=self.package.name)

        response = self.client.get(legacy_url)

        # URL permanently redirected to the new url
        self.assertRedirects(
            response,
            self.get_package_news_feed_url(self.package.name),
            status_code=301)

    def test_package_page_contains_news_feed_url(self):
        pkg_url = reverse('dtracker-package-page', kwargs={
            'package_name': self.package.name
        })
        rss_url = self.get_package_news_feed_url(self.package.name)
        News.objects.create(
            title="Hello world",
            content="Hello world",
            package=self.package
        )

        response = self.client.get(pkg_url)

        self.assertIn('<a title="rss feed" href="{}">'.format(rss_url),
                      response.content.decode('utf8'))
