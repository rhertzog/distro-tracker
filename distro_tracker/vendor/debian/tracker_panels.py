# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.


from django.urls import reverse
from django.utils.encoding import force_text
from django.utils.functional import cached_property
from django.utils.http import urlencode, urlquote, urlquote_plus
from django.utils.safestring import mark_safe

from distro_tracker.core.utils import get_or_none
from distro_tracker.core.models import Repository
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import PackageExtractedInfo
from distro_tracker.core.panels import BasePanel
from distro_tracker.core.panels import LinksPanel
from distro_tracker.core.panels import HtmlPanelItem
from distro_tracker.core.panels import TemplatePanelItem
from distro_tracker.vendor.debian.models import LintianStats
from distro_tracker.vendor.debian.models import PackageExcuses
from distro_tracker.vendor.debian.models import UbuntuPackage


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


class BuildLogCheckLinks(LinksPanel.ItemProvider):
    def get_panel_items(self):
        if not isinstance(self.package, SourcePackageName):
            # Only source packages can have build log check info
            return

        has_experimental = False
        experimental_repo = get_or_none(Repository, name='experimental')
        if experimental_repo:
            has_experimental = experimental_repo.has_source_package_name(
                self.package.name)

        query_string = urlencode({'p': self.package.name})
        try:
            self.package.build_logcheck_stats
            has_checks = True
        except:
            has_checks = False
        logcheck_url = \
            "https://qa.debian.org/bls/packages/{hash}/{pkg}.html".format(
                hash=urlquote(self.package.name[0], safe=""),
                pkg=urlquote(self.package.name, safe=""))
        try:
            infos = self.package.packageextractedinfo_set.get(
                key='reproducibility')
            has_reproducibility = True
            reproducibility_status = infos.value['reproducibility']
        except PackageExtractedInfo.DoesNotExist:
            has_reproducibility = False
            reproducibility_status = None
        reproducibility_url = \
            "https://tests.reproducible-builds.org/debian/rb-pkg/{}.html"
        reproducibility_url = reproducibility_url.format(
            urlquote(self.package.name, safe=""))

        return [
            TemplatePanelItem('debian/logcheck-links.html', {
                'package_query_string': query_string,
                'has_checks': has_checks,
                'logcheck_url': logcheck_url,
                'has_reproducibility': has_reproducibility,
                'reproducibility_url': reproducibility_url,
                'reproducibility_status': reproducibility_status,
                'has_experimental': has_experimental,
            })
        ]


class PopconLink(LinksPanel.ItemProvider):
    POPCON_URL = 'https://qa.debian.org/popcon.php?package={package}'

    def get_panel_items(self):
        if not isinstance(self.package, SourcePackageName):
            return

        return [
            LinksPanel.SimpleLinkItem(
                'popcon',
                self.POPCON_URL.format(
                    package=urlquote_plus(self.package.name)))
        ]


class SourceCodeSearchLinks(LinksPanel.ItemProvider):
    """
    Add links to sources.debian.org source code browser and the
    codesearch.debian.net code search (if the package is found in unstable).
    """
    #: A list of repositories that cause the sources.debian.org link to be
    #: displayed if the package is found in one of them.
    ALLOWED_REPOSITORIES = (
        'unstable',
        'experimental',
        'testing',
        'stable',
        'oldstable',
    )
    SOURCES_URL_TEMPLATE = 'https://sources.debian.org/src/{package}/{suite}/'
    SEARCH_FORM_TEMPLATE = (
        '<form class="code-search-form"'
        ' action="' + reverse('dtracker-code-search') + '"'
        ' method="get" target="_blank">'
        '<input type="hidden" name="package" value="{package}">'
        '<input type="search" name="query" placeholder="search source code">'
        '</form>')

    def get_panel_items(self):
        if not isinstance(self.package, SourcePackageName):
            # Only source packages can have these links
            return

        repositories = [repo.suite for repo in self.package.repositories] + \
            [repo.codename for repo in self.package.repositories]
        links = []
        for allowed_repo in self.ALLOWED_REPOSITORIES:
            if allowed_repo in repositories:
                links.append(LinksPanel.SimpleLinkItem(
                    'browse source code',
                    self.SOURCES_URL_TEMPLATE.format(
                        package=urlquote(self.package.name, safe=""),
                        suite=urlquote(allowed_repo, safe=""))))
                break

        if 'unstable' in repositories:
            # Add a search form
            links.append(HtmlPanelItem(self.SEARCH_FORM_TEMPLATE.format(
                package=self.package.name)))

        return links


class DebtagsLink(LinksPanel.ItemProvider):
    """
    Add a link to debtags editor.
    """
    SOURCES_URL_TEMPLATE = \
        'https://debtags.debian.org/rep/todo/maint/{maint}#{package}'

    def get_panel_items(self):
        if not isinstance(self.package, SourcePackageName):
            return
        try:
            infos = self.package.packageextractedinfo_set.get(key='general')
        except PackageExtractedInfo.DoesNotExist:
            return
        maintainer = infos.value['maintainer']['email']
        return [
            LinksPanel.SimpleLinkItem(
                'edit tags',
                self.SOURCES_URL_TEMPLATE.format(
                    package=urlquote(self.package.name, safe=""),
                    maint=urlquote(maintainer, safe=""))
            )
        ]


class SecurityTrackerLink(LinksPanel.ItemProvider):
    """
    Add a link to the security tracker.
    """
    URL_TEMPLATE = \
        'https://security-tracker.debian.org/tracker/source-package/{package}'

    def get_panel_items(self):
        if self.package.packageextractedinfo_set.filter(
                key='debian-security').count() == 0:
            return
        return [
            LinksPanel.SimpleLinkItem(
                'security tracker',
                self.URL_TEMPLATE.format(package=self.package.name)
            )
        ]


class ScreenshotsLink(LinksPanel.ItemProvider):
    """
    Add a link to screenshots.debian.net
    """
    SOURCES_URL_TEMPLATE = \
        'https://screenshots.debian.net/package/{package}'

    def get_panel_items(self):
        if not isinstance(self.package, SourcePackageName):
            return
        try:
            infos = self.package.packageextractedinfo_set.get(key='screenshots')
        except PackageExtractedInfo.DoesNotExist:
            return
        if infos.value['screenshots'] == 'true':
            return [
                LinksPanel.SimpleLinkItem(
                    'screenshots',
                    self.SOURCES_URL_TEMPLATE.format(
                        package=urlquote(self.package.name, safe=""))
                )
            ]
        else:
            return


class TransitionsPanel(BasePanel):
    template_name = 'debian/transitions-panel.html'
    panel_importance = 2
    position = 'center'
    title = 'testing migrations'

    @cached_property
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

    @property
    def has_content(self):
        return bool(self.context['transitions']) or \
            bool(self.context['excuses'])


class UbuntuPanel(BasePanel):
    template_name = 'debian/ubuntu-panel.html'
    position = 'right'
    title = 'ubuntu'

    @cached_property
    def context(self):
        try:
            ubuntu_package = self.package.ubuntu_package
        except UbuntuPackage.DoesNotExist:
            return

        return {
            'ubuntu_package': ubuntu_package,
        }

    @property
    def has_content(self):
        return bool(self.context)


class BackToOldPTS(BasePanel):
    """
    Display a message to users of the old PTS to encourage them to file bugs
    about issues that they discover and also to offer them a link back to the
    old PTS in case they need it.
    """
    template_name = 'debian/back-to-old-pts.html'
    position = 'center'
    title = 'About the new package tracker'
    panel_importance = 100

    @cached_property
    def context(self):
        return {
            'package': self.package.name
        }

    @property
    def has_content(self):
        return "packages.qa.debian.org" in \
            force_text(self.request.META.get('HTTP_REFERER', ''),
                       encoding='latin1', errors='replace')
