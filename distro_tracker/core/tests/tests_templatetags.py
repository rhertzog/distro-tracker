# -*- coding: utf-8 -*-

# Copyright 2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker template tags.
"""

from bs4 import BeautifulSoup as soup

from django.template import Context, Template

from distro_tracker.test import SimpleTestCase


class TemplateTagsTests(SimpleTestCase):
    """
    Tests for the ``distro_tracker.core.templatetags`` module.
    """

    @staticmethod
    def get_template(content):
        return Template('{% load distro_tracker_extras %}' + content)

    def parse_toggle_chevron(self, params=''):
        template = self.get_template('{{% toggle_chevron {} %}}'.format(params))
        rendered = template.render(Context())
        return soup(rendered, 'html.parser')

    def test_toggle_chevron_generates_a_toggle_details_link(self):
        html = self.parse_toggle_chevron()
        link = html.find(name='span')
        self.assertIsNotNone(link)
        self.assertIn(link.get_text(), "[Toggle details]")

    def test_toggle_chevron_generates_a_custom_link(self):
        html = self.parse_toggle_chevron('title="abc"')
        link = html.find(name='span')
        self.assertIsNotNone(link)
        self.assertIn(link.get_text(), "[abc]")

    def get_breakable_version(self, version):
        template = self.get_template('{{version|breakable}}')
        return template.render(Context({'version': version}))

    def test_breakable_on_short_string(self):
        """
        Short strings need no breakpoint.
        """
        self.assertEqual(self.get_breakable_version('1.2-3'), '1.2-3')

    def test_breakable_on_long_string(self):
        """
        Long strings get breakpoints after [~.+-] characters.
        """
        version = "20180727~birthday.gift12+deb9u1-4"
        expected = "20180727~<wbr>birthday.<wbr>gift12+<wbr>deb9u1-<wbr>4"
        self.assertEqual(self.get_breakable_version(version), expected)

    def test_breakable_on_short_html(self):
        """
        Ensure we don't allow HTML injection on short string.
        """
        version = "<>&foo;"
        expected = "&lt;&gt;&amp;foo;"
        self.assertEqual(self.get_breakable_version(version), expected)

    def test_breakable_on_long_html(self):
        """
        Ensure we don't allow HTML injection on long string.
        """
        version = "1234567890<>&foo;"
        expected = "1234567890&lt;&gt;&amp;foo;"
        self.assertEqual(self.get_breakable_version(version), expected)

    def test_breakable_on_none(self):
        """
        Ensure we don't fail on None value.
        """
        self.assertEqual(self.get_breakable_version(None), '')
