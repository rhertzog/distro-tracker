# Copyright 2013-2019 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Add debci-specific fields to the package tables shown on team pages."""

from django.db.models import Prefetch

from distro_tracker.core.models import (
    PackageData,
)
from distro_tracker.core.package_tables import (
    BaseTableField,
)


class DebciTableField(BaseTableField):
    """
    This table field displays information regarding the Debci status for
    this package.

    It displays the package's Debci status
    """
    column_name = 'Tests'
    slug = 'debci'
    template_name = 'debci_status/debci.html'
    prefetch_related_lookups = [
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='debci'),
            to_attr='debci'
        )
    ]

    def context(self, package):
        ctx = {}

        try:
            debci = package.debci[0].value
            ctx['status'] = debci['result']['status']
            ctx['url'] = debci['url']
            if ctx['status'] == 'pass':
                ctx['label_type'] = 'success'
            else:
                ctx['label_type'] = 'danger'
        except IndexError:
            # There is no debci info for the package
            ctx['url'] = None

        return ctx
