# -*- coding: utf-8 -*-

# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for Kali-specific modules/functionality of Distro Tracker.
"""

from __future__ import unicode_literals

import email.message

from distro_tracker.test import SimpleTestCase
from distro_tracker.vendor.kali.rules import classify_message


class ClassifyMessageTests(SimpleTestCase):

    def setUp(self):
        self.message = email.message.Message()

    def run_classify(self, package=None, keyword=None):
        return classify_message(self.message, package, keyword)

    def test_classify_message_recognizes_rebuildd_logs(self):
        self.message['X-Rebuildd-Version'] = '0.4.1'
        self.message['X-Rebuildd-Host'] = 'foo.kali.org'
        self.message['Subject'] = ('[rebuildd] Log for failed build of '
                                   'cisco-ocs_0.1-1kali1 on kali/i386')
        pkg, keyword = self.run_classify()
        self.assertEqual(pkg, 'cisco-ocs')
        self.assertEqual(keyword, 'build')
