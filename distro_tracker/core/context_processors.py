# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements Django context processors specific to Distro Tracker."""
from django.conf import settings

#: Defines a dictionary of all Distro Tracker extra context key/value pairs that
#: are to be included in the
#: :class:`RequestContext <django.template.RequestContext>`.
DISTRO_TRACKER_EXTRAS = {
    'DISTRO_TRACKER_VENDOR_NAME': settings.DISTRO_TRACKER_VENDOR_NAME,
    'DISTRO_TRACKER_VENDOR_URL': getattr(settings, 'DISTRO_TRACKER_VENDOR_URL',
                                         ''),
    'DISTRO_TRACKER_CONTACT_EMAIL': settings.DISTRO_TRACKER_CONTACT_EMAIL,
    'DISTRO_TRACKER_CONTROL_EMAIL': settings.DISTRO_TRACKER_CONTROL_EMAIL,
    'DISTRO_TRACKER_SITE_DOMAIN': settings.DISTRO_TRACKER_FQDN,
}


def extras(request):
    """
    The context processor which includes the
    :py:data:`DISTRO_TRACKER_EXTRAS
    <distro_tracker.core.context_processors.DISTRO_TRACKER_EXTRAS>` in the
    :class:`RequestContext <django.template.RequestContext>`.
    """
    return DISTRO_TRACKER_EXTRAS
