# Copyright 2013-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Debian-specific tasks.
"""

import collections
import io
import itertools
import json
import logging
import os
import re
from enum import Enum

import debianbts
import yaml
from bs4 import BeautifulSoup as soup
from debian import deb822, debian_support
from debian.debian_support import AptPkgVersion
from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils.http import urlencode

from distro_tracker import vendor
from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
    BinaryPackageBugStats,
    BinaryPackageName,
    BugDisplayManagerMixin,
    PackageBugStats,
    PackageData,
    PackageName,
    Repository,
    SourcePackageDeps,
    SourcePackageName
)
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.mixins import PackageTagging
from distro_tracker.core.tasks.schedulers import IntervalScheduler
from distro_tracker.core.utils.http import (
    HttpCache,
    get_resource_content,
    get_resource_text
)
from distro_tracker.core.utils.misc import get_data_checksum
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils.packages import (
    html_package_list,
    package_hashdir,
    package_url
)
from distro_tracker.vendor.debian.models import (
    BuildLogCheckStats,
    LintianStats,
    PackageExcuses,
    PackageTransition,
    UbuntuPackage
)

from .models import DebianContributor

logger = logging.getLogger(__name__)


class RetrieveDebianMaintainersTask(BaseTask):
    """
    Retrieves (and updates if necessary) a list of Debian Maintainers.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 24

    def execute_main(self):
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        url = "https://ftp-master.debian.org/dm.txt"
        if not self.force_update and not cache.is_expired(url):
            # No need to do anything when the previously cached value is fresh
            return
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            # No need to do anything if the cached item was still not updated
            return

        maintainers = {}
        lines = response.iter_lines(decode_unicode=True)
        for stanza in deb822.Deb822.iter_paragraphs(lines):
            if 'Uid' in stanza and 'Allow' in stanza:
                # Allow is a comma-separated string of 'package (DD fpr)' items,
                # where DD fpr is the fingerprint of the DD that granted the
                # permission
                name, email = stanza['Uid'].rsplit(' ', 1)
                email = email.strip('<>')
                for pair in stanza['Allow'].split(','):
                    pair = pair.strip()
                    pkg, dd_fpr = pair.split()
                    maintainers.setdefault(email, [])
                    maintainers[email].append(pkg)

        # Now update the developer information
        with transaction.atomic():
            # Reset all old maintainers first.
            qs = DebianContributor.objects.filter(is_debian_maintainer=True)
            qs.update(is_debian_maintainer=False)

            for email, packages in maintainers.items():
                email, _ = UserEmail.objects.get_or_create(email=email)
                contributor, _ = DebianContributor.objects.get_or_create(
                    email=email)

                contributor.is_debian_maintainer = True
                contributor.allowed_packages = packages
                contributor.save()


class RetrieveLowThresholdNmuTask(BaseTask):
    """
    Updates the list of Debian Maintainers which agree with the lowthreshold
    NMU.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 24

    def _retrieve_emails(self):
        """
        Helper function which obtains the list of emails of maintainers that
        agree with the lowthreshold NMU.
        """
        url = 'https://wiki.debian.org/LowThresholdNmu?action=raw'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        if not self.force_update and not cache.is_expired(url):
            return
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return

        emails = []
        devel_php_RE = re.compile(
            r'https?://qa\.debian\.org/developer\.php\?login=([^\s&|]+)')
        word_RE = re.compile(r'^\w+$')
        for line in response.iter_lines(decode_unicode=True):
            match = devel_php_RE.search(line)
            while match:    # look for several matches on the same line
                email = None
                login = match.group(1)
                if word_RE.match(login):
                    email = login + '@debian.org'
                elif login.find('@') >= 0:
                    email = login
                if email:
                    emails.append(email)
                line = line[match.end():]
                match = devel_php_RE.search(line)
        return emails

    def execute_main(self):
        emails = self._retrieve_emails()
        with transaction.atomic():
            # Reset all threshold flags first.
            qs = DebianContributor.objects.filter(
                agree_with_low_threshold_nmu=True)
            qs.update(agree_with_low_threshold_nmu=False)
            for email in emails:
                email, _ = UserEmail.objects.get_or_create(email=email)
                contributor, _ = DebianContributor.objects.get_or_create(
                    email=email)

                contributor.agree_with_low_threshold_nmu = True
                contributor.save()


class UpdatePackageBugStats(BaseTask, BugDisplayManagerMixin):
    """
    Updates the BTS bug stats for all packages (source, binary and pseudo).
    Creates :class:`distro_tracker.core.ActionItem` instances for packages
    which have bugs tagged help or patch.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    PATCH_BUG_ACTION_ITEM_TYPE_NAME = 'debian-patch-bugs-warning'
    HELP_BUG_ACTION_ITEM_TYPE_NAME = 'debian-help-bugs-warning'

    PATCH_ITEM_SHORT_DESCRIPTION = (
        '<a href="{url}">{count}</a> tagged patch in the '
        '<abbr title="Bug Tracking System">BTS</abbr>')
    HELP_ITEM_SHORT_DESCRIPTION = (
        '<a href="{url}">{count}</a> tagged help in the '
        '<abbr title="Bug Tracking System">BTS</abbr>')
    PATCH_ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/patch-bugs-action-item.html'
    HELP_ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/help-bugs-action-item.html'

    bug_categories = (
        'rc',
        'normal',
        'wishlist',
        'fixed',
        'patch',
    )

    def initialize(self, *args, **kwargs):
        super(UpdatePackageBugStats, self).initialize(*args, **kwargs)
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        # The :class:`distro_tracker.core.models.ActionItemType` instances which
        # this task can create.
        self.patch_item_type = ActionItemType.objects.create_or_update(
            type_name=self.PATCH_BUG_ACTION_ITEM_TYPE_NAME,
            full_description_template=self.PATCH_ITEM_FULL_DESCRIPTION_TEMPLATE)
        self.help_item_type = ActionItemType.objects.create_or_update(
            type_name=self.HELP_BUG_ACTION_ITEM_TYPE_NAME,
            full_description_template=self.HELP_ITEM_FULL_DESCRIPTION_TEMPLATE)

    def _get_tagged_bug_stats(self, tag, user=None):
        """
        Using the BTS interface, retrieves the statistics of bugs with a
        particular tag.

        :param tag: The tag for which the statistics are required.
        :type tag: string
        :param user: The email of the user who tagged the bug with the given
            tag.
        :type user: string

        :returns: A dict mapping package names to the count of bugs with the
            given tag.
        """
        debian_ca_bundle = '/etc/ssl/ca-debian/ca-certificates.crt'
        if os.path.exists(debian_ca_bundle):
            os.environ['SSL_CERT_FILE'] = debian_ca_bundle
        if user:
            bug_numbers = debianbts.get_usertag(user, tag).values()
        else:
            bug_numbers = debianbts.get_bugs('tag', tag)

        # Match each retrieved bug ID to a package and then find the aggregate
        # count for each package.
        bug_stats = {}
        bugs = debianbts.get_status(*bug_numbers)
        for bug in bugs:
            if bug.done or bug.fixed_versions or bug.pending == 'done':
                continue

            bug_stats.setdefault(bug.package, 0)
            bug_stats[bug.package] += 1

        return bug_stats

    def _extend_bug_stats(self, bug_stats, extra_stats, category_name):
        """
        Helper method which adds extra bug stats to an already existing list of
        stats.

        :param bug_stats: An already existing list of bug stats. Maps package
            names to list of bug category descriptions.
        :type bug_stats: dict
        :param extra_stats: Extra bug stats which should be added to
            ``bug_stats``. Maps package names to integers representing bug
            counts.
        :type extra_stats: dict
        :param category_name: The name of the bug category which is being added
        :type category_name: string
        """
        for package, count in extra_stats.items():
            bug_stats.setdefault(package, [])
            bug_stats[package].append({
                'category_name': category_name,
                'bug_count': count,
            })

    def _create_patch_bug_action_item(self, package, bug_stats):
        """
        Creates a :class:`distro_tracker.core.models.ActionItem` instance for
        the given package if it contains any bugs tagged patch.

        :param package: The package for which the action item should be
            updated.
        :type package: :class:`distro_tracker.core.models.PackageName`
        :param bug_stats: A dictionary mapping category names to structures
            describing those categories. Those structures should be
            identical to the ones stored in the :class:`PackageBugStats`
            instance.
        :type bug_stats: dict
        """
        # Get the old action item, if any
        action_item = package.get_action_item_for_type(
            self.PATCH_BUG_ACTION_ITEM_TYPE_NAME)

        if 'patch' not in bug_stats or bug_stats['patch']['bug_count'] == 0:
            # Remove the old action item, since the package does not have any
            # bugs tagged patch anymore.
            if action_item is not None:
                action_item.delete()
            return

        # If the package has bugs tagged patch, update the action item
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.patch_item_type)

        bug_count = bug_stats['patch']['bug_count']
        # Include the URL in the short description
        url = self.bug_manager.get_bug_tracker_url(
            package.name, 'source', 'patch')
        if not url:
            url = ''
        # Include the bug count in the short description
        count = '{bug_count} bug'.format(bug_count=bug_count)
        if bug_count > 1:
            count += 's'
        action_item.short_description = \
            self.PATCH_ITEM_SHORT_DESCRIPTION.format(url=url, count=count)
        # Set additional URLs and merged bug count in the extra data for a full
        # description
        action_item.extra_data = {
            'bug_count': bug_count,
            'merged_count': bug_stats['patch'].get('merged_count', 0),
            'url': url,
            'merged_url': self.bug_manager.get_bug_tracker_url(
                package.name, 'source', 'patch-merged'),
        }
        action_item.save()

    def _create_help_bug_action_item(self, package, bug_stats):
        """
        Creates a :class:`distro_tracker.core.models.ActionItem` instance for
        the given package if it contains any bugs tagged help.

        :param package: The package for which the action item should be
            updated.
        :type package: :class:`distro_tracker.core.models.PackageName`
        :param bug_stats: A dictionary mapping category names to structures
            describing those categories. Those structures should be
            identical to the ones stored in the :class:`PackageBugStats`
            instance.
        :type bug_stats: dict
        """
        # Get the old action item, if any
        action_item = package.get_action_item_for_type(
            self.HELP_BUG_ACTION_ITEM_TYPE_NAME)

        if 'help' not in bug_stats or bug_stats['help']['bug_count'] == 0:
            # Remove the old action item, since the package does not have any
            # bugs tagged patch anymore.
            if action_item is not None:
                action_item.delete()
            return

        # If the package has bugs tagged patch, update the action item
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.help_item_type)

        bug_count = bug_stats['help']['bug_count']
        # Include the URL in the short description
        url, _ = vendor.call('get_bug_tracker_url', package.name, 'source',
                             'help')
        if not url:
            url = ''
        # Include the bug count in the short description
        count = '{bug_count} bug'.format(bug_count=bug_count)
        if bug_count > 1:
            count += 's'
        action_item.short_description = self.HELP_ITEM_SHORT_DESCRIPTION.format(
            url=url, count=count)
        # Set additional URLs and merged bug count in the extra data for a full
        # description
        action_item.extra_data = {
            'bug_count': bug_count,
            'url': url,
        }
        action_item.save()

    def _create_action_items(self, package_bug_stats):
        """
        Method which creates a :class:`distro_tracker.core.models.ActionItem`
        instance for a package based on the given package stats.

        For now, an action item is created if the package either has bugs
        tagged as help or patch.
        """
        # Transform the bug stats to a structure easier to pass to functions
        # for particular bug-category action items.
        bug_stats = {
            category['category_name']: category
            for category in package_bug_stats.stats
        }
        package = package_bug_stats.package
        self._create_patch_bug_action_item(package, bug_stats)
        self._create_help_bug_action_item(package, bug_stats)

    def _get_udd_bug_stats(self):
        url = 'https://udd.debian.org/cgi-bin/ddpo-bugs.cgi'
        response_content = get_resource_content(url)
        if not response_content:
            return

        # Each line in the response should be bug stats for a single package
        bug_stats = {}
        for line in response_content.splitlines():
            line = line.decode('utf-8', 'ignore').strip()
            try:
                package_name, bug_counts = line, ''
                if line.startswith('src:'):
                    src, package_name, bug_counts = line.split(':', 2)
                else:
                    package_name, bug_counts = line.split(':', 1)
                # Merged counts are in parentheses so remove those before
                # splitting the numbers
                bug_counts = re.sub(r'[()]', ' ', bug_counts).split()
                bug_counts = [int(count) for count in bug_counts]
            except ValueError:
                logger.warning(
                    'Failed to parse bug information for %s: %s',
                    package_name, bug_counts, exc_info=1)
                continue

            # Match the extracted counts with category names
            bug_stats[package_name] = [
                {
                    'category_name': category_name,
                    'bug_count': bug_count,
                    'merged_count': merged_count,
                }
                for category_name, (bug_count, merged_count) in zip(
                    self.bug_categories, zip(bug_counts[::2], bug_counts[1::2]))
            ]

        return bug_stats

    def _remove_obsolete_action_items(self, package_names):
        """
        Removes action items for packages which no longer have any bug stats.
        """
        ActionItem.objects.delete_obsolete_items(
            item_types=[self.patch_item_type, self.help_item_type],
            non_obsolete_packages=package_names)

    def update_source_and_pseudo_bugs(self):
        """
        Performs the update of bug statistics for source and pseudo packages.
        """
        # First get the bug stats exposed by the UDD.
        bug_stats = self._get_udd_bug_stats()
        if not bug_stats:
            bug_stats = {}

        # Add in help bugs from the BTS interface
        try:
            help_bugs = self._get_tagged_bug_stats('help')
            self._extend_bug_stats(bug_stats, help_bugs, 'help')
        except RuntimeError:
            logger.exception("Could not get bugs tagged help")

        # Add in newcomer bugs from the BTS interface
        try:
            newcomer_bugs = self._get_tagged_bug_stats('newcomer')
            self._extend_bug_stats(bug_stats, newcomer_bugs, 'newcomer')
        except RuntimeError:
            logger.exception("Could not get bugs tagged newcomer")

        with transaction.atomic():
            # Clear previous stats
            PackageBugStats.objects.all().delete()
            self._remove_obsolete_action_items(bug_stats.keys())
            # Get all packages which have updated stats, along with their
            # action items in 2 DB queries.
            packages = PackageName.objects.filter(name__in=bug_stats.keys())
            packages.prefetch_related('action_items')

            # Update stats and action items.
            stats = []
            for package in packages:
                # Save the raw package bug stats
                package_bug_stats = PackageBugStats(
                    package=package, stats=bug_stats[package.name])
                stats.append(package_bug_stats)

                # Add action items for the package.
                self._create_action_items(package_bug_stats)

            PackageBugStats.objects.bulk_create(stats)

    def update_binary_bugs(self):
        """
        Performs the update of bug statistics for binary packages.
        """
        url = 'https://udd.debian.org/cgi-bin/bugs-binpkgs-distro_tracker.cgi'
        response_content = get_resource_content(url)
        if not response_content:
            return

        # Extract known binary package bug stats: each line is a separate pkg
        bug_stats = {}
        for line in response_content.splitlines():
            line = line.decode('utf-8')
            package_name, bug_counts = line.split(None, 1)
            bug_counts = bug_counts.split()
            try:
                bug_counts = [int(count) for count in bug_counts]
            except ValueError:
                logger.exception(
                    'Failed to parse bug information for %s: %s',
                    package_name, bug_counts)
                continue

            bug_stats[package_name] = [
                {
                    'category_name': category_name,
                    'bug_count': bug_count,
                }
                for category_name, bug_count in zip(
                    self.bug_categories, bug_counts)
            ]

        with transaction.atomic():
            # Clear previous stats
            BinaryPackageBugStats.objects.all().delete()
            packages = \
                BinaryPackageName.objects.filter(name__in=bug_stats.keys())
            # Create new stats in a single query
            stats = [
                BinaryPackageBugStats(package=package,
                                      stats=bug_stats[package.name])
                for package in packages
            ]
            BinaryPackageBugStats.objects.bulk_create(stats)

    def execute_main(self):
        # Stats for source and pseudo packages is retrieved from a different
        # resource (with a different structure) than stats for binary packages.
        self.update_source_and_pseudo_bugs()
        self.update_binary_bugs()


class UpdateLintianStatsTask(BaseTask):
    """
    Updates packages' lintian stats.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    ACTION_ITEM_TYPE_NAME = 'lintian-warnings-and-errors'
    ITEM_DESCRIPTION = 'lintian reports <a href="{url}">{report}</a>'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/lintian-action-item.html'

    def initialize(self, *args, **kwargs):
        super(UpdateLintianStatsTask, self).initialize(*args, **kwargs)
        self.lintian_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def get_lintian_stats(self):
        url = 'https://lintian.debian.org/qa-list.txt'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return

        all_stats = {}
        categories = (
            'errors',
            'warnings',
            'pedantics',
            'experimentals',
            'overriddens',
        )
        for line in response.iter_lines(decode_unicode=True):
            package, stats = line.split(None, 1)
            stats = stats.split()
            try:
                all_stats[package] = {
                    category: int(count)
                    for count, category in zip(stats, categories)
                }
            except ValueError:
                logger.exception(
                    'Failed to parse lintian information for %s: %s',
                    package, line)
                continue

        return all_stats

    def update_action_item(self, package, lintian_stats):
        """
        Updates the :class:`ActionItem` for the given package based on the
        :class:`LintianStats <distro_tracker.vendor.debian.models.LintianStats`
        given in ``package_stats``. If the package has errors or warnings an
        :class:`ActionItem` is created.
        """
        package_stats = lintian_stats.stats
        warnings, errors = (
            package_stats.get('warnings'), package_stats.get('errors', 0))
        # Get the old action item for this warning, if it exists.
        lintian_action_item = package.get_action_item_for_type(
            self.lintian_action_item_type.type_name)
        if not warnings and not errors:
            if lintian_action_item:
                # If the item previously existed, delete it now since there
                # are no longer any warnings/errors.
                lintian_action_item.delete()
            return

        # The item didn't previously have an action item: create it now
        if lintian_action_item is None:
            lintian_action_item = ActionItem(
                package=package,
                item_type=self.lintian_action_item_type)

        lintian_url = lintian_stats.get_lintian_url()
        new_extra_data = {
            'warnings': warnings,
            'errors': errors,
            'lintian_url': lintian_url,
        }
        if lintian_action_item.extra_data:
            old_extra_data = lintian_action_item.extra_data
            if (old_extra_data['warnings'] == warnings and
                    old_extra_data['errors'] == errors):
                # No need to update
                return

        lintian_action_item.extra_data = new_extra_data

        if errors and warnings:
            report = '{} error{} and {} warning{}'.format(
                errors,
                's' if errors > 1 else '',
                warnings,
                's' if warnings > 1 else '')
        elif errors:
            report = '{} error{}'.format(
                errors,
                's' if errors > 1 else '')
        elif warnings:
            report = '{} warning{}'.format(
                warnings,
                's' if warnings > 1 else '')

        lintian_action_item.short_description = self.ITEM_DESCRIPTION.format(
            url=lintian_url,
            report=report)

        # If there are errors make the item a high severity issue
        if errors:
            lintian_action_item.severity = ActionItem.SEVERITY_HIGH

        lintian_action_item.save()

    def execute_main(self):
        all_lintian_stats = self.get_lintian_stats()
        if not all_lintian_stats:
            return

        # Discard all old stats
        LintianStats.objects.all().delete()

        packages = PackageName.objects.filter(name__in=all_lintian_stats.keys())
        packages.prefetch_related('action_items')
        # Remove action items for packages which no longer have associated
        # lintian data.
        ActionItem.objects.delete_obsolete_items(
            [self.lintian_action_item_type], all_lintian_stats.keys())

        stats = []
        for package in packages:
            package_stats = all_lintian_stats[package.name]
            # Save the raw lintian stats.
            lintian_stats = LintianStats(package=package, stats=package_stats)
            stats.append(lintian_stats)
            # Create an ActionItem if there are errors or warnings
            self.update_action_item(package, lintian_stats)

        LintianStats.objects.bulk_create(stats)


class UpdateAppStreamStatsTask(BaseTask):
    """
    Updates packages' AppStream issue hints data.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 6

    ACTION_ITEM_TYPE_NAME = 'appstream-issue-hints'
    ITEM_DESCRIPTION = 'AppStream hints: {report}'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/appstream-action-item.html'

    def initialize(self, *args, **kwargs):
        super(UpdateAppStreamStatsTask, self).initialize(*args, **kwargs)
        self.appstream_action_item_type = \
            ActionItemType.objects.create_or_update(
                type_name=self.ACTION_ITEM_TYPE_NAME,
                full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)
        self._tag_severities = {}

    def _load_tag_severities(self):
        url = 'https://appstream.debian.org/hints/asgen-hints.json'
        json_data = get_resource_text(url, force_update=True)

        data = json.loads(json_data)
        for tag, info in data.items():
            self._tag_severities[tag] = info['severity']

    def _load_appstream_hint_stats(self, section, arch, all_stats={}):
        url = 'https://appstream.debian.org/hints/sid/{}/Hints-{}.json.gz' \
              .format(section, arch)
        hints_json = get_resource_text(url, force_update=self.force_update)

        hints = json.loads(hints_json)
        for hint in hints:
            pkid = hint['package']
            parts = pkid.split('/')
            package_name = parts[0]

            # get the source package for this binary package name
            src_pkgname = None
            if SourcePackageName.objects.exists_with_name(package_name):
                package = SourcePackageName.objects.get(name=package_name)
                src_pkgname = package.name
            elif BinaryPackageName.objects.exists_with_name(package_name):
                bin_package = BinaryPackageName.objects.get(name=package_name)
                package = bin_package.main_source_package_name
                src_pkgname = package.name
            else:
                src_pkgname = package_name

            if src_pkgname not in all_stats:
                all_stats[src_pkgname] = {}
            if package_name not in all_stats[src_pkgname]:
                all_stats[src_pkgname][package_name] = {}

            for cid, h in hint['hints'].items():
                for e in h:
                    severity = self._tag_severities[e['tag']]
                    sevkey = "errors"
                    if severity == "warning":
                        sevkey = "warnings"
                    elif severity == "info":
                        sevkey = "infos"
                    if sevkey not in all_stats[src_pkgname][package_name]:
                        all_stats[src_pkgname][package_name][sevkey] = 1
                    else:
                        all_stats[src_pkgname][package_name][sevkey] += 1

        return all_stats

    def _get_appstream_url(self, package, bin_pkgname):
        """
        Returns the AppStream URL for the given PackageName in :package.
        """

        src_package = get_or_none(SourcePackageName, pk=package.pk)
        if not src_package:
            return '#'

        if not src_package.main_version:
            return '#'

        component = 'main'
        main_entry = src_package.main_entry
        if main_entry:
            component = main_entry.component
            if not component:
                component = 'main'

        return (
            'https://appstream.debian.org/sid/{}/issues/{}.html'
            .format(component, bin_pkgname)
        )

    def _create_final_stats_report(self, package, package_stats):
        """
        Returns a transformed statistics report to be stored in the database.
        """

        as_report = package_stats.copy()
        for bin_package in list(as_report.keys()):
            # we currently don't want to display info-type hints
            as_report[bin_package].pop('infos', None)
            if as_report[bin_package]:
                as_report[bin_package]['url'] = \
                    self._get_appstream_url(package, bin_package)
            else:
                as_report.pop(bin_package)
        return as_report

    def update_action_item(self, package, package_stats):
        """
        Updates the :class:`ActionItem` for the given package based on the
        AppStream hint statistics given in ``package_stats``.
        If the package has errors or warnings an
        :class:`ActionItem` is created.
        """

        total_warnings = 0
        total_errors = 0
        for bin_pkgname, info in package_stats.items():
            total_warnings += info.get('warnings', 0)
            total_errors += info.get('errors', 0)

        # Get the old action item for this warning, if it exists.
        appstream_action_item = package.get_action_item_for_type(
            self.appstream_action_item_type.type_name)
        if not total_warnings and not total_errors:
            if appstream_action_item:
                # If the item previously existed, delete it now since there
                # are no longer any warnings/errors.
                appstream_action_item.delete()
            return

        # The item didn't previously have an action item: create it now
        if appstream_action_item is None:
            appstream_action_item = ActionItem(
                package=package,
                item_type=self.appstream_action_item_type)

        as_report = self._create_final_stats_report(package, package_stats)

        if appstream_action_item.extra_data:
            old_extra_data = appstream_action_item.extra_data
            if old_extra_data == as_report:
                # No need to update
                return

        appstream_action_item.extra_data = as_report

        if total_errors and total_warnings:
            short_report = '{} error{} and {} warning{}'.format(
                total_errors,
                's' if total_errors > 1 else '',
                total_warnings,
                's' if total_warnings > 1 else '')
        elif total_errors:
            short_report = '{} error{}'.format(
                total_errors,
                's' if total_errors > 1 else '')
        elif total_warnings:
            short_report = '{} warning{}'.format(
                total_warnings,
                's' if total_warnings > 1 else '')

        appstream_action_item.short_description = \
            self.ITEM_DESCRIPTION.format(report=short_report)

        # If there are errors make the item a high severity issue
        if total_errors:
            appstream_action_item.severity = ActionItem.SEVERITY_HIGH

        appstream_action_item.save()

    def execute_main(self):
        self._load_tag_severities()
        all_stats = {}
        repository = Repository.objects.get(default=True)
        arch = "amd64"
        for component in repository.components:
            self._load_appstream_hint_stats(component, arch, all_stats)
        if not all_stats:
            return

        with transaction.atomic():
            # Delete obsolete data
            PackageData.objects.filter(key='appstream').delete()

            packages = PackageName.objects.filter(name__in=all_stats.keys())
            packages.prefetch_related('action_items')

            stats = []
            for package in packages:
                package_stats = all_stats[package.name]
                stats.append(
                    PackageData(
                        package=package,
                        key='appstream',
                        value=package_stats
                    )
                )

                # Create an ActionItem if there are errors or warnings
                self.update_action_item(package, package_stats)

            PackageData.objects.bulk_create(stats)
            # Remove action items for packages which no longer have associated
            # AppStream hints.
            ActionItem.objects.delete_obsolete_items(
                [self.appstream_action_item_type], all_stats.keys())


class UpdateTransitionsTask(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600

    REJECT_LIST_URL = 'https://ftp-master.debian.org/transitions.yaml'
    PACKAGE_TRANSITION_LIST_URL = (
        'https://release.debian.org/transitions/export/packages.yaml')

    def initialize(self, *args, **kwargs):
        super(UpdateTransitionsTask, self).initialize(*args, **kwargs)
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)

    def _get_yaml_resource(self, url):
        """
        Gets the YAML resource at the given URL and returns it as a Python
        object.
        """
        content = self.cache.get_content(url)
        return yaml.safe_load(io.BytesIO(content))

    def _add_reject_transitions(self, packages):
        """
        Adds the transitions which cause uploads to be rejected to the
        given ``packages`` dict.
        """
        reject_list = self._get_yaml_resource(self.REJECT_LIST_URL)
        for id, transition in reject_list.items():
            for package in transition['packages']:
                packages.setdefault(package, {})
                packages[package].setdefault(id, {})
                packages[package][id]['reject'] = True
                packages[package][id]['status'] = 'ongoing'

    def _add_package_transition_list(self, packages):
        """
        Adds the ongoing and planned transitions to the given ``packages``
        dict.
        """
        package_transition_list = self._get_yaml_resource(
            self.PACKAGE_TRANSITION_LIST_URL)

        wanted_transition_statuses = ('ongoing', 'planned')
        for package_info in package_transition_list:
            package_name = package_info['name']
            for transition_name, status in package_info['list']:
                if status not in wanted_transition_statuses:
                    # Skip transitions with an unwanted status
                    continue

                packages.setdefault(package_name, {})
                packages[package_name].setdefault(transition_name, {})
                packages[package_name][transition_name]['status'] = status

    def execute_main(self):
        # Update the relevant resources first
        _, updated_reject_list = self.cache.update(
            self.REJECT_LIST_URL, force=self.force_update)
        _, updated_package_transition_list = self.cache.update(
            self.PACKAGE_TRANSITION_LIST_URL, force=self.force_update)

        if not updated_reject_list and not updated_package_transition_list:
            # Nothing to do - at least one needs to be updated...
            return

        package_transitions = {}
        self._add_reject_transitions(package_transitions)
        self._add_package_transition_list(package_transitions)

        PackageTransition.objects.all().delete()
        # Get the packages which have transitions
        packages = PackageName.objects.filter(
            name__in=package_transitions.keys())
        transitions = []
        for package in packages:
            for transition_name, data in \
                    package_transitions[package.name].items():
                transitions.append(PackageTransition(
                    package=package,
                    transition_name=transition_name,
                    status=data.get('status', None),
                    reject=data.get('reject', False)))

        PackageTransition.objects.bulk_create(transitions)


class UpdateExcusesTask(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE_NAME = 'debian-testing-migration'
    ITEM_DESCRIPTION = (
        "The package has not entered testing even though the delay is over")
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/testing-migration-action-item.html'

    class AgeVerdict(Enum):
        PKG_OF_AGE = 0
        PKG_TOO_OLD = 1
        PKG_TOO_YOUNG = 2
        PKG_WO_POLICY = 3

    def initialize(self, *args, **kwargs):
        super(UpdateExcusesTask, self).initialize(*args, **kwargs)
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def _adapt_excuse_links(self, excuse):
        """
        If the excuse contains any anchor links, convert them to links to Distro
        Tracker package pages. Return the original text unmodified, otherwise.
        """
        re_anchor_href = re.compile(r'^#(.*)$')
        html = soup(excuse, 'html.parser')
        for a_tag in html.findAll('a', {'href': True}):
            href = a_tag['href']
            match = re_anchor_href.match(href)
            if not match:
                continue
            package = match.group(1)
            a_tag['href'] = package_url(package)

        return str(html)

    def _skip_excuses_item(self, item_text):
        if not item_text:
            return True
        # We ignore these excuses
        if "Section" in item_text or "Maintainer" in item_text:
            return True
        return False

    def _check_age(self, source):
        """Checks the age of the package and compares it to the age requirement
        for migration"""

        if 'policy_info' not in source or 'age' not in source['policy_info']:
            return (self.AgeVerdict.PKG_WO_POLICY, None, None)

        age = source['policy_info']['age']['current-age']
        limit = source['policy_info']['age']['age-requirement']
        if age > limit:
            return (self.AgeVerdict.PKG_TOO_OLD, age, limit)
        elif age < limit:
            return (self.AgeVerdict.PKG_TOO_YOUNG, age, limit)
        else:
            return (self.AgeVerdict.PKG_OF_AGE, age, limit)

    def _extract_problematic(self, source):
        verdict, age, limit = self._check_age(source)

        if verdict == self.AgeVerdict.PKG_TOO_OLD:
            return (source['item-name'], {'age': age, 'limit': limit})

    @staticmethod
    def _make_excuses_check_dependencies(source):
        """Checks the dependencies of the package (blocked-by and
        migrate-after) and returns a list to display."""

        addendum = []

        if 'dependencies' in source:
            blocked_by = source['dependencies'].get('blocked-by', [])
            after = source['dependencies'].get('migrate-after', [])
            after = [
                element
                for element in after
                if element not in blocked_by
            ]
            if blocked_by:
                addendum.append("Blocked by: %s" % (
                    html_package_list(blocked_by),
                ))
            if after:
                addendum.append("Migrates after: %s" % (
                    html_package_list(after),
                ))

        return addendum

    @staticmethod
    def _make_excuses_check_verdict(source):
        """Checks the migration policy verdict of the package and builds an
        excuses message depending on the result."""

        addendum = []

        if 'migration-policy-verdict' in source:
            verdict = source['migration-policy-verdict']
            if verdict == 'REJECTED_BLOCKED_BY_ANOTHER_ITEM':
                addendum.append("Migration status: Blocked. Can't migrate "
                                "due to a non-migratable dependency. Check "
                                "status below."
                                )

        return addendum

    def _make_excuses_check_age(self, source):
        """Checks how old is the package and builds an excuses message
        depending on the result."""

        addendum = []

        verdict, age, limit = self._check_age(source)

        if verdict in [
            self.AgeVerdict.PKG_TOO_OLD,
            self.AgeVerdict.PKG_OF_AGE
        ]:
            addendum.append("%d days old (%d needed)" % (
                age,
                limit,
            ))
        elif verdict == self.AgeVerdict.PKG_TOO_YOUNG:
            addendum.append("Too young, only %d of %d days old" % (
                age,
                limit,
            ))

        return addendum

    def _make_excuses(self, source):
        """Make the excuses list for a source item using the yaml data it
        contains"""

        excuses = [
            self._adapt_excuse_links(excuse)
            for excuse in source['excuses']
        ]

        # This is the place where we compute some additionnal
        # messages that should be added to excuses.
        addendum = []

        addendum.extend(self._make_excuses_check_verdict(source))
        addendum.extend(self._make_excuses_check_dependencies(source))
        addendum.extend(self._make_excuses_check_age(source))

        excuses = addendum + excuses

        if 'is-candidate' in source:
            if not source['is-candidate']:
                excuses.append("Not considered")

        return (
            source['item-name'],
            excuses,
        )

    def _get_excuses_and_problems(self, content):
        """
        Gets the excuses for each package.
        Also finds a list of packages which have not migrated to testing
        agter the necessary time has passed.

        :returns: A two-tuple  where the first element is a dict mapping
        package names to a list of excuses. The second element is a dict
        mapping packages names to a problem information. Problem information
        is a dict with the keys ``age`` and ``limit``.
        """
        if 'sources' not in content:
            logger.warning("Invalid format of excuses file")
            return

        sources = content['sources']
        excuses = [
            self._make_excuses(source)
            for source in sources
            if '/' not in source['item-name']
        ]
        problems = [
            self._extract_problematic(source)
            for source in sources
            if '/' not in source['item-name']
        ]
        problematic = [p for p in problems if p]
        return dict(excuses), dict(problematic)

    def _create_action_item(self, package, extra_data):
        """
        Creates a :class:`distro_tracker.core.models.ActionItem` for the given
        package including the given extra data. The item indicates that there is
        a problem with the package migrating to testing.
        """
        action_item = \
            package.get_action_item_for_type(self.ACTION_ITEM_TYPE_NAME)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)

        action_item.short_description = self.ITEM_DESCRIPTION
        if package.main_entry:
            query_string = urlencode({'package': package.name})
            extra_data['check_why_url'] = (
                'https://qa.debian.org/excuses.php'
                '?{query_string}'.format(query_string=query_string))

        action_item.extra_data = extra_data
        action_item.save()

    def _remove_obsolete_action_items(self, problematic):
        """
        Remove action items for packages which are no longer problematic.
        """
        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=problematic.keys())

    def _get_excuses_yaml(self):
        """
        Function returning the content of excuses from debian-release
        :returns: a dict of excuses or ``None`` if the content in the
        cache is up to date.
        """
        url = 'https://release.debian.org/britney/excuses.yaml'
        response, updated = self.cache.update(url, force=self.force_update)
        if not updated:
            return

        return yaml.load(response.text)

    def execute_main(self):
        content_lines = self._get_excuses_yaml()
        if not content_lines:
            return

        result = self._get_excuses_and_problems(content_lines)
        if not result:
            return
        package_excuses, problematic = result

        # Remove stale excuses data and action items which are not still
        # problematic.
        self._remove_obsolete_action_items(problematic)
        PackageExcuses.objects.all().delete()

        excuses = []
        packages = SourcePackageName.objects.filter(
            name__in=package_excuses.keys())
        packages.prefetch_related('action_items')
        for package in packages:
            excuse = PackageExcuses(
                package=package,
                excuses=package_excuses[package.name])
            excuses.append(excuse)
            if package.name in problematic:
                self._create_action_item(package, problematic[package.name])

        # Create all excuses in a single query
        PackageExcuses.objects.bulk_create(excuses)


class UpdateBuildLogCheckStats(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600 * 6

    ACTION_ITEM_TYPE_NAME = 'debian-build-logcheck'
    ITEM_DESCRIPTION = 'Build log checks report <a href="{url}">{report}</a>'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/logcheck-action-item.html'

    def initialize(self, *args, **kwargs):
        super(UpdateBuildLogCheckStats, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def _get_buildd_content(self):
        url = 'https://qa.debian.org/bls/logcheck.txt'
        return get_resource_content(url)

    def get_buildd_stats(self):
        content = self._get_buildd_content()
        stats = {}
        for line in content.decode('utf-8').splitlines():
            pkg, errors, warnings = line.split("|")[:3]
            try:
                errors, warnings = int(errors), int(warnings)
            except ValueError:
                continue
            stats[pkg] = {
                'errors': errors,
                'warnings': warnings,
            }
        return stats

    def create_action_item(self, package, stats):
        """
        Creates a :class:`distro_tracker.core.models.ActionItem` instance for
        the given package if the build logcheck stats indicate
        """
        action_item = \
            package.get_action_item_for_type(self.ACTION_ITEM_TYPE_NAME)

        errors = stats.get('errors', 0)
        warnings = stats.get('warnings', 0)

        if not errors and not warnings:
            # Remove the previous action item since the package no longer has
            # errors/warnings.
            if action_item is not None:
                action_item.delete()
            return

        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)

        if action_item.extra_data:
            if action_item.extra_data == stats:
                # Nothing has changed -- do not update the item
                return

        logcheck_url = "https://qa.debian.org/bls/packages/{hash}/{pkg}.html"\
            .format(hash=package.name[0], pkg=package.name)
        if errors and warnings:
            report = '{} error{} and {} warning{}'.format(
                errors,
                's' if errors > 1 else '',
                warnings,
                's' if warnings > 1 else '')
            action_item.severity = ActionItem.SEVERITY_HIGH
        elif errors:
            report = '{} error{}'.format(
                errors,
                's' if errors > 1 else '')
            action_item.severity = ActionItem.SEVERITY_HIGH
        elif warnings:
            report = '{} warning{}'.format(
                warnings,
                's' if warnings > 1 else '')
            action_item.severity = ActionItem.SEVERITY_LOW

        action_item.short_description = self.ITEM_DESCRIPTION.format(
            url=logcheck_url,
            report=report)
        action_item.extra_data = stats
        action_item.save()

    def execute_main(self):
        # Build a dict with stats from both buildd and clang
        stats = self.get_buildd_stats()

        BuildLogCheckStats.objects.all().delete()
        ActionItem.objects.delete_obsolete_items(
            [self.action_item_type], stats.keys())

        packages = SourcePackageName.objects.filter(name__in=stats.keys())
        packages = packages.prefetch_related('action_items')

        logcheck_stats = []
        for package in packages:
            logcheck_stat = BuildLogCheckStats(
                package=package,
                stats=stats[package.name])
            logcheck_stats.append(logcheck_stat)

            self.create_action_item(package, stats[package.name])

        # One SQL query to create all the stats.
        BuildLogCheckStats.objects.bulk_create(logcheck_stats)


class DebianWatchFileScannerUpdate(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600 * 6

    ACTION_ITEM_TYPE_NAMES = (
        'new-upstream-version',
        'watch-failure',
    )
    ACTION_ITEM_TEMPLATES = {
        'new-upstream-version': "debian/new-upstream-version-action-item.html",
        'watch-failure': "debian/watch-failure-action-item.html",
    }
    ITEM_DESCRIPTIONS = {
        'new-upstream-version': lambda item: (
            'A new upstream version is available: '
            '<a href="{url}">{version}</a>'.format(
                url=item.extra_data['upstream_url'],
                version=item.extra_data['upstream_version'])),
        'watch-failure': lambda item: (
            'Problems while searching for a new upstream version'),
    }
    ITEM_SEVERITIES = {
        'new-upstream-version': ActionItem.SEVERITY_HIGH,
        'watch-failure': ActionItem.SEVERITY_HIGH,
    }

    def initialize(self, *args, **kwargs):
        super(DebianWatchFileScannerUpdate, self).initialize(*args, **kwargs)
        self.action_item_types = {
            type_name: ActionItemType.objects.create_or_update(
                type_name=type_name,
                full_description_template=self.ACTION_ITEM_TEMPLATES.get(
                    type_name, None))
            for type_name in self.ACTION_ITEM_TYPE_NAMES
        }

    def _get_upstream_status_content(self):
        url = 'https://udd.debian.org/cgi-bin/upstream-status.json.cgi'
        return get_resource_content(url)

    def _remove_obsolete_action_items(self, item_type_name,
                                      non_obsolete_packages):
        """
        Removes any existing :class:`ActionItem` with the given type name based
        on the list of package names which should still have the items based on
        the processed stats.
        """
        action_item_type = self.action_item_types[item_type_name]
        ActionItem.objects.delete_obsolete_items(
            item_types=[action_item_type],
            non_obsolete_packages=non_obsolete_packages)

    def get_upstream_status_stats(self, stats):
        """
        Gets the stats from the downloaded data and puts them in the given
        ``stats`` dictionary.
        The keys of the dict are package names.

        :returns: A a two-tuple where the first item is a list of packages
            which have new upstream versions and the second is a list of
            packages which have watch failures.
        """
        content = self._get_upstream_status_content()
        dehs_data = None
        if content:
            dehs_data = json.loads(content.decode('utf-8'))
        if not dehs_data:
            return [], []

        all_new_versions, all_failures = [], []
        for entry in dehs_data:
            package_name = entry['package']
            stats.setdefault(package_name, {})
            stats[package_name]['upstream_version'] = entry['upstream-version']
            stats[package_name]['upstream_url'] = entry['upstream-url']
            if 'status' in entry and ('Newer version' in entry['status'] or
                                      'newer package' in entry['status']):
                stats[package_name]['new-upstream-version'] = {
                    'upstream_version': entry['upstream-version'],
                    'upstream_url': entry['upstream-url'],
                }
                all_new_versions.append(package_name)
            if entry.get('warnings') or entry.get('errors'):
                msg = '{}\n{}'.format(
                    entry.get('errors') or '',
                    entry.get('warnings') or '',
                ).strip()
                stats[package_name]['watch-failure'] = {
                    'warning': msg,
                }
                all_failures.append(package_name)

        return all_new_versions, all_failures

    def update_package_info(self, package, stats):
        """
        Updates upstream information of the given package based on the given
        stats. Upstream data is saved as a :class:`PackageData` within the
        `general` key

        :param package: The package to which the upstream info should be
            associated.
        :type package: :class:`distro_tracker.core.models.PackageName`
        :param stats: The stats which are used to create the upstream info.
        :type stats: :class:`dict`
        """
        try:
            watch_data = package.watch_status[0]
        except IndexError:
            watch_data = PackageData(
                package=package,
                key='upstream-watch-status',
            )

        watch_data.value = stats
        watch_data.save()

    def update_action_item(self, item_type, package, stats):
        """
        Updates the action item of the given type for the given package based
        on the given stats.

        The severity of the item is defined by the :attr:`ITEM_SEVERITIES` dict.

        The short descriptions are created by passing the :class:`ActionItem`
        (with extra data already set) to the callables defined in
        :attr:`ITEM_DESCRIPTIONS`.

        :param item_type: The type of the :class:`ActionItem` that should be
            updated.
        :type item_type: string
        :param package: The package to which this action item should be
            associated.
        :type package: :class:`distro_tracker.core.models.PackageName`
        :param stats: The stats which are used to create the action item.
        :type stats: :class:`dict`
        """
        action_item = package.get_action_item_for_type(item_type)
        if action_item is None:
            # Create an action item...
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_types[item_type])

        if item_type in self.ITEM_SEVERITIES:
            action_item.severity = self.ITEM_SEVERITIES[item_type]
        action_item.extra_data = stats
        action_item.short_description = \
            self.ITEM_DESCRIPTIONS[item_type](action_item)

        action_item.save()

    @transaction.atomic
    def execute_main(self):
        stats = {}
        new_upstream_version, failures = self.get_upstream_status_stats(stats)
        updated_packages_per_type = {
            'new-upstream-version': new_upstream_version,
            'watch-failure': failures,
        }

        # Remove obsolete action items for each of the categories...
        for item_type, packages in updated_packages_per_type.items():
            self._remove_obsolete_action_items(item_type, packages)

        packages = SourcePackageName.objects.filter(
            name__in=stats.keys())
        filter_qs = PackageData.objects.filter(key='upstream-watch-status')
        packages = packages.prefetch_related(
            'action_items',
            Prefetch('data', queryset=filter_qs, to_attr='watch_status')
        )

        # Update action items for each package
        for package in packages:
            for type_name in self.ACTION_ITEM_TYPE_NAMES:
                if type_name in stats[package.name]:
                    # method(package, stats[package.name][type_name])
                    self.update_action_item(
                        type_name, package, stats[package.name][type_name])

            self.update_package_info(package, stats[package.name])


class UpdateSecurityIssuesTask(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    ACTION_ITEM_TYPE_NAME = 'debian-security-issue-in-{}'
    ACTION_ITEM_TEMPLATE = 'debian/security-issue-action-item.html'
    ITEM_DESCRIPTION_TEMPLATE = {
        'open': '<a href="{url}">{count} security {issue}</a> in {release}',
        'nodsa':
            '<a href="{url}">{count} ignored security {issue}</a> in {release}',
        'none': 'No known security issue in {release}',
    }

    def initialize(self, *args, **kwargs):
        super(UpdateSecurityIssuesTask, self).initialize(*args, **kwargs)
        self._action_item_type = {}
        self._content = None

    def action_item_type(self, release):
        return self._action_item_type.setdefault(
            release, ActionItemType.objects.create_or_update(
                type_name=self.ACTION_ITEM_TYPE_NAME.format(release),
                full_description_template=self.ACTION_ITEM_TEMPLATE))

    def _get_issues_content(self):
        if self._content:
            return self._content
        url = 'https://security-tracker.debian.org/tracker/data/json'
        content = get_resource_content(url)
        if content:
            self._content = json.loads(content.decode('utf-8'))
            return self._content

    @staticmethod
    def get_issues_summary(issues):
        result = {}
        for issue_id, issue_data in issues.items():
            for release, data in issue_data['releases'].items():
                stats = result.setdefault(release, {
                    'open': 0,
                    'open_details': {},
                    'nodsa': 0,
                    'nodsa_details': {},
                    'unimportant': 0,
                })
                if (data.get('status', '') == 'resolved' or
                        data.get('urgency', '') == 'end-of-life'):
                    continue
                elif data.get('urgency', '') == 'unimportant':
                    stats['unimportant'] += 1
                elif data.get('nodsa', False):
                    stats['nodsa'] += 1
                    stats['nodsa_details'][issue_id] = \
                        issue_data.get('description', '')
                else:
                    stats['open'] += 1
                    stats['open_details'][issue_id] = \
                        issue_data.get('description', '')
        return result

    @classmethod
    def get_issues_stats(cls, content):
        """
        Gets package issue stats from Debian's security tracker.
        """
        stats = {}
        for pkg, issues in content.items():
            stats[pkg] = cls.get_issues_summary(issues)
        return stats

    def _get_short_description(self, key, action_item):
        count = action_item.extra_data['security_issues_count']
        url = 'https://security-tracker.debian.org/tracker/source-package/{}'
        return self.ITEM_DESCRIPTION_TEMPLATE[key].format(
            count=count,
            issue='issues' if count > 1 else 'issue',
            release=action_item.extra_data.get('release', 'sid'),
            url=url.format(action_item.package.name),
        )

    def update_action_item(self, stats, action_item):
        """
        Updates the ``debian-security-issue`` action item based on the count of
        security issues.
        """
        security_issues_count = stats['open'] + stats['nodsa']
        action_item.extra_data['security_issues_count'] = security_issues_count
        action_item.extra_data['open_details'] = stats['open_details']
        action_item.extra_data['nodsa_details'] = stats['nodsa_details']
        if stats['open']:
            action_item.severity = ActionItem.SEVERITY_HIGH
            action_item.short_description = \
                self._get_short_description('open', action_item)
        elif stats['nodsa']:
            action_item.severity = ActionItem.SEVERITY_LOW
            action_item.short_description = \
                self._get_short_description('nodsa', action_item)
        else:
            action_item.severity = ActionItem.SEVERITY_WISHLIST
            action_item.short_description = \
                self._get_short_description('none', action_item)

    @classmethod
    def generate_package_data(cls, issues):
        return {
            'details': issues,
            'stats': cls.get_issues_summary(issues),
            'checksum': get_data_checksum(issues)
        }

    def process_pkg_action_items(self, pkgdata, existing_action_items):
        release_ai = {}
        to_add = []
        to_update = []
        to_drop = []
        global_stats = pkgdata.value.get('stats', {})
        for ai in existing_action_items:
            release = ai.extra_data['release']
            release_ai[release] = ai
            if release not in global_stats:
                to_drop.append(ai)
        for release, stats in global_stats.items():
            count = stats.get('open', 0) + stats.get('nodsa', 0)
            if release in release_ai:
                ai = release_ai[release]
                if count == 0:
                    to_drop.append(ai)
                else:
                    self.update_action_item(stats, ai)
                    to_update.append(ai)
            elif count > 0:
                new_ai = ActionItem(item_type=self.action_item_type(release),
                                    package=pkgdata.package,
                                    extra_data={'release': release})
                self.update_action_item(stats, new_ai)
                to_add.append(new_ai)
        return to_add, to_update, to_drop

    def execute_main(self):
        # Fetch all debian-security PackageData
        all_pkgdata = PackageData.objects.select_related(
            'package').filter(key='debian-security').only(
                'package__name', 'value')

        all_data = {}
        packages = {}
        for pkgdata in all_pkgdata:
            all_data[pkgdata.package.name] = pkgdata
            packages[pkgdata.package.name] = pkgdata.package
        # Fetch all debian-security ActionItems
        pkg_action_items = collections.defaultdict(lambda: [])
        all_action_items = ActionItem.objects.select_related(
            'package').filter(
                item_type__type_name__startswith='debian-security-issue-in-')
        for action_item in all_action_items:
            pkg_action_items[action_item.package.name].append(action_item)
        # Scan the security tracker data
        content = self._get_issues_content()
        to_add = []
        to_update = []
        for pkgname, issues in content.items():
            if pkgname in all_data:
                # Check if we need to update the existing data
                checksum = get_data_checksum(issues)
                if all_data[pkgname].value.get('checksum', '') == checksum:
                    continue
                # Update the data
                pkgdata = all_data[pkgname]
                pkgdata.value = self.generate_package_data(issues)
                to_update.append(pkgdata)
            else:
                # Add data for a new package
                package, _ = PackageName.objects.get_or_create(name=pkgname)
                to_add.append(
                    PackageData(
                        package=package,
                        key='debian-security',
                        value=self.generate_package_data(issues)
                    )
                )
        # Process action items
        ai_to_add = []
        ai_to_update = []
        ai_to_drop = []
        for pkgdata in itertools.chain(to_add, to_update):
            add, update, drop = self.process_pkg_action_items(
                pkgdata, pkg_action_items[pkgdata.package.name])
            ai_to_add.extend(add)
            ai_to_update.extend(update)
            ai_to_drop.extend(drop)
        # Sync in database
        with transaction.atomic():
            # Delete obsolete data
            PackageData.objects.filter(
                key='debian-security').exclude(
                    package__name__in=content.keys()).delete()
            ActionItem.objects.filter(
                item_type__type_name__startswith='debian-security-issue-in-'
            ).exclude(package__name__in=content.keys()).delete()
            ActionItem.objects.filter(
                item_type__type_name__startswith='debian-security-issue-in-',
                id__in=[ai.id for ai in ai_to_drop]).delete()
            # Add new entries
            PackageData.objects.bulk_create(to_add)
            ActionItem.objects.bulk_create(ai_to_add)
            # Update existing entries
            for pkgdata in to_update:
                pkgdata.save()
            for ai in ai_to_update:
                ai.save()


class UpdatePiuPartsTask(BaseTask):
    """
    Retrieves the piuparts stats for all the suites defined in the
    :data:`distro_tracker.project.local_settings.DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES`
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    ACTION_ITEM_TYPE_NAME = 'debian-piuparts-test-fail'
    ACTION_ITEM_TEMPLATE = 'debian/piuparts-action-item.html'
    ITEM_DESCRIPTION = 'piuparts found (un)installation error(s)'

    def initialize(self, *args, **kwargs):
        super(UpdatePiuPartsTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def _get_piuparts_content(self, suite):
        """
        :returns: The content of the piuparts report for the given package
            or ``None`` if there is no data for the particular suite.
        """
        url = 'https://piuparts.debian.org/{suite}/sources.txt'
        return get_resource_content(url.format(suite=suite))

    def get_piuparts_stats(self):
        suites = getattr(settings, 'DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES', [])
        failing_packages = {}
        for suite in suites:
            content = self._get_piuparts_content(suite)
            if content is None:
                logger.info("There is no piuparts for suite: %s", suite)
                continue

            for line in content.decode('utf-8').splitlines():
                package_name, status = line.split(':', 1)
                package_name, status = package_name.strip(), status.strip()
                if status == 'fail':
                    failing_packages.setdefault(package_name, [])
                    failing_packages[package_name].append(suite)

        return failing_packages

    def create_action_item(self, package, suites):
        """
        Creates an :class:`ActionItem <distro_tracker.core.models.ActionItem>`
        instance for the package based on the list of suites in which the
        piuparts installation test failed.
        """
        action_item = package.get_action_item_for_type(self.action_item_type)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type,
                short_description=self.ITEM_DESCRIPTION)

        if action_item.extra_data:
            existing_items = action_item.extra_data.get('suites', [])
            if list(sorted(existing_items)) == list(sorted(suites)):
                # No need to update this item
                return
        action_item.extra_data = {
            'suites': suites,
        }
        action_item.save()

    def execute_main(self):
        failing_packages = self.get_piuparts_stats()

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=failing_packages.keys())

        packages = SourcePackageName.objects.filter(
            name__in=failing_packages.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.create_action_item(package, failing_packages[package.name])


class UpdateUbuntuStatsTask(BaseTask):
    """
    The task updates Ubuntu stats for packages. These stats are displayed in a
    separate panel.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    def initialize(self, *args, **kwargs):
        super(UpdateUbuntuStatsTask, self).initialize(*args, **kwargs)
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)

    def _get_versions_content(self):
        url = 'https://udd.debian.org/cgi-bin/ubuntupackages.cgi'
        return get_resource_content(url)

    def get_ubuntu_versions(self):
        """
        Retrieves the Ubuntu package versions.

        :returns: A dict mapping package names to Ubuntu versions.
        """
        content = self._get_versions_content()

        package_versions = {}
        for line in content.decode('utf-8').splitlines():
            package, version = line.split(' ', 1)
            version = version.strip()
            package_versions[package] = version

        return package_versions

    def _get_bug_stats_content(self):
        url = 'https://udd.debian.org/cgi-bin/ubuntubugs.cgi'
        return get_resource_content(url)

    def get_ubuntu_bug_stats(self):
        """
        Retrieves the Ubuntu bug stats of a package. Bug stats contain the
        count of bugs and the count of patches.

        :returns: A dict mapping package names to a dict of package stats.
        """
        content = self._get_bug_stats_content()

        bug_stats = {}
        for line in content.decode('utf-8').splitlines():
            package_name, bug_count, patch_count = line.split("|", 2)
            try:
                bug_count, patch_count = int(bug_count), int(patch_count)
            except ValueError:
                continue
            bug_stats[package_name] = {
                'bug_count': bug_count,
                'patch_count': patch_count,
            }

        return bug_stats

    def _get_ubuntu_patch_diff_content(self):
        url = 'https://patches.ubuntu.com/PATCHES'
        return get_resource_content(url)

    def get_ubuntu_patch_diffs(self):
        """
        Retrieves the Ubuntu patch diff information. The information consists
        of the diff URL and the version of the Ubuntu package to which the
        diff belongs to.

        :returns: A dict mapping package names to diff information.
        """
        content = self._get_ubuntu_patch_diff_content()

        patch_diffs = {}
        re_diff_version = re.compile(r'_(\S+)\.patch')
        for line in content.decode('utf-8').splitlines():
            package_name, diff_url = line.split(' ', 1)
            # Extract the version of the package from the diff url
            match = re_diff_version.search(diff_url)
            if not match:
                # Invalid URL: no version
                continue
            version = match.group(1)
            patch_diffs[package_name] = {
                'version': version,
                'diff_url': diff_url
            }

        return patch_diffs

    def execute_main(self):
        package_versions = self.get_ubuntu_versions()
        bug_stats = self.get_ubuntu_bug_stats()
        patch_diffs = self.get_ubuntu_patch_diffs()

        obsolete_ubuntu_pkgs = UbuntuPackage.objects.exclude(
            package__name__in=package_versions.keys())
        obsolete_ubuntu_pkgs.delete()

        packages = PackageName.objects.filter(name__in=package_versions.keys())
        packages = packages.prefetch_related('ubuntu_package')

        for package in packages:
            version = package_versions[package.name]
            bugs = bug_stats.get(package.name, None)
            diff = patch_diffs.get(package.name, None)

            try:
                ubuntu_package = package.ubuntu_package
                ubuntu_package.version = version
                ubuntu_package.bugs = bugs
                ubuntu_package.patch_diff = diff
                ubuntu_package.save()
            except UbuntuPackage.DoesNotExist:
                ubuntu_package = UbuntuPackage.objects.create(
                    package=package,
                    version=version,
                    bugs=bugs,
                    patch_diff=diff)


class UpdateDebianDuckTask(BaseTask):
    """
    A task for updating upstream url issue information on all packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    DUCK_LINK = 'http://duck.debian.net'
    # URL of the list of source packages with issues.
    DUCK_SP_LIST_URL = 'http://duck.debian.net/static/sourcepackages.txt'

    ACTION_ITEM_TYPE_NAME = 'debian-duck'
    ACTION_ITEM_TEMPLATE = 'debian/duck-action-item.html'
    ITEM_DESCRIPTION = 'The URL(s) for this package had some ' + \
        'recent persistent <a href="{issues_link}">issues</a>'

    def initialize(self, *args, **kwargs):
        super(UpdateDebianDuckTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def _get_duck_urls_content(self):
        """
        Gets the list of packages with URL issues from
        duck.debian.net

        :returns: A array if source package names.
        """

        ducklist = get_resource_text(self.DUCK_SP_LIST_URL)
        if ducklist is None:
            return None

        packages = []
        for package_name in ducklist.splitlines():
            package_name = package_name.strip()
            packages.append(package_name)
        return packages

    def update_action_item(self, package):
        action_item = package.get_action_item_for_type(self.action_item_type)
        if not action_item:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type,
            )

        issues_link = self.DUCK_LINK + "/static/sp/" \
            + package_hashdir(package.name) + "/" + package.name + ".html"
        action_item.short_description = \
            self.ITEM_DESCRIPTION.format(issues_link=issues_link)

        action_item.extra_data = {
            'duck_link': self.DUCK_LINK,
            'issues_link': issues_link
        }
        action_item.severity = ActionItem.SEVERITY_LOW
        action_item.save()

    def execute_main(self):
        ducklings = self._get_duck_urls_content()
        if ducklings is None:
            return

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=ducklings)

        packages = SourcePackageName.objects.filter(name__in=ducklings)

        for package in packages:
            self.update_action_item(package)


class UpdateWnppStatsTask(BaseTask):
    """
    The task updates the WNPP bugs for all packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    ACTION_ITEM_TYPE_NAME = 'debian-wnpp-issue'
    ACTION_ITEM_TEMPLATE = 'debian/wnpp-action-item.html'
    ITEM_DESCRIPTION = '<a href="{url}">{wnpp_type}: {wnpp_msg}</a>'

    def initialize(self, *args, **kwargs):
        super(UpdateWnppStatsTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def get_wnpp_stats(self):
        """
        Retrieves and parses the wnpp stats for all packages. WNPP stats
        include the WNPP type and the BTS bug id.

        :returns: A dict mapping package names to wnpp stats.
        """
        url = 'https://qa.debian.org/data/bts/wnpp_rm'
        content = get_resource_text(url, only_if_updated=True)
        if content is None:
            return

        wnpp_stats = {}
        for line in content.splitlines():
            line = line.strip()
            try:
                package_name, wnpp_type, bug_id = line.split('|')[0].split()
                bug_id = int(bug_id)
            except ValueError:
                # Badly formatted bug number
                continue
            # Strip the colon from the end of the package name
            package_name = package_name[:-1]

            wnpp_stats[package_name] = {
                'wnpp_type': wnpp_type,
                'bug_id': bug_id,
            }

        return wnpp_stats

    def update_action_item(self, package, stats):
        """
        Creates an :class:`ActionItem <distro_tracker.core.models.ActionItem>`
        instance for the given type indicating that the package has a WNPP
        issue.
        """
        action_item = package.get_action_item_for_type(self.action_item_type)
        if not action_item:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)

        # Check if the stats have actually been changed
        if action_item.extra_data:
            if action_item.extra_data.get('wnpp_info', None) == stats:
                # Nothing to do -- stll the same data
                return

        # Update the data since something has changed
        try:
            release = package.main_entry.repository.suite or \
                package.main_entry.repository.codename
        except AttributeError:
            release = None

        msgs = {
            'O': "This package has been orphaned and needs a maintainer.",
            'ITA': "Someone intends to adopt this package.",
            'RFA': "The maintainer wants to pass over package maintainance.",
            'RFH': "The maintainer is looking for help with this package.",
            'ITP': "Someone is planning to reintroduce this package.",
            'RFP': "There is a request to reintroduce this package.",
            'RM': "This package has been requested to be removed.",
            'RFS': "A sponsor is needed to update this package.",
            '?': "The WNPP database contains an entry for this package."
        }
        wnpp_type = stats['wnpp_type']
        try:
            wnpp_msg = msgs[wnpp_type]
        except KeyError:
            wnpp_msg = msgs['?']

        action_item.short_description = self.ITEM_DESCRIPTION.format(
            url='https://bugs.debian.org/{}'.format(stats['bug_id']),
            wnpp_type=wnpp_type, wnpp_msg=wnpp_msg)
        action_item.extra_data = {
            'wnpp_info': stats,
            'release': release,
        }
        action_item.save()

    def update_depneedsmaint_action_item(self, package_needs_maintainer, stats):
        short_description_template = \
            'Depends on packages which need a new maintainer'
        package_needs_maintainer.get_absolute_url()
        action_item_type = ActionItemType.objects.create_or_update(
            type_name='debian-depneedsmaint',
            full_description_template='debian/depneedsmaint-action-item.html')
        dependencies = SourcePackageDeps.objects.filter(
            dependency=package_needs_maintainer)
        for dependency in dependencies:
            package = dependency.source
            action_item = package.get_action_item_for_type(action_item_type)
            if not action_item:
                action_item = ActionItem(
                    package=package,
                    item_type=action_item_type,
                    extra_data={})

            pkgdata = {
                'bug': stats['bug_id'],
                'details': dependency.details,
            }

            if (action_item.extra_data.get(package_needs_maintainer.name, {}) ==
                    pkgdata):
                # Nothing has changed
                continue

            action_item.short_description = short_description_template
            action_item.extra_data[package_needs_maintainer.name] = pkgdata

            action_item.save()

    @transaction.atomic
    def execute_main(self):
        wnpp_stats = self.get_wnpp_stats()
        if wnpp_stats is None:
            # Nothing to do: cached content up to date
            return

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=wnpp_stats.keys())
        # Remove obsolete action items for packages whose dependencies need a
        # new maintainer.
        packages_need_maintainer = []
        for name, stats in wnpp_stats.items():
            if stats['wnpp_type'] in ('O', 'RFA'):
                packages_need_maintainer.append(name)
        packages_depneeds_maint = [
            package.name for package in SourcePackageName.objects.filter(
                source_dependencies__dependency__name__in=packages_need_maintainer)  # noqa
        ]
        ActionItem.objects.delete_obsolete_items(
            item_types=[
                ActionItemType.objects.get_or_create(
                    type_name='debian-depneedsmaint')[0],
            ],
            non_obsolete_packages=packages_depneeds_maint)

        # Drop all reverse references
        for ai in ActionItem.objects.filter(
                item_type__type_name='debian-depneedsmaint'):
            ai.extra_data = {}
            ai.save()

        packages = SourcePackageName.objects.filter(name__in=wnpp_stats.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            stats = wnpp_stats[package.name]
            self.update_action_item(package, stats)
            # Update action items for packages which depend on this one to
            # indicate that a dependency needs a new maintainer.
            if package.name in packages_need_maintainer:
                self.update_depneedsmaint_action_item(package, stats)


class UpdateNewQueuePackages(BaseTask):
    """
    Updates the versions of source packages found in the NEW queue.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    DATA_KEY = 'debian-new-queue-info'

    def initialize(self, *args, **kwargs):
        super(UpdateNewQueuePackages, self).initialize(*args, **kwargs)

    def _get_new_content(self):
        """
        :returns: The content of the deb822 formatted file giving the list of
            packages found in NEW.
            ``None`` if the cached resource is up to date.
        """
        url = 'https://ftp-master.debian.org/new.822'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        if not cache.is_expired(url):
            return
        response, updated = cache.update(url, force=self.force_update)
        if not updated:
            return
        return response.content

    def extract_package_info(self, content):
        """
        Extracts the package information from the content of the NEW queue.
        :returns: A dict mapping package names to a dict mapping the
            distribution name in which the package is found to the version
            information for the most recent version of the package in the dist.
        """
        packages = {}
        for stanza in deb822.Deb822.iter_paragraphs(content.splitlines()):
            necessary_fields = ('Source', 'Queue', 'Version', 'Distribution')
            if not all(field in stanza for field in necessary_fields):
                continue
            if stanza['Queue'] != 'new':
                continue

            versions = stanza['Version'].split()
            # Save only the most recent version
            version = max(versions, key=lambda x: AptPkgVersion(x))

            package_name = stanza['Source']
            pkginfo = packages.setdefault(package_name, {})
            distribution = stanza['Distribution']
            if distribution in pkginfo:
                current_version = pkginfo[distribution]['version']
                if debian_support.version_compare(version, current_version) < 0:
                    # The already saved version is more recent than this one.
                    continue

            pkginfo[distribution] = {
                'version': version,
            }

        return packages

    def execute_main(self):
        content = self._get_new_content()

        all_package_info = self.extract_package_info(content)

        packages = SourcePackageName.objects.filter(
            name__in=all_package_info.keys())

        with transaction.atomic():
            # Drop old entries
            PackageData.objects.filter(key=self.DATA_KEY).delete()
            # Prepare current entries
            data = []
            for package in packages:
                new_queue_info = PackageData(
                    key=self.DATA_KEY,
                    package=package,
                    value=all_package_info[package.name])
                data.append(new_queue_info)
            # Bulk create them
            PackageData.objects.bulk_create(data)


class UpdateDebciStatusTask(BaseTask):
    """
    Updates packages' debci status.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE_NAME = 'debci-failed-tests'
    ITEM_DESCRIPTION = (
        'Debci reports <a href="{debci_url}">failed tests</a> '
        '(<a href="{log_url}">log</a>)'
    )
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/debci-action-item.html'

    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.debci_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def get_debci_status(self):
        url = 'https://ci.debian.net/data/status/unstable/amd64/packages.json'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return
        debci_status = json.loads(response.text)
        return debci_status

    def update_action_item(self, package, debci_status):
        """
        Updates the :class:`ActionItem` for the given package based on the
        :class:`DebciStatus <distro_tracker.vendor.debian.models.DebciStatus`
        If the package has test failures an :class:`ActionItem` is created.
        """
        debci_action_item = package.get_action_item_for_type(
            self.debci_action_item_type.type_name)
        if debci_status.get('status') in ('pass', 'neutral'):
            if debci_action_item:
                debci_action_item.delete()
            return

        if debci_action_item is None:
            debci_action_item = ActionItem(
                package=package,
                item_type=self.debci_action_item_type,
                severity=ActionItem.SEVERITY_HIGH)

        package_name = debci_status.get('package')
        if package_name[:3] == 'lib':
            log_dir = package_name[:4]
        else:
            log_dir = package_name[:1]
        url = 'https://ci.debian.net/packages/' + log_dir + '/' + \
            package_name + '/'
        log = 'https://ci.debian.net/data/packages/unstable/amd64/' + \
            log_dir + "/" + package_name + '/latest-autopkgtest/log.gz'
        debci_action_item.short_description = self.ITEM_DESCRIPTION.format(
            debci_url=url,
            log_url=log)

        debci_action_item.extra_data = {
            'duration': debci_status.get('duration_human'),
            'previous_status': debci_status.get('previous_status'),
            'date': debci_status.get('date'),
            'url': url,
            'log': log,
        }

        debci_action_item.save()

    def execute_main(self):
        all_debci_status = self.get_debci_status()
        if all_debci_status is None:
            return

        with transaction.atomic():
            # Delete obsolete data
            PackageData.objects.filter(key='debci').delete()
            packages = []
            infos = []
            for result in all_debci_status:
                try:
                    package = SourcePackageName.objects.get(
                        name=result['package'])
                    packages.append(package)
                except SourcePackageName.DoesNotExist:
                    continue

                infos.append(
                    PackageData(
                        package=package,
                        key='debci',
                        value=result
                    )
                )

                self.update_action_item(package, result)

            PackageData.objects.bulk_create(infos)
            ActionItem.objects.delete_obsolete_items(
                [self.debci_action_item_type], packages)


class UpdateAutoRemovalsStatsTask(BaseTask):
    """
    A task for updating autoremovals information on all packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE_NAME = 'debian-autoremoval'
    ACTION_ITEM_TEMPLATE = 'debian/autoremoval-action-item.html'
    ITEM_DESCRIPTION = ('Marked for autoremoval on {removal_date}' +
                        '{dependencies}: {bugs}')

    def initialize(self, *args, **kwargs):
        super(UpdateAutoRemovalsStatsTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def get_autoremovals_stats(self):
        """
        Retrieves and parses the autoremoval stats for all packages.
        Autoremoval stats include the BTS bugs id.

        :returns: A dict mapping package names to autoremoval stats.
        """
        content = get_resource_content(
            'https://udd.debian.org/cgi-bin/autoremovals.yaml.cgi')
        if content:
            return yaml.safe_load(io.BytesIO(content))

    def update_action_item(self, package, stats):
        """
        Creates an :class:`ActionItem <distro_tracker.core.models.ActionItem>`
        instance for the given type indicating that the package has an
        autoremoval issue.
        """
        action_item = package.get_action_item_for_type(self.action_item_type)
        if not action_item:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type,
                severity=ActionItem.SEVERITY_HIGH)

        bugs_dependencies = stats.get('bugs_dependencies', [])
        buggy_dependencies = stats.get('buggy_dependencies', [])
        reverse_dependencies = stats.get('rdeps', [])
        all_bugs = stats['bugs'] + bugs_dependencies
        link = '<a href="https://bugs.debian.org/{}">#{}</a>'
        removal_date = stats['removal_date'].strftime('%d %B')
        if isinstance(removal_date, bytes):
            removal_date = removal_date.decode('utf-8', 'ignore')

        action_item.short_description = self.ITEM_DESCRIPTION.format(
            removal_date=removal_date,
            dependencies=(' due to ' + html_package_list(
                buggy_dependencies) if buggy_dependencies else ''),
            bugs=', '.join(link.format(bug, bug) for bug in all_bugs))

        # datetime objects are not JSON-serializable, convert them ourselves
        for key in stats.keys():
            if hasattr(stats[key], 'strftime'):
                stats[key] = stats[key].strftime('%a %d %b %Y')

        action_item.extra_data = {
            'stats': stats,
            'removal_date': stats['removal_date'],
            'version': stats.get('version', ''),
            'bugs': ', '.join(link.format(bug, bug) for bug in stats['bugs']),
            'bugs_dependencies': ', '.join(
                link.format(bug, bug) for bug in bugs_dependencies),
            'buggy_dependencies':
                html_package_list(buggy_dependencies),
            'reverse_dependencies':
                html_package_list(reverse_dependencies),
            'number_rdeps': len(reverse_dependencies)}
        action_item.save()

    def execute_main(self):
        autoremovals_stats = self.get_autoremovals_stats()
        if autoremovals_stats is None:
            # Nothing to do: cached content up to date
            return

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=autoremovals_stats.keys())

        packages = SourcePackageName.objects.filter(
            name__in=autoremovals_stats.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.update_action_item(package, autoremovals_stats[package.name])


class UpdatePackageScreenshotsTask(BaseTask):
    """
    Check if a screenshot exists on screenshots.debian.net, and add a
    key to PackageData if it does.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 24

    DATA_KEY = 'screenshots'

    def _get_screenshots(self):
        url = 'https://screenshots.debian.net/json/packages'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return

        data = json.loads(response.text)
        return data

    def execute_main(self):
        content = self._get_screenshots()
        if content is None:
            return

        packages_with_screenshots = []
        for item in content['packages']:
            try:
                package = SourcePackageName.objects.get(name=item['name'])
                packages_with_screenshots.append(package)
            except SourcePackageName.DoesNotExist:
                pass

        with transaction.atomic():
            PackageData.objects.filter(key='screenshots').delete()

            data = []
            for package in packages_with_screenshots:
                try:
                    screenshot_info = package.data.get(key=self.DATA_KEY)
                    screenshot_info.value['screenshots'] = 'true'
                except PackageData.DoesNotExist:
                    screenshot_info = PackageData(
                        key=self.DATA_KEY,
                        package=package,
                        value={'screenshots': 'true'})

                data.append(screenshot_info)

            PackageData.objects.bulk_create(data)


class UpdateBuildReproducibilityTask(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600 * 6

    BASE_URL = 'https://tests.reproducible-builds.org'
    ACTION_ITEM_TYPE_NAME = 'debian-build-reproducibility'
    ACTION_ITEM_TEMPLATE = 'debian/build-reproducibility-action-item.html'
    ITEM_DESCRIPTION = {
        'blacklisted': '<a href="{url}">Blacklisted</a> from build '
                       'reproducibility testing',
        'FTBFS': '<a href="{url}">Fails to build</a> during reproducibility '
                 'testing',
        'reproducible': None,
        'FTBR': '<a href="{url}">Does not build reproducibly</a> '
                'during testing',
        '404': None,
        'not for us': None,
    }

    def initialize(self, *args, **kwargs):
        super(UpdateBuildReproducibilityTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def get_build_reproducibility(self):
        url = '{}/debian/reproducible-tracker.json'.format(self.BASE_URL)
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        if not self.force_update and not cache.is_expired(url):
            return
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return
        reproducibilities = json.loads(response.text)
        packages = {}
        for item in reproducibilities:
            package = item['package']
            status = item['status']
            missing = package not in packages
            important = self.ITEM_DESCRIPTION.get(status) is not None
            if important or missing:
                packages[package] = status
        return packages

    def update_action_item(self, package, status):
        description = self.ITEM_DESCRIPTION.get(status)

        if not description:  # Not worth an action item
            return False

        action_item = package.get_action_item_for_type(
            self.action_item_type.type_name)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type,
                severity=ActionItem.SEVERITY_NORMAL)

        url = "{}/debian/rb-pkg/{}.html".format(self.BASE_URL, package.name)
        action_item.short_description = description.format(url=url)
        action_item.save()
        return True

    def execute_main(self):
        reproducibilities = self.get_build_reproducibility()
        if reproducibilities is None:
            return

        with transaction.atomic():
            PackageData.objects.filter(key='reproducibility').delete()

            packages = []
            data = []

            for name, status in reproducibilities.items():
                try:
                    package = SourcePackageName.objects.get(name=name)
                    if self.update_action_item(package, status):
                        packages.append(package)
                except SourcePackageName.DoesNotExist:
                    continue

                reproducibility_info = PackageData(
                    key='reproducibility',
                    package=package,
                    value={'reproducibility': status})
                data.append(reproducibility_info)

            ActionItem.objects.delete_obsolete_items([self.action_item_type],
                                                     packages)
            PackageData.objects.bulk_create(data)


class MultiArchHintsTask(BaseTask):

    class Scheduler(IntervalScheduler):
        interval = 3600 * 6

    ACTIONS_WEB = 'https://wiki.debian.org/MultiArch/Hints'
    ACTIONS_URL = 'https://dedup.debian.net/static/multiarch-hints.yaml'
    ACTION_ITEM_TYPE_NAME = 'debian-multiarch-hints'
    ACTION_ITEM_TEMPLATE = 'debian/multiarch-hints.html'
    ACTION_ITEM_DESCRIPTION = \
        '<a href="{link}">Multiarch hinter</a> reports {count} issue(s)'

    def initialize(self, *args, **kwargs):
        super(MultiArchHintsTask, self).initialize(*args, **kwargs)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)
        self.SEVERITIES = {}
        for value, name in ActionItem.SEVERITIES:
            self.SEVERITIES[name] = value

    def get_data(self):
        data = get_resource_content(self.ACTIONS_URL)
        data = yaml.safe_load(data)
        return data

    def get_packages(self):
        data = self.get_data()
        if data['format'] != 'multiarch-hints-1.0':
            return None
        data = data['hints']
        packages = collections.defaultdict(dict)
        for item in data:
            if 'source' not in item:
                continue
            package = item['source']
            wishlist = ActionItem.SEVERITY_WISHLIST
            severity = self.SEVERITIES.get(item['severity'], wishlist)
            pkg_severity = packages[package].get('severity', wishlist)
            packages[package]['severity'] = max(severity, pkg_severity)
            packages[package].setdefault('hints', []).append(
                (item['description'], item['link']))
        return packages

    def update_action_item(self, package, severity, description, extra_data):
        action_item = package.get_action_item_for_type(
            self.action_item_type.type_name)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)
        action_item.severity = severity
        action_item.short_description = description
        action_item.extra_data = extra_data
        action_item.save()

    def execute_main(self):
        packages = self.get_packages()
        if not packages:
            return

        with transaction.atomic():
            for name, data in packages.items():
                try:
                    package = SourcePackageName.objects.get(name=name)
                except SourcePackageName.DoesNotExist:
                    continue

                description = self.ACTION_ITEM_DESCRIPTION.format(
                    count=len(data['hints']), link=self.ACTIONS_WEB)
                self.update_action_item(package, data['severity'], description,
                                        data['hints'])

            ActionItem.objects.delete_obsolete_items([self.action_item_type],
                                                     packages.keys())


class UpdateVcsWatchTask(BaseTask):
    """
    Updates packages' vcswatch stats.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE_NAME = 'vcswatch-warnings-and-errors'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/vcswatch-action-item.html'
    VCSWATCH_URL = 'https://qa.debian.org/cgi-bin/vcswatch?package=%(package)s'
    VCSWATCH_DATA_URL = 'https://qa.debian.org/data/vcswatch/vcswatch.json.gz'

    VCSWATCH_STATUS_DICT = {
        "NEW": {
            "description":
                '<a href="{vcswatch_url}">{commits} new commit{commits_s}</a> '
                'since last upload, time to upload?',
            "severity": ActionItem.SEVERITY_NORMAL,
        },
        "COMMITS": {
            "description":
                '<a href="{vcswatch_url}">{commits} new commit{commits_s}</a> '
                'since last upload, time to release?',
            "severity": ActionItem.SEVERITY_NORMAL,
        },
        "OLD": {
            'description':
                'The <a href="{vcswatch_url}">VCS repository is not up to '
                'date</a>, push the missing commits.',
            "severity": ActionItem.SEVERITY_HIGH,
        },
        "UNREL": {
            "description":
                'The <a href="{vcswatch_url}">VCS repository is not up to '
                'date</a>, push the missing commits.',
            "severity": ActionItem.SEVERITY_HIGH,
        },
        "ERROR": {
            "description":
                '<a href="{vcswatch_url}">Failed to analyze the VCS '
                'repository</a>. Please troubleshoot and fix the issue.',
            "severity": ActionItem.SEVERITY_HIGH,
        },
        "DEFAULT": {
            "description":
                '<a href="{url}">Unexpected status</a> ({status}) reported by '
                'VcsWatch.',
            "severity": ActionItem.SEVERITY_HIGH,
        },
    }

    def initialize(self, *args, **kwargs):
        super(UpdateVcsWatchTask, self).initialize(*args, **kwargs)
        self.vcswatch_ai_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE
        )

    def get_vcswatch_data(self):
        text = get_resource_text(self.VCSWATCH_DATA_URL)

        if text is None:
            return

        # There's some text, let's load!
        data = json.loads(text)

        out = {}
        # This allows to save a lot of list search later.
        for entry in data:
            out[entry[u'package']] = entry

        return out

    def clean_package_info(self, package_infos_without_watch, todo):
        """Takes a list of :class:`PackageData` which do not
        have a watch entry and cleans it. Then schedule in todo what
        to do with them.
        """
        for package_info in package_infos_without_watch:
            if 'QA' in package_info.value:
                package_info.value.pop('QA')
                if (list(package_info.value.keys()) == ['checksum'] or
                        not package_info.value.keys()):
                    todo['drop']['package_infos'].append(package_info)
                else:
                    package_info.value['checksum'] = get_data_checksum(
                        package_info.value
                    )
                    todo['update']['package_infos'].append(package_info)

    def update_action_item(self, package, vcswatch_data, action_item, todo):
        """
        For a given :class:`ActionItem` and a given vcswatch data, updates
        properly the todo dict if required.

        Returns dependingly on what has been done. If something is to
        be updated, returns True, if nothing is to be updated, returns
        False. If the calling loop should `continue`, returns `None`.

        :rtype: bool or `None`
        """

        package_status = vcswatch_data['status']

        if package_status == "OK":
            # Everything is fine, let's purge the action item. Not the
            # package extracted info as its QA url is still relevant.
            if action_item:
                todo['drop']['action_items'].append(action_item)

            # Nothing more to do!
            return False

        # NOT BEFORE "OK" check!!
        if package_status not in self.VCSWATCH_STATUS_DICT:
            package_status = "DEFAULT"

        # If we are here, then something is not OK. Let's check if we
        # already had some intel regarding the current package status.
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.vcswatch_ai_type)
            todo['add']['action_items'].append(action_item)
        else:
            todo['update']['action_items'].append(action_item)

        # Computes the watch URL
        vcswatch_url = self.VCSWATCH_URL % {'package': package.name}

        if action_item.extra_data:
            extra_data = action_item.extra_data
        else:
            extra_data = {}

        # Fetches the long description and severity from
        # the VCSWATCH_STATUS_DICT dict.
        action_item.severity = \
            self.VCSWATCH_STATUS_DICT[package_status]['severity']

        nb_commits = int(vcswatch_data["commits"] or 0)

        # The new data
        new_extra_data = {
            'vcswatch_url': vcswatch_url,
        }
        new_extra_data.update(vcswatch_data)

        extra_data_match = all([
            new_extra_data[key] == extra_data.get(key, None)
            for key in new_extra_data
        ])

        # If everything is fine and we are not forcing the update
        # then we proceed to the next package.
        if extra_data_match and not self.force_update:
            # Remove from the todolist
            todo['update']['action_items'].remove(action_item)
            return False
        else:
            # Report for short description of the :class:`ActionItem`
            desc = self.VCSWATCH_STATUS_DICT[package_status]['description']
            commits_s = 's' if nb_commits != 1 else ''
            action_item.short_description = \
                desc.format(commits_s=commits_s, **new_extra_data)
            action_item.extra_data = new_extra_data
            return True

    def update_package_info(self, package, vcswatch_data, package_info, key,
                            todo):
        # Same thing with PackageData
        if package_info is None:
            package_info = PackageData(
                package=package,
                key=key,
            )
            todo['add']['package_infos'].append(package_info)
        else:
            todo['update']['package_infos'].append(package_info)

        # Computes the watch URL
        vcswatch_url = self.VCSWATCH_URL % {'package': package.name}

        new_value = dict(package_info.value)
        if key == 'vcs_extra_links':
            new_value['QA'] = vcswatch_url
        elif key == 'vcswatch':
            if 'package_version' in vcswatch_data:
                new_value['package_version'] = vcswatch_data['package_version']
            if 'changelog_version' in vcswatch_data:
                new_value['changelog_version'] = vcswatch_data[
                    'changelog_version']
            if 'changelog_distribution' in vcswatch_data:
                new_value['changelog_distribution'] = vcswatch_data[
                    'changelog_distribution']

        new_value['checksum'] = get_data_checksum(new_value)

        package_info_match = (
            new_value['checksum'] == package_info.value.get('checksum', None)
        )

        if package_info_match and not self.force_update:
            todo['update']['package_infos'].remove(package_info)
            return False
        else:
            package_info.value = new_value
            return True

    def update_packages_item(self, packages, vcswatch_datas):
        """Generates the lists of :class:`ActionItem` to be added,
        deleted or updated regarding the status of their packages.

        Categories of statuses are:
        {u'COMMITS', u'ERROR', u'NEW', u'OK', u'OLD', u'UNREL'}

        Basically, it fetches all info from :class:`PackageData`
        with key='vcs', the ones without data matching vcswatch_datas are
        stored in one variable that's iterated through directly, and if
        there was something before, it is purged. Then, all entries in
        that queryset that have no relevant intel anymore are scheduled
        to be deleted. The others are only updated.

        All :class:`PackageData` matching vcswatch_datas
        are stored in another variable. The same is done with the list of
        :class:`ActionItem` that match this task type.

        Then, it iterates on all vcswatch_datas' packages and it tries to
        determine if there are any news, if so, it updates apopriately the
        prospective :class:`ActionItem` and :class:`PackageData`,
        and schedule them to be updated. If no data was existent, then
        it creates them and schedule them to be added to the database.

        At the end, this function returns a dict of all instances of
        :class:`ActionItem` and :class:`PackageData` stored
        in subdicts depending on their class and what is to be done
        with them.

        :rtype: dict

        """

        todo = {
            'drop': {
                'action_items': [],
                'package_infos': [],
            },
            'update': {
                'action_items': [],
                'package_infos': [],
            },
            'add': {
                'action_items': [],
                'package_infos': [],
            },
        }

        package_info_keys = ['vcs_extra_links', 'vcswatch']
        package_infos = {}
        for key in package_info_keys:
            # Fetches all PackageData with a given key for packages having
            # a vcswatch key. As the pair (package, key) is unique, there is a
            # bijection between these data, and we fetch them classifying them
            # by package name.
            for package_info in PackageData.objects.select_related(
                    'package').filter(key=key).only('package__name', 'value'):
                if package_info.package.name not in package_infos:
                    package_infos[package_info.package.name] = {}
                package_infos[package_info.package.name][key] = package_info

        # As :class:`PackageData` key=vcs_extra_links is shared, we
        # have to clean up those with vcs watch_url that aren't in vcs_data
        package_infos_without_watch = PackageData.objects.filter(
            key='vcs_extra_links').exclude(
            package__name__in=vcswatch_datas.keys()).only('value')

        # Do the actual clean.
        self.clean_package_info(package_infos_without_watch, todo)

        # Fetches all :class:`ActionItem` for packages concerned by a vcswatch
        # action.
        action_items = {
            action_item.package.name: action_item
            for action_item in ActionItem.objects.select_related(
                'package'
            ).filter(item_type=self.vcswatch_ai_type)
        }

        for package in packages:
            # Get the vcswatch_data from the whole vcswatch_datas
            vcswatch_data = vcswatch_datas[package.name]

            # Get the old action item for this warning, if it exists.
            action_item = action_items.get(package.name, None)

            # Updates the :class:`ActionItem`. If _continue is None,
            # then there is nothing more to do with this package.
            # If it is False, then no update is pending for the
            # :class:`ActionItem`, else there is an update
            # to do.
            _ai_continue = self.update_action_item(
                package,
                vcswatch_data,
                action_item,
                todo)

            _pi_continue = False
            for key in package_info_keys:
                try:
                    package_info = package_infos[package.name][key]
                except KeyError:
                    package_info = None

                _pi_continue |= self.update_package_info(
                    package,
                    vcswatch_data,
                    package_info,
                    key,
                    todo)

            if not _ai_continue and not _pi_continue:
                continue

        return todo

    def execute_main(self):
        # Get the actual vcswatch json file from qa.debian.org
        vcs_data = self.get_vcswatch_data()

        # Only fetch the packages that are in the json dict.
        packages = PackageName.objects.filter(name__in=vcs_data.keys())

        # Faster than fetching the action items one by one in a loop
        # when handling each package.
        packages.prefetch_related('action_items')

        # Determine wether something is to be kept or dropped.
        todo = self.update_packages_item(packages, vcs_data)

        with transaction.atomic():
            # Delete the :class:`ActionItem` that are osbolete, and also
            # the :class:`PackageData` of the same.
            ActionItem.objects.delete_obsolete_items(
                [self.vcswatch_ai_type],
                vcs_data.keys())
            PackageData.objects.filter(
                key='vcs_extra_links',
                id__in=[
                    package_info.id
                    for package_info in todo['drop']['package_infos']
                ]
            ).delete()

            # Then delete the :class:`ActionItem` that are to be deleted.
            ActionItem.objects.filter(
                item_type__type_name=self.vcswatch_ai_type.type_name,
                id__in=[
                    action_item.id
                    for action_item in todo['drop']['action_items']
                ]
            ).delete()

            # Then bulk_create the :class:`ActionItem` to add and the
            # :class:`PackageData`
            ActionItem.objects.bulk_create(todo['add']['action_items'])
            PackageData.objects.bulk_create(todo['add']['package_infos'])

            # Update existing entries
            for action_item in todo['update']['action_items']:
                action_item.save()
            for package_info in todo['update']['package_infos']:
                package_info.save()


class TagPackagesWithRcBugs(BaseTask, PackageTagging):
    """
    Performs an update of 'rc-bugs' tag for packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    TAG_NAME = 'tag:rc-bugs'
    TAG_DISPLAY_NAME = 'rc bugs'
    TAG_COLOR_TYPE = 'danger'
    TAG_DESCRIPTION = 'The package has Release Critical bugs'
    TAG_TABLE_TITLE = 'Packages with RC bugs'

    def packages_to_tag(self):
        all_bug_stats = PackageBugStats.objects.all().prefetch_related(
            'package')
        packages_list = []
        for bug_stats in all_bug_stats:
            categories = bug_stats.stats
            found = False
            for category in categories:
                if found:
                    break
                if category['category_name'] == 'rc':
                    found = True
                    if category['bug_count'] > 0:
                        packages_list.append(bug_stats.package)
        return packages_list


class TagPackagesWithNewUpstreamVersion(BaseTask, PackageTagging):
    """
    Performs an update of 'new-upstream-version' tag for packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 3

    TAG_NAME = 'tag:new-upstream-version'
    TAG_DISPLAY_NAME = 'new upstream version'
    TAG_COLOR_TYPE = 'warning'
    TAG_DESCRIPTION = 'The upstream has a newer version available'
    TAG_TABLE_TITLE = 'Newer upstream version'

    def packages_to_tag(self):
        try:
            action_type = ActionItemType.objects.get(
                type_name='new-upstream-version')
        except ActionItemType.DoesNotExist:
            return []

        packages_list = []
        items = action_type.action_items.all().prefetch_related('package')
        for item in items:
            packages_list.append(item.package)
        return packages_list
