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
from django.conf import settings
from django.contrib.sites.models import Site


PTS_EXTRAS = {
    'PTS_VENDOR_NAME': settings.PTS_VENDOR_NAME,
    'PTS_VENDOR_URL': getattr(settings, 'PTS_VENDOR_URL', ''),
    'PTS_CONTACT_EMAIL': settings.PTS_CONTACT_EMAIL,
    'PTS_CONTROL_EMAIL': settings.PTS_CONTROL_EMAIL,
    'PTS_SITE_DOMAIN': Site.objects.get_current(),
}


def pts_extras(request):
    return PTS_EXTRAS
