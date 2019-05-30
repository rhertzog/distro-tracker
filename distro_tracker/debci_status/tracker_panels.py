# -*- coding: utf-8 -*-

# Copyright 2013-2019 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Debci specific panel on the package page."""

from distro_tracker.core.models import PackageData

from distro_tracker.core.panels import LinksPanel


class DebciLink(LinksPanel.ItemProvider):
    """
    If there are any debci report for the package, provides a link to the
    debci page.
    """
    def get_panel_items(self):
        try:
            debci_data = self.package.data.get(key='debci')
        except PackageData.DoesNotExist:
            return []

        return [LinksPanel.SimpleLinkItem('debci', debci_data.value['url'])]
