# -*- coding: utf-8 -*-

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
from django.utils.safestring import mark_safe
from pts.core.models import PackageBugStats
from pts.core.utils import get_or_none
from pts.core.models import SourcePackageName
from pts.core.panels import BasePanel
from pts.core.panels import LinksPanel
from pts.core.panels import TodosPanel
from pts.core.panels import ProblemsPanel
from pts.core.panels import TemplatePanelItem
from pts.core.panels import HtmlPanelItem
from pts.vendor.debian.models import LintianStats
from pts.vendor.debian.models import PackageExcuses
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


class DebianBugProblems(ProblemsPanel.ItemProvider):
    def get_panel_items(self):
        items = []
        try:
            bug_stats = self.package.bug_stats.stats
        except PackageBugStats.DoesNotExist:
            return []
        # Find the statistics on the help bug category
        help_bug_stats = next((
            category
            for category in bug_stats
            if category['category_name'] == 'help'),
            None
        )
        if help_bug_stats and help_bug_stats['bug_count'] > 0:
            items.append(
                TemplatePanelItem("debian/help-bugs-problem.html", {
                    'bug_stats': help_bug_stats,
                    'url': vendor.call(
                        'get_bug_tracker_url',
                        self.package.name, 'source', 'help')[0],
                })
            )

        return items



class StandardsVersionTodo(TodosPanel.ItemProvider):
    """
    Add a todo item when the standards version of the package is older than the
    current Debian policy version.
    """
    def get_panel_items(self):
        debian_policy = get_or_none(SourcePackageName, name='debian-policy')
        if not debian_policy:
            return []
        policy_version = debian_policy.main_version.version
        # Minor patch level should be disregarded for the comparison
        policy_version, _ = policy_version.rsplit('.', 1)
        standards_version = self.package.main_version.standards_version
        if not standards_version.startswith(policy_version):
            return [
                TemplatePanelItem('debian/standards-version-todo.html', {
                    'lastsv': policy_version,
                    'standards_version': self.package.main_version.standards_version,
                })
            ]
        else:
            return []


class StandardsVersionProblem(ProblemsPanel.ItemProvider):
    """
    Add a todo item when the major version number of the package's standards
    version is older than the major version number of the current Debian
    policy.
    """
    def get_panel_items(self):
        debian_policy = get_or_none(SourcePackageName, name='debian-policy')
        if not debian_policy:
            return []
        policy_version = debian_policy.main_version.version
        major_policy_version_number, _ = policy_version.split('.', 1)

        standards_version = self.package.main_version.standards_version
        if not standards_version.startswith(major_policy_version_number):
            return [
                HtmlPanelItem(
                    "The package is severely out of date with respect to the "
                    "Debian Policy. Latest version is {lastsv} and your "
                    "package only follows {standards_version}...".format(
                        lastsv=policy_version, standards_version=standards_version))
            ]

        return []


class LintianLink(LinksPanel.ItemProvider):
    """
    If there are any known lintian issues for the package, provides a link to
    the lintian page.
    """
    def get_panel_items(self):
        try:
            lintian_stats = self.package.lintian_stats
        except LintianStats.DoesNotExist:
            return []

        if sum(lintian_stats.stats.values()):
            warnings, errors = (
                lintian_stats.stats.get('warnings', 0),
                lintian_stats.stats.get('errors', 0))
            has_errors_or_warnings = warnings or errors
            # Get the full URL only if the package does not have any errors or
            # warnings
            url = lintian_stats.get_lintian_url(full=not has_errors_or_warnings)
            return [
                TemplatePanelItem('debian/lintian-link.html', {
                    'lintian_stats': lintian_stats.stats,
                    'lintian_url': url,
                })
            ]

        return []


class TransitionsPanel(BasePanel):
    template_name = 'debian/transitions-panel.html'
    position = 'center'
    title = 'testing migrations'

    @property
    def context(self):
        try:
            excuses = self.package.excuses.excuses
        except PackageExcuses.DoesNotExist:
            excuses = None
        if excuses:
            excuses = [mark_safe(excuse) for excuse in excuses]
        return {
            'transitions': self.package.package_transitions.all(),
            'excuses': excuses,
            'package_name': self.package.name,
        }
