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
from pts import vendor
from pts.core.models import PseudoPackage


def get_pseudo_package_list():
    pseudo_packages, implemented = vendor.call('get_pseudo_package_list')

    if not implemented:
        return

    # Drop the old pseudo package information since it could contain pseudo
    # packages which are no longer valid
    PseudoPackage.objects.all().delete()
    for package_name in pseudo_packages:
        PseudoPackage.objects.create(name=package_name)
