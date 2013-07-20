# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

"""
Debian-specific models.
"""

from __future__ import unicode_literals
from django.db import models
from django.utils.encoding import python_2_unicode_compatible

from pts.core.utils import SpaceDelimitedTextField


@python_2_unicode_compatible
class DebianContributor(models.Model):
    """
    Model containing additional Debian-specific information about contributors.
    """
    email = models.OneToOneField('core.ContributorEmail')
    agree_with_low_threshold_nmu = models.BooleanField(default=False)
    is_debian_maintainer = models.BooleanField(default=False)
    allowed_packages = SpaceDelimitedTextField(blank=True)

    def __str__(self):
        return 'Debian contributor <{email}>'.format(email=self.email)
