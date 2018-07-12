# -*- coding: utf-8 -*-

# Copyright 2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from django.db.models import Prefetch
from distro_tracker.core.models import (
    PackageData,
)
from distro_tracker.core.package_tables import (
    BaseTableField,
)


class UpstreamTableField(BaseTableField):
    """
    This table field displays information regarding the upstream version.
    It displays the package's upstream version with a link to the source code
    """
    column_name = 'Upstream'
    template_name = 'debian/package-table-fields/upstream.html'
    prefetch_related_lookups = [
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='general'),
            to_attr='general_data'
        ),
    ]

    def context(self, package):
        try:
            info = package.general_data[0]
            if 'upstream' in info.value:
                return info.value['upstream']
        except IndexError:
            # There is no general info for the package
            return
