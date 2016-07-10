# -*- coding: utf-8 -*-

# Copyright 2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker template tags.
"""
from __future__ import unicode_literals

from bs4 import BeautifulSoup as soup
from django.template import Template, Context

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
        link = html.find(name='a')
        self.assertIsNotNone(link)
        self.assertIn(link.get_text(), "[Toggle details]")

    def test_toggle_chevron_generates_a_custom_link(self):
        html = self.parse_toggle_chevron('title="abc"')
        link = html.find(name='a')
        self.assertIsNotNone(link)
        self.assertIn(link.get_text(), "[abc]")
