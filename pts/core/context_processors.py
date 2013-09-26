# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements Django context processors specific for the PTS."""
from __future__ import unicode_literals
from django.conf import settings
from django.contrib.sites.models import Site


#: Defines a dictionary of all PTS extra context key/value pairs that are to be
#: included in the :class:`RequestContext <django.template.RequestContext>`.
PTS_EXTRAS = {
    'PTS_VENDOR_NAME': settings.PTS_VENDOR_NAME,
    'PTS_VENDOR_URL': getattr(settings, 'PTS_VENDOR_URL', ''),
    'PTS_CONTACT_EMAIL': settings.PTS_CONTACT_EMAIL,
    'PTS_CONTROL_EMAIL': settings.PTS_CONTROL_EMAIL,
    'PTS_SITE_DOMAIN': Site.objects.get_current(),
}


def pts_extras(request):
    """
    The context processor which includes the
    :py:data:`PTS_EXTRAS <pts.core.context_processors.PTS_EXTRAS>` in the
    :class:`RequestContext <django.template.RequestContext>`.
    """
    return PTS_EXTRAS
