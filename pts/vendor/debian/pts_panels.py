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
from pts.core.models import PackageBugStats
from pts.core.panels import TodosPanel
from pts.core.panels import TemplatePanelItem
from pts import vendor


class DebianBugTodos(TodosPanel.ItemProvider):
    def get_panel_items(self):
        items = []
        try:
            bug_stats = self.package.bug_stats.stats
        except PackageBugStats.DoesNotExist:
            return []
        # Find the statistics on the patch bug category
        patch_bug_stats = next((
            category
            for category in bug_stats
            if category['category_name'] == 'patch'),
            None
        )
        if patch_bug_stats and patch_bug_stats['bug_count'] > 0:
            items.append(
                TemplatePanelItem("debian/patch-bugs-todo.html", {
                    'bug_stats': patch_bug_stats,
                    'url': vendor.call(
                        'get_bug_tracker_url',
                        self.package.name, 'source', 'patch')[0],
                    'merged_url': vendor.call(
                        'get_bug_tracker_url',
                        self.package.name, 'source', 'patch-merged')[0],
                })
            )

        return items
