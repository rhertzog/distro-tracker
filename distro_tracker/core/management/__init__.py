# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.contrib.sites import models as sites_app
from django.contrib.sites.models import Site
from django.db.models import signals
from django.conf import settings
from django.dispatch import receiver


@receiver(signals.post_syncdb, sender=sites_app)
def create_site(app, created_models, verbosity, **kwargs):
    """
    Override the name and domain of the default site created when the sites app
    is installed.

    Do not use example.com, but the domain from settings.
    """
    if Site in created_models:
        site, _ = Site.objects.get_or_create(pk=settings.SITE_ID)
        site.name = 'Package Tracking System'
        site.domain = settings.DISTRO_TRACKER_FQDN
        site.save()
