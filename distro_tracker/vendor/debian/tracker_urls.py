# Copyright 2015-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""The URL routes for the vendor.debian app."""
from __future__ import unicode_literals

from django.conf.urls import url

from distro_tracker.vendor.debian.views import CodeSearchView


urlpatterns = [
    # code search
    url(r'^codesearch/$', CodeSearchView.as_view(),
        name='dtracker-code-search'),
]
