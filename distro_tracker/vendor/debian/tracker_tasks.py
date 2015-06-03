# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Debian-specific tasks.
"""

from __future__ import unicode_literals
from django.db import transaction
from django.conf import settings
from django.utils import six
from django.utils.http import urlencode
from django.core.urlresolvers import reverse

from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.models import PackageExtractedInfo
from distro_tracker.core.models import ActionItem, ActionItemType
from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import PackageBugStats
from distro_tracker.core.models import BinaryPackageBugStats
from distro_tracker.core.models import PackageName
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import BinaryPackageName
from distro_tracker.core.models import SourcePackageDeps
from distro_tracker.vendor.debian.models import LintianStats
from distro_tracker.vendor.debian.models import BuildLogCheckStats
from distro_tracker.vendor.debian.models import PackageTransition
from distro_tracker.vendor.debian.models import PackageExcuses
from distro_tracker.vendor.debian.models import UbuntuPackage
from distro_tracker.core.utils.http import HttpCache
from distro_tracker.core.utils.http import get_resource_content
from distro_tracker.core.utils.packages import package_hashdir
from .models import DebianContributor
from distro_tracker import vendor

import re
import yaml
import json
from debian import deb822
from debian.debian_support import AptPkgVersion
from debian import debian_support
from copy import deepcopy
from bs4 import BeautifulSoup as soup

try:
    import SOAPpy
except ImportError:
    pass

import logging
logger = logging.getLogger(__name__)


class RetrieveDebianMaintainersTask(BaseTask):
    """
    Retrieves (and updates if necessary) a list of Debian Maintainers.
    """
    def __init__(self, force_update=False, *args, **kwargs):
        super(RetrieveDebianMaintainersTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def execute(self):
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
    def __init__(self, force_update=False, *args, **kwargs):
        super(RetrieveLowThresholdNmuTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

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
        for line in response.iter_lines():
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

    def execute(self):
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


class UpdatePackageBugStats(BaseTask):
    """
    Updates the BTS bug stats for all packages (source, binary and pseudo).
    Creates :class:`distro_tracker.core.ActionItem` instances for packages
    which have bugs tagged help or patch.
    """
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

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdatePackageBugStats, self).__init__(*args, **kwargs)
        self.force_update = force_update
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
        Using the BTS SOAP interface, retrieves the statistics of bugs with a
        particular tag.

        :param tag: The tag for which the statistics are required.
        :type tag: string
        :param user: The email of the user who tagged the bug with the given
            tag.
        :type user: string

        :returns: A dict mapping package names to the count of bugs with the
            given tag.
        """
        url = 'https://bugs.debian.org/cgi-bin/soap.cgi'
        namespace = 'Debbugs/SOAP'
        server = SOAPpy.SOAPProxy(url, namespace)
        if user:
            bugs = server.get_usertag(user, tag)
            bugs = bugs[0]
        else:
            bugs = server.get_bugs('tag', tag)

        # Match each retrieved bug ID to a package and then find the aggregate
        # count for each package.
        bug_stats = {}
        statuses = server.get_status(bugs)
        statuses = statuses[0]
        for status in statuses:
            status = status['value']
            if status['done'] or status['fixed'] or \
                    status['pending'] == 'fixed':
                continue

            package_name = status['package']
            bug_stats.setdefault(package_name, 0)
            bug_stats[package_name] += 1

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
        url, _ = vendor.call('get_bug_tracker_url', package.name, 'source',
                             'patch')
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
            'merged_url': vendor.call(
                'get_bug_tracker_url', package.name, 'source',
                'patch-merged')[0],
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
            line = line.decode('utf-8', 'ignore')
            package_name, bug_counts = line.split(':', 1)
            # Merged counts are in parentheses so remove those before splitting
            # the numbers
            bug_counts = re.sub(r'[()]', ' ', bug_counts).split()
            try:
                bug_counts = [int(count) for count in bug_counts]
            except ValueError:
                logger.warning(
                    'Failed to parse bug information for {pkg}: {cnts}'.format(
                        pkg=package_name, cnts=bug_counts), exc_info=1)
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

        # Add in help bugs from the BTS SOAP interface
        try:
            help_bugs = self._get_tagged_bug_stats('help')
            self._extend_bug_stats(bug_stats, help_bugs, 'help')
        except:
            logger.exception("Could not get bugs tagged help")

        # Add in gift bugs from the BTS SOAP interface
        try:
            gift_bugs = self._get_tagged_bug_stats('gift',
                                                   'debian-qa@lists.debian.org')
            self._extend_bug_stats(bug_stats, gift_bugs, 'gift')
        except:
            logger.exception("Could not get bugs tagged gift")

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
                    'Failed to parse bug information for {pkg}: {cnts}'.format(
                        pkg=package_name, cnts=bug_counts))
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

    def execute(self):
        # Stats for source and pseudo packages is retrieved from a different
        # resource (with a different structure) than stats for binary packages.
        self.update_source_and_pseudo_bugs()
        self.update_binary_bugs()


class UpdateLintianStatsTask(BaseTask):
    """
    Updates packages' lintian stats.
    """
    ACTION_ITEM_TYPE_NAME = 'lintian-warnings-and-errors'
    ITEM_DESCRIPTION = 'lintian reports <a href="{url}">{report}</a>'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/lintian-action-item.html'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateLintianStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.lintian_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

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
        for line in response.iter_lines():
            package, stats = line.split(None, 1)
            stats = stats.split()
            try:
                all_stats[package] = {
                    category: int(count)
                    for count, category in zip(stats, categories)
                }
            except ValueError:
                logger.exception(
                    'Failed to parse lintian information for {pkg}: '
                    '{line}'.format(
                        pkg=package, line=line))
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

    def execute(self):
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


class UpdateTransitionsTask(BaseTask):
    REJECT_LIST_URL = 'https://ftp-master.debian.org/transitions.yaml'
    PACKAGE_TRANSITION_LIST_URL = (
        'https://release.debian.org/transitions/export/packages.yaml')

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateTransitionsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_yaml_resource(self, url):
        """
        Gets the YAML resource at the given URL and returns it as a Python
        object.
        """
        content = self.cache.get_content(url)
        return yaml.safe_load(six.BytesIO(content))

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

    def execute(self):
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
    ACTION_ITEM_TYPE_NAME = 'debian-testing-migration'
    ITEM_DESCRIPTION = (
        "The package has not entered testing even though the delay is over")
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/testing-migration-action-item.html'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateExcusesTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _adapt_excuse_links(self, excuse):
        """
        If the excuse contains any anchor links, convert them to links to Distro
        Tracker package pages. Return the original text unmodified, otherwise.
        """
        re_anchor_href = re.compile(r'^#(.*)$')
        html = soup(excuse)
        for a_tag in html.findAll('a', {'href': True}):
            href = a_tag['href']
            match = re_anchor_href.match(href)
            if not match:
                continue
            package = match.group(1)
            a_tag['href'] = reverse('dtracker-package-page', kwargs={
                'package_name': package
            })

        return str(html)

    def _skip_excuses_item(self, item_text):
        if not item_text:
            return True
        # We ignore these excuses
        if "Section" in item_text or "Maintainer" in item_text:
            return True
        return False

    def _extract_problems_in_excuses_item(self, subline, package, problematic):
        if 'days old (needed' in subline:
            words = subline.split()
            age, limit = words[0], words[4]
            if age != limit:
                # It is problematic only when the age is strictly
                # greater than the limit.
                problematic[package] = {
                    'age': age,
                    'limit': limit,
                }

    def _get_excuses_and_problems(self, content_lines):
        """
        Gets the excuses for each package from the given iterator of lines
        representing the excuses html file.
        Also finds a list of packages which have not migrated to testing even
        after the necessary time has passed.

        :returns: A two-tuple where the first element is a dict mapping
            package names to a list of excuses. The second element is a dict
            mapping package names to a problem information. Problem information
            is a dict with the keys ``age`` and ``limit``.
        """
        try:
            # Skip all HTML before the first list
            while '<ul>' not in next(content_lines):
                pass
        except StopIteration:
            logger.warning("Invalid format of excuses file")
            return

        top_level_list = True
        package = ""
        package_excuses = {}
        problematic = {}
        excuses = []
        for line in content_lines:
            if isinstance(line, six.binary_type):
                line = line.decode('utf-8')
            if '</ul>' in line:
                # The inner list is closed -- all excuses for the package are
                # processed and we're back to the top-level list.
                top_level_list = True
                if '/' in package:
                    continue
                # Done with the package
                package_excuses[package] = deepcopy(excuses)
                continue

            if '<ul>' in line:
                # Entering the list of excuses
                top_level_list = False
                continue

            if top_level_list:
                # The entry in the top level list outside of an inner list is
                # a <li> item giving the name of the package for which the
                # excuses follow.
                words = re.split("[><() ]", line)
                package = words[6]
                excuses = []
                top_level_list = False
                continue

            line = line.strip()
            for subline in line.split("<li>"):
                if self._skip_excuses_item(subline):
                    continue

                # Check if there is a problem for the package.
                self._extract_problems_in_excuses_item(subline, package,
                                                       problematic)

                # Extract the rest of the excuses
                # If it contains a link to an anchor convert it to a link to a
                # package page.
                excuses.append(self._adapt_excuse_links(subline))

        return package_excuses, problematic

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
            section = package.main_entry.section
            if section not in ('contrib', 'non-free'):
                query_string = urlencode({'package': package.name})
                extra_data['check_why_url'] = (
                    'https://release.debian.org/migration/testing.pl'
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

    def _get_update_excuses_content(self):
        """
        Function returning the content of the update_excuses.html file as an
        terable of lines.
        Returns ``None`` if the content in the cache is up to date.
        """
        url = 'https://ftp-master.debian.org/testing/update_excuses.html'
        response, updated = self.cache.update(url, force=self.force_update)
        if not updated:
            return

        return response.iter_lines(decode_unicode=True)

    def execute(self):
        content_lines = self._get_update_excuses_content()
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
    ACTION_ITEM_TYPE_NAME = 'debian-build-logcheck'
    ITEM_DESCRIPTION = 'Build log checks report <a href="{url}">{report}</a>'
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/logcheck-action-item.html'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateBuildLogCheckStats, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_buildd_content(self):
        url = 'https://qa.debian.org/bls/logcheck.txt'
        return get_resource_content(url)

    def get_buildd_stats(self):
        content = self._get_buildd_content()
        stats = {}
        for line in content.splitlines():
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

    def execute(self):
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
    ACTION_ITEM_TYPE_NAMES = (
        'new-upstream-version',
        'watch-failure',
        'watch-file-broken',
        'watch-file-available',
    )
    ACTION_ITEM_TEMPLATES = {
        'new-upstream-version': "debian/new-upstream-version-action-item.html",
        'watch-failure': "debian/watch-failure-action-item.html",
        'watch-file-broken': "debian/watch-file-broken-action-item.html",
        'watch-file-available': "debian/watch-file-available-action-item.html",
    }
    ITEM_DESCRIPTIONS = {
        'new-upstream-version': lambda item: (
            'A new upstream version is available: '
            '<a href="{url}">{version}</a>'.format(
                url=item.extra_data['upstream_url'],
                version=item.extra_data['upstream_version'])),
        'watch-failure': lambda item: (
            'Problems while searching for a new upstream version'),
        'watch-file-broken': lambda item: (
            'Problem with the debian/watch file included in the package'),
        'watch-file-available': lambda item: (
            'An updated debian/watch file is '
            '<a href="https://qa.debian.org/cgi-bin/watchfile.cgi'
            '?package={package}">available</a>.'.format(
                package=item.package.name)),
    }
    ITEM_SEVERITIES = {
        'new-upstream-version': ActionItem.SEVERITY_HIGH,
        'watch-failure': ActionItem.SEVERITY_HIGH,
        'watch-file-broken': ActionItem.SEVERITY_LOW,
        'watch-file-available': ActionItem.SEVERITY_WISHLIST,
    }

    def __init__(self, force_update=False, *args, **kwargs):
        super(DebianWatchFileScannerUpdate, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_types = {
            type_name: ActionItemType.objects.create_or_update(
                type_name=type_name,
                full_description_template=self.ACTION_ITEM_TEMPLATES.get(
                    type_name, None))
            for type_name in self.ACTION_ITEM_TYPE_NAMES
        }

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_udd_dehs_content(self):
        url = 'https://qa.debian.org/cgi-bin/udd-dehs'
        return get_resource_content(url)

    def _get_watch_broken_content(self):
        url = 'https://qa.debian.org/watch/watch-broken.txt'
        return get_resource_content(url)

    def _get_watch_available_content(self):
        url = 'https://qa.debian.org/watch/watch-avail.txt'
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

    def get_udd_dehs_stats(self, stats):
        """
        Gets the DEHS stats from the UDD and puts them in the given ``stats``
        dictionary.
        The keys of the dict are package names.

        :returns: A a two-tuple where the first item is a list of packages
            which have new upstream versions and the second is a list of
            packages which have watch failures.
        """
        content = self._get_udd_dehs_content()
        dehs_data = yaml.safe_load(six.BytesIO(content))
        if not dehs_data:
            return [], []

        all_new_versions, all_failures = [], []
        for entry in dehs_data:
            package_name = entry['package']
            if 'status' in entry and 'Newer version' in entry['status']:
                stats.setdefault(package_name, {})
                stats[package_name]['new-upstream-version'] = {
                    'upstream_version': entry['upstream-version'],
                    'upstream_url': entry['upstream-url'],
                }
                all_new_versions.append(package_name)
            if 'warnings' in entry:
                stats.setdefault(package_name, {})
                stats[package_name]['watch-failure'] = {
                    'warning': entry['warnings'],
                }
                all_failures.append(package_name)

        return all_new_versions, all_failures

    def get_watch_broken_stats(self, stats):
        """
        Gets the stats of files which have broken watch files, as per
        `<https://qa.debian.org/watch/watch-broken.txt>`_.
        It updates the given dictionary ``stats`` to contain these stats
        as an additional key ``watch-file-broken`` for each package that has
        the stats.

        :returns: A list of packages which have broken watch files.
        """
        content = self._get_watch_broken_content().decode('utf-8')
        packages = []
        for package_name in content.splitlines():
            package_name = package_name.strip()
            stats.setdefault(package_name, {})
            # For now no extra data needed for this type of item.
            stats[package_name]['watch-file-broken'] = None
            packages.append(package_name)

        return packages

    def get_watch_available_stats(self, stats):
        """
        Gets the stats of files which have available watch files, as per
        `<https://qa.debian.org/watch/watch-avail.txt>`_.
        It updates the given dictionary ``stats`` to contain these stats
        as an additional key ``watch-file-available`` for each package that has
        the stats.

        :returns: A list of packages which have available watch files.
        """
        content = self._get_watch_available_content().decode('utf-8')
        packages = []
        for package_name in content.splitlines():
            package_name = package_name.strip()
            stats.setdefault(package_name, {})
            # For now no extra data needed for this type of item.
            stats[package_name]['watch-file-available'] = None
            packages.append(package_name)

        return packages

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

    def execute(self):
        stats = {}
        new_upstream_version, failures = self.get_udd_dehs_stats(stats)
        watch_broken = self.get_watch_broken_stats(stats)
        watch_available = self.get_watch_available_stats(stats)
        updated_packages_per_type = {
            'new-upstream-version': new_upstream_version,
            'watch-failure': failures,
            'watch-file-broken': watch_broken,
            'watch-file-available': watch_available,
        }

        # Remove obsolete action items for each of the categories...
        for item_type, packages in updated_packages_per_type.items():
            self._remove_obsolete_action_items(item_type, packages)

        packages = SourcePackageName.objects.filter(
            name__in=stats.keys())
        packages = packages.prefetch_related('action_items')

        # Update action items for each package
        for package in packages:
            for type_name in self.ACTION_ITEM_TYPE_NAMES:
                if type_name in stats[package.name]:
                    # method(package, stats[package.name][type_name])
                    self.update_action_item(
                        type_name, package, stats[package.name][type_name])


class UpdateSecurityIssuesTask(BaseTask):
    ACTION_ITEM_TYPE_NAME = 'debian-security-issue'
    ACTION_ITEM_TEMPLATE = 'debian/security-issue-action-item.html'
    ITEM_DESCRIPTION_TEMPLATE = "{count} security {issue}"

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateSecurityIssuesTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_issues_content(self):
        url = 'https://security-tracker.debian.org/tracker/data/pts/1'
        return get_resource_content(url)

    def get_issues_stats(self):
        """
        Gets package issue stats from Debian's security tracker.
        """
        content = self._get_issues_content()
        stats = {}
        for line in content.splitlines():
            package_name, count = line.rsplit(':', 1)
            try:
                count = int(count)
            except ValueError:
                continue
            stats[package_name] = count

        return stats

    def update_action_item(self, package, security_issue_count):
        """
        Updates the ``debian-security-issue`` action item for the given package
        based on the count of security issues.
        """
        action_item = package.get_action_item_for_type(self.action_item_type)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)

        action_item.short_description = self.ITEM_DESCRIPTION_TEMPLATE.format(
            count=security_issue_count,
            issue='issues' if security_issue_count > 1 else 'issue')
        action_item.extra_data = {
            'security_issues_count': security_issue_count,
        }
        action_item.save()

    def execute(self):
        stats = self.get_issues_stats()

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=stats.keys())

        packages = PackageName.objects.filter(name__in=stats.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.update_action_item(package, stats[package.name])


class UpdatePiuPartsTask(BaseTask):
    """
    Retrieves the piuparts stats for all the suites defined in the
    :data:`distro_tracker.project.local_settings.DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES`
    """
    ACTION_ITEM_TYPE_NAME = 'debian-piuparts-test-fail'
    ACTION_ITEM_TEMPLATE = 'debian/piuparts-action-item.html'
    ITEM_DESCRIPTION = 'piuparts found (un)installation error(s)'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdatePiuPartsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

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
                logger.info("There is no piuparts for suite: {}".format(suite))
                continue

            for line in content.splitlines():
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

    def execute(self):
        failing_packages = self.get_piuparts_stats()

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=failing_packages.keys())

        packages = SourcePackageName.objects.filter(
            name__in=failing_packages.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.create_action_item(package, failing_packages[package.name])


class UpdateReleaseGoalsTask(BaseTask):
    """
    Retrieves the release goals and any bugs associated with the release goal
    for all packages. Creates :class:`ActionItem` instances for packages which
    have such bugs.
    """
    ACTION_ITEM_TYPE_NAME = 'debian-release-goals-bugs'
    ACTION_ITEM_TEMPLATE = 'debian/release-goals-action-item.html'
    ITEM_DESCRIPTION = (
        "{count} bugs must be fixed to meet some Debian release goals")

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateReleaseGoalsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_release_goals_content(self):
        """
        :returns: A tuple consisting of contents of the release goals list and
            the release bug list. ``None`` if neither of the packages have
            been when compared to the cached resource.
        """
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        release_goals_url = 'https://release.debian.org/testing/goals.yaml'
        bugs_list_url = 'https://udd.debian.org/pts-release-goals.cgi'
        if not self.force_update and (
                not cache.is_expired(release_goals_url) and
                not cache.is_expired(bugs_list_url)):
            return

        release_goals_response, updated_release_goals = cache.update(
            release_goals_url, force=self.force_update)
        bug_list_response, updated_bug_list = cache.update(
            bugs_list_url, force=self.force_update)

        if updated_bug_list or updated_release_goals:
            return release_goals_response.content, bug_list_response.content

    def get_release_goals_stats(self):
        content = self._get_release_goals_content()
        if content is None:
            return

        release_goals_content, bug_list_content = content

        release_goals = yaml.safe_load(release_goals_content)
        release_goals_list = []
        if release_goals:
            release_goals_list = release_goals['release-goals']
        # Map (user, tag) tuples to the release goals.
        # This is used to match the bugs with the correct release goal.
        release_goals = {}
        for goal in release_goals_list:
            if 'bugs' in goal:
                user = goal['bugs']['user']
                for tag in goal['bugs']['usertags']:
                    release_goals[(user, tag)] = goal

        release_goal_stats = {}
        # Build a dict mapping package names to a list of bugs matched to a
        # release goal.
        bug_list = yaml.safe_load(bug_list_content) or []
        for bug in bug_list:
            user, tag = bug['email'], bug['tag']
            if (user, tag) not in release_goals:
                # Cannot match the bug with a release goal...
                continue
            release_goal = release_goals[(user, tag)]
            if release_goal['state'] != 'accepted':
                continue
            package = bug['source']
            release_goal_stats.setdefault(package, [])
            release_goal_stats[package].append({
                'name': release_goal['name'],
                'url': release_goal['url'],
                'id': bug['id'],
            })

        return release_goal_stats

    def update_action_item(self, package, bug_list):
        action_item = package.get_action_item_for_type(
            self.ACTION_ITEM_TYPE_NAME)
        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type)

        # Check if there were any changes to the package's stats since last
        # update.
        if action_item.extra_data:
            old_data = sorted(action_item.extra_data, key=lambda x: x['id'])
            bug_list = sorted(bug_list, key=lambda x: x['id'])
            if old_data == bug_list:
                # No need to update anything as nothing has changed
                return
        action_item.short_description = self.ITEM_DESCRIPTION.format(
            count=len(bug_list))
        action_item.extra_data = bug_list
        action_item.save()

    def execute(self):
        stats = self.get_release_goals_stats()
        if stats is None:
            return

        ActionItem.objects.delete_obsolete_items(
            item_types=[self.action_item_type],
            non_obsolete_packages=stats.keys())

        packages = PackageName.objects.filter(name__in=stats.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.update_action_item(package, stats[package.name])


class UpdateUbuntuStatsTask(BaseTask):
    """
    The task updates Ubuntu stats for packages. These stats are displayed in a
    separate panel.
    """
    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateUbuntuStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

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
        for line in content.splitlines():
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
        for line in content.splitlines():
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
        for line in content.splitlines():
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

    def execute(self):
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

    DUCK_LINK = 'http://duck.debian.net'
    # URL of the list of source packages with issues.
    DUCK_SP_LIST_URL = 'http://duck.debian.net/static/sourcepackages.txt'

    ACTION_ITEM_TYPE_NAME = 'debian-duck'
    ACTION_ITEM_TEMPLATE = 'debian/duck-action-item.html'
    ITEM_DESCRIPTION = 'The URL(s) for this package had some ' + \
        'recent persistent <a href="{issues_link}">issues</a>'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateDebianDuckTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_duck_urls_content(self):
        """
        Gets the list of packages with URL issues from
        duck.debian.net

        :returns: A array if source package names.
        """

        ducklist = get_resource_content(self.DUCK_SP_LIST_URL)
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

    def execute(self):
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
    ACTION_ITEM_TYPE_NAME = 'debian-wnpp-issue'
    ACTION_ITEM_TEMPLATE = 'debian/wnpp-action-item.html'
    ITEM_DESCRIPTION = '<a href="{url}">{wnpp_type}</a>'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateWnppStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_wnpp_content(self):
        url = 'https://qa.debian.org/data/bts/wnpp_rm'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        if not cache.is_expired(url):
            return
        response, updated = cache.update(url, force=self.force_update)
        if not updated:
            return
        return response.content

    def get_wnpp_stats(self):
        """
        Retrieves and parses the wnpp stats for all packages. WNPP stats
        include the WNPP type and the BTS bug id.

        :returns: A dict mapping package names to wnpp stats.
        """
        content = self._get_wnpp_content()
        if content is None:
            return

        wnpp_stats = {}
        for line in content.splitlines():
            line = line.strip()
            try:
                package_name, wnpp_type, bug_id = line.split('|')[0].split()
                bug_id = int(bug_id)
            except:
                # Badly formatted
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
        except:
            release = None
        action_item.short_description = self.ITEM_DESCRIPTION.format(
            url='https://bugs.debian.org/{}'.format(stats['bug_id']),
            wnpp_type=stats['wnpp_type'])
        action_item.extra_data = {
            'wnpp_info': stats,
            'release': release,
        }
        action_item.save()

    def update_depneedsmaint_action_item(self, package_needs_maintainer):
        short_description_template = (
            'The package depends on source packages which need '
            'a new maintainer.'
        )
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

            if package_needs_maintainer.name in action_item.extra_data:
                if action_item.extra_data == dependency.details:
                    # Nothing has changed
                    continue
            action_item.short_description = short_description_template
            action_item.extra_data[package_needs_maintainer.name] = \
                dependency.details

            action_item.save()

    def execute(self):
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

        packages = SourcePackageName.objects.filter(name__in=wnpp_stats.keys())
        packages = packages.prefetch_related('action_items')

        for package in packages:
            self.update_action_item(package, wnpp_stats[package.name])
            # Update action items for packages which depend on this one to
            # indicate that a dependency needs a new maintainer.
            if package.name in packages_need_maintainer:
                self.update_depneedsmaint_action_item(package)


class UpdateNewQueuePackages(BaseTask):
    """
    Updates the versions of source packages found in the NEW queue.
    """
    EXTRACTED_INFO_KEY = 'debian-new-queue-info'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateNewQueuePackages, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

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

    def execute(self):
        content = self._get_new_content()

        all_package_info = self.extract_package_info(content)

        packages = SourcePackageName.objects.filter(
            name__in=all_package_info.keys())

        with transaction.atomic():
            # Drop old entries
            PackageExtractedInfo.objects.filter(
                key=self.EXTRACTED_INFO_KEY).delete()
            # Prepare current entries
            extracted_info = []
            for package in packages:
                new_queue_info = PackageExtractedInfo(
                    key=self.EXTRACTED_INFO_KEY,
                    package=package,
                    value=all_package_info[package.name])
                extracted_info.append(new_queue_info)
            # Bulk create them
            PackageExtractedInfo.objects.bulk_create(extracted_info)


class UpdateDebciStatusTask(BaseTask):
    """
    Updates packages' debci status.
    """
    ACTION_ITEM_TYPE_NAME = 'debci-failed-tests'
    ITEM_DESCRIPTION = (
        'Debci reports <a href="{debci_url}">failed tests</a> '
        '(<a href="{log_url}">log</a>)'
    )
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debian/debci-action-item.html'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateDebciStatusTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.debci_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def get_debci_status(self):
        url = 'http://ci.debian.net/data/status/unstable/amd64/packages.json'
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
        if debci_status.get('status') == 'pass':
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
        url = 'http://ci.debian.net/packages/' + log_dir + '/' + \
            package_name + '/'
        log = 'http://ci.debian.net/data/packages/unstable/amd64/' + \
            log_dir + "/" + package_name + '/latest-autopkgtest/log'
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

    def execute(self):
        all_debci_status = self.get_debci_status()
        if all_debci_status is None:
            return

        with transaction.atomic():
            packages = []
            for result in all_debci_status:
                if result['status'] == 'fail':
                    try:
                        package = SourcePackageName.objects.get(
                            name=result['package'])
                        packages.append(package)
                        self.update_action_item(package, result)
                    except SourcePackageName.DoesNotExist:
                        pass

            # Remove action items for packages without failing tests.
            ActionItem.objects.delete_obsolete_items(
                [self.debci_action_item_type], packages)


class UpdateAutoRemovalsStatsTask(BaseTask):
    """
    A task for updating autoremovals information on all packages.
    """
    ACTION_ITEM_TYPE_NAME = 'debian-autoremoval'
    ACTION_ITEM_TEMPLATE = 'debian/autoremoval-action-item.html'
    ITEM_DESCRIPTION = 'Marked for autoremoval on {removal_date}: {bugs}'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateAutoRemovalsStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def get_autoremovals_stats(self):
        """
        Retrieves and parses the autoremoval stats for all packages.
        Autoremoval stats include the BTS bugs id.

        :returns: A dict mapping package names to autoremoval stats.
        """
        content = get_resource_content(
            'https://udd.debian.org/cgi-bin/autoremovals.yaml.cgi')
        if content:
            return yaml.safe_load(six.BytesIO(content))

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
        all_bugs = stats['bugs'] + bugs_dependencies
        link = '<a href="https://bugs.debian.org/{}">{}</a>'

        action_item.short_description = self.ITEM_DESCRIPTION.format(
            removal_date=stats['removal_date'].strftime('%d %B'),
            bugs=', '.join(link.format(bug, bug) for bug in all_bugs))

        action_item.extra_data = {
            'stats': stats,
            'removal_date': stats['removal_date'].strftime('%a %d %b %Y'),
            'bugs': ', '.join(link.format(bug, bug) for bug in stats['bugs']),
            'bugs_dependencies': ', '.join(
                link.format(bug, bug) for bug in bugs_dependencies),
            'buggy_dependencies': ' and '.join(
                ['<a href="/pkg/{}">{}</a>'.format(
                    reverse(
                        'dtracker-package-page',
                        kwargs={'package_name': p}),
                    p) for p in buggy_dependencies])}
        action_item.save()

    def execute(self):
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
    key to PackageExtractedInfo if it does.
    """
    EXTRACTED_INFO_KEY = 'screenshots'

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdatePackageScreenshotsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_screenshots(self):
        url = 'https://screenshots.debian.net/json/packages'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return

        data = json.loads(response.text)
        return data

    def execute(self):
        content = self._get_screenshots()

        packages_with_screenshots = []
        for item in content['packages']:
            try:
                package = SourcePackageName.objects.get(name=item['name'])
                packages_with_screenshots.append(package)
            except SourcePackageName.DoesNotExist:
                pass

        with transaction.atomic():
            PackageExtractedInfo.objects.filter(key='screenshots').delete()

            extracted_info = []
            for package in packages_with_screenshots:
                try:
                    screenshot_info = package.packageextractedinfo_set.get(
                        key=self.EXTRACTED_INFO_KEY)
                    screenshot_info.value['screenshots'] = 'true'
                except PackageExtractedInfo.DoesNotExist:
                    screenshot_info = PackageExtractedInfo(
                        key=self.EXTRACTED_INFO_KEY,
                        package=package,
                        value={'screenshots': 'true'})

                extracted_info.append(screenshot_info)

            PackageExtractedInfo.objects.bulk_create(extracted_info)


class UpdateBuildReproducibilityTask(BaseTask):
    BASE_URL = 'https://reproducible.debian.net'
    ACTION_ITEM_TYPE_NAME = 'debian-build-reproducibility'
    ACTION_ITEM_TEMPLATE = 'debian/build-reproducibility-action-item.html'
    ITEM_DESCRIPTION = {
        'blacklisted': '<a href="{url}">Blacklisted</a> from build '
                       'reproducibility testing',
        'FTBFS': '<a href="{url}">Fails to build</a> during reproducibility '
                 'testing',
        'reproducible': None,
        'unreproducible': '<a href="{url}">Does not build reproducibly</a> '
                          'during testing',
        '404': None,
        'not for us': None,
    }

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateBuildReproducibilityTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ACTION_ITEM_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def get_build_reproducibility(self):
        url = '{}/reproducible.json'.format(self.BASE_URL)
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

        url = "{}/rb-pkg/{}.html".format(self.BASE_URL, package.name)
        action_item.short_description = description.format(url=url)
        action_item.save()
        return True

    def execute(self):
        reproducibilities = self.get_build_reproducibility()
        if reproducibilities is None:
            return

        with transaction.atomic():
            PackageExtractedInfo.objects.filter(key='reproducibility').delete()

            packages = []
            extracted_info = []

            for name, status in reproducibilities.items():
                try:
                    package = SourcePackageName.objects.get(name=name)
                    if self.update_action_item(package, status):
                        packages.append(package)
                except SourcePackageName.DoesNotExist:
                    continue

                reproducibility_info = PackageExtractedInfo(
                    key='reproducibility',
                    package=package,
                    value={'reproducibility': status})
                extracted_info.append(reproducibility_info)

            ActionItem.objects.delete_obsolete_items([self.action_item_type],
                                                     packages)
            PackageExtractedInfo.objects.bulk_create(extracted_info)
