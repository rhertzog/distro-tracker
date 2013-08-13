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
Debian-specific tasks.
"""

from __future__ import unicode_literals
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.utils import six
from django.utils.http import urlencode
from django.core.urlresolvers import reverse

from pts.core.tasks import BaseTask
from pts.core.models import ActionItem, ActionItemType
from pts.core.models import ContributorEmail
from pts.core.models import PackageBugStats
from pts.core.models import BinaryPackageBugStats
from pts.core.models import PackageName
from pts.core.models import SourcePackageName
from pts.core.models import BinaryPackageName
from pts.vendor.debian.models import LintianStats
from pts.vendor.debian.models import BuildLogCheckStats
from pts.vendor.debian.models import PackageTransition
from pts.vendor.debian.models import PackageExcuses
from pts.core.utils.http import HttpCache
from pts.core.utils.http import get_resource_content
from .models import DebianContributor
from pts import vendor

import re
import SOAPpy
import yaml
from debian import deb822
from copy import deepcopy
from BeautifulSoup import BeautifulSoup as soup

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
        cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        url = "http://ftp-master.debian.org/dm.txt"
        if not self.force_update and not cache.is_expired(url):
            # No need to do anything when the previously cached value is fresh
            return
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            # No need to do anything if the cached item was still not updated
            return

        maintainers = {}
        for stanza in deb822.Deb822.iter_paragraphs(response.iter_lines()):
            if 'Uid' in stanza and 'Allow' in stanza:
                # Allow is a comma-separated string of 'package (DD fpr)' items,
                # where DD fpr is the fingerprint of the DD that granted the
                # permission
                name, email = stanza['Uid'].rsplit(' ', 1)
                email = email.strip('<>')
                for pair in stanza['Allow'].split(','):
                    pair = pair.strip()
                    pkg, dd_fpr = pair.split()
                    pkg = pkg.encode('utf-8')
                    maintainers.setdefault(email, [])
                    maintainers[email].append(pkg)

        # Now update the developer information
        with transaction.commit_on_success():
            # Reset all old maintainers first.
            qs = DebianContributor.objects.filter(is_debian_maintainer=True)
            qs.update(is_debian_maintainer=False)

            for email, packages in maintainers.items():
                email, _ = ContributorEmail.objects.get_or_create(email=email)
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
        url = 'http://wiki.debian.org/LowThresholdNmu?action=raw'
        cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        if not self.force_update and not cache.is_expired(url):
            return
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return

        emails = []
        devel_php_RE = re.compile(
            r'http://qa\.debian\.org/developer\.php\?login=([^\s&|]+)')
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
        with transaction.commit_on_success():
            # Reset all threshold flags first.
            qs = DebianContributor.objects.filter(agree_with_low_threshold_nmu=True)
            qs.update(agree_with_low_threshold_nmu=False)
            for email in emails:
                email, _ = ContributorEmail.objects.get_or_create(email=email)
                contributor, _ = DebianContributor.objects.get_or_create(
                    email=email)

                contributor.agree_with_low_threshold_nmu = True
                contributor.save()


class UpdatePackageBugStats(BaseTask):
    """
    Updates the BTS bug stats for all packages (source, binary and pseudo).
    Creates :class:`pts.core.ActionItem` instances for packages which have bugs
    tagged help or patch.
    """
    PATCH_BUG_ACTION_ITEM_TYPE_NAME = 'debian-patch-bugs-warning'
    HELP_BUG_ACTION_ITEM_TYPE_NAME = 'debian-help-bugs-warning'

    PATCH_ITEM_SHORT_DESCRIPTION = (
        '<a href="{url}">{count}</a> tagged patch in the '
        '<abbr title="Bug Tracking System">BTS</abbr>')
    HELP_ITEM_SHORT_DESCRIPTION = (
        '<a href="{url}">{count}</a> tagged help in the '
        '<abbr title="Bug Tracking System">BTS</abbr>')

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
        self.cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        # The :class:`pts.core.models.ActionItemType` instances which this task
        # can create.
        self.patch_item_type = ActionItemType.objects.create_or_update(
            type_name=self.PATCH_BUG_ACTION_ITEM_TYPE_NAME,
            full_description_template='debian/patch-bugs-action-item.html')
        self.help_item_type = ActionItemType.objects.create_or_update(
            type_name=self.HELP_BUG_ACTION_ITEM_TYPE_NAME,
            full_description_template='debian/help-bugs-action-item.html')

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
        url = 'http://bugs.debian.org/cgi-bin/soap.cgi'
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
            if status['done'] or status['fixed'] or status['pending'] == 'fixed':
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
        Creates a :class:`pts.core.models.ActionItem` instance for the given
        package if it contains any bugs tagged patch.

        :param package: The package for which the action item should be
            updated.
        :type package: :class:`pts.core.models.PackageName`
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
        url, _ = vendor.call('get_bug_tracker_url', package.name, 'source', 'patch')
        if not url:
            url = ''
        # Include the bug count in the short description
        count = '{bug_count} bug'.format(bug_count=bug_count)
        if bug_count > 1:
            count += 's'
        action_item.short_description = self.PATCH_ITEM_SHORT_DESCRIPTION.format(
            url=url, count=count)
        # Set additional URLs and merged bug count in the extra data for a full
        # description
        action_item.extra_data = {
            'bug_count': bug_count,
            'merged_count': bug_stats['patch'].get('merged_count', 0),
            'url': url,
            'merged_url': vendor.call(
                'get_bug_tracker_url', package.name, 'source', 'patch-merged')[0],
        }
        action_item.save()

    def _create_help_bug_action_item(self, package, bug_stats):
        """
        Creates a :class:`pts.core.models.ActionItem` instance for the given
        package if it contains any bugs tagged help.

        :param package: The package for which the action item should be
            updated.
        :type package: :class:`pts.core.models.PackageName`
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
        url, _ = vendor.call('get_bug_tracker_url', package.name, 'source', 'help')
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
        Method which creates a :class:`pts.core.models.ActionItem` instance
        for a package based on the given package stats.

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
        url = 'http://udd.debian.org/cgi-bin/ddpo-bugs.cgi'
        response_content = get_resource_content(url)
        if not response_content:
            return

        # Each line in the response should be bug stats for a single package
        bug_stats = {}
        for line in response_content.splitlines():
            line = line.decode('utf-8')
            package_name, bug_counts = line.split(':', 1)
            # Merged counts are in parentheses so remove those before splitting
            # the numbers
            bug_counts = re.sub(r'[()]', ' ', bug_counts).split()
            try:
                bug_counts = [int(count) for count in bug_counts]
            except ValueError:
                logger.exception(
                    'Failed to parse bug information for {pkg}: {cnts}'.format(
                        pkg=package_name, cnts=bug_counts))
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
        obsolete_items = ActionItem.objects.filter(
            Q(item_type=self.patch_item_type) | Q(item_type=self.help_item_type))
        obsolete_items = obsolete_items.exclude(package__name__in=package_names)
        obsolete_items.delete()

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
            gift_bugs = self._get_tagged_bug_stats('gift', 'debian-qa@lists.debian.org')
            self._extend_bug_stats(bug_stats, gift_bugs, 'gift')
        except:
            logger.exception("Could not get bugs tagged gift")

        with transaction.commit_on_success():
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
        url = 'http://udd.debian.org/cgi-bin/bugs-binpkgs-pts.cgi'
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

        with transaction.commit_on_success():
            # Clear previous stats
            BinaryPackageBugStats.objects.all().delete()
            packages = BinaryPackageName.objects.filter(name__in=bug_stats.keys())
            # Create new stats in a single query
            stats = [
                BinaryPackageBugStats(package=package, stats=bug_stats[package.name])
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

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateLintianStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.lintian_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template='debian/lintian-action-item.html')

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def get_lintian_stats(self):
        url = 'http://lintian.debian.org/qa-list.txt'
        cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
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
                    'Failed to parse lintian information for {pkg}: {line}'.format(
                        pkg=package, line=line))
                continue

        return all_stats

    def update_action_item(self, package, lintian_stats):
        """
        Updates the :class:`ActionItem` for the given package based on the
        :class:`LintianStats <pts.vendor.debian.models.LintianStats` given in
        ``package_stats``. If the package has errors or warnings an
        :class:`ActionItem` is created.
        """
        package_stats = lintian_stats.stats
        warnings, errors = (
            package_stats.get('warnings'), package_stats.get('errors', 0))
        # Get the old action item for this warning, if it exists.
        lintian_action_item = package.get_action_item_for_type(
            self.lintian_action_item_type.type_name)
        if warnings or errors:
            # The item didn't previously have an action item: create it now
            if lintian_action_item is None:
                lintian_action_item = ActionItem(
                    package=package,
                    item_type=self.lintian_action_item_type,
                    short_description='lintian reports errors or warnings')

            lintian_action_item.extra_data = {
                'warnings': warnings,
                'errors': errors,
                'lintian_url': lintian_stats.get_lintian_url()
            }
            lintian_action_item.save()
        else:
            if lintian_action_item:
                # If the item previously existed, delete it now since there
                # are no longer any warnings/errors.
                lintian_action_item.delete()

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
        obsolete_items = ActionItem.objects.filter(
            item_type=self.lintian_action_item_type)
        obsolete_items = obsolete_items.exclude(package__in=packages)
        obsolete_items.delete()

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
    REJECT_LIST_URL = 'http://ftp-master.debian.org/transitions.yaml'
    PACKAGE_TRANSITION_LIST_URL = (
        'http://release.debian.org/transitions/export/packages.yaml')

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateTransitionsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.PTS_CACHE_DIRECTORY)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_yaml_resource(self, url):
        """
        Gets the YAML resource at the given URL and returns it as a Python
        object.
        """
        content = self.cache.get_content(url)
        return yaml.load(six.BytesIO(content))

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
            for transition_name, data in package_transitions[package.name].items():
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

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateExcusesTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        self.action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template='debian/testing-migration-action-item.html')

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _adapt_excuse_links(self, excuse):
        """
        If the excuse contains any anchor links, convert them to links to PTS
        package pages. Return the original text unmodified, otherwise.
        """
        re_anchor_href = re.compile(r'^#(.*)$')
        html = soup(excuse)
        for a_tag in html.findAll('a', {'href': True}):
            href = a_tag['href']
            match = re_anchor_href.match(href)
            if not match:
                continue
            package = match.group(1)
            a_tag['href'] = reverse('pts-package-page', kwargs={
                'package_name': package
            })

        return str(html)

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

            component = 'main'
            line = line.strip()
            for subline in line.split("<li>"):
                if not subline:
                    continue
                # We ignore these excuses
                if 'Section:' in subline:
                    component = re.sub(r'Section: *(.*)', '\\1', subline)
                    continue
                if 'Maintainer:' in subline:
                    continue

                # Check if there is a problem for the package.
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

                # Extract the rest of the excuses
                # If it contains a link to an anchor convert it to a link to a
                # package page.
                excuses.append(self._adapt_excuse_links(subline))

        return package_excuses, problematic

    def _create_action_item(self, package, extra_data):
        """
        Creates a :class:`pts.core.models.ActionItem` for the given package
        including the given extra data. The item indicates that there is a
        problem with the package migrating to testing.
        """
        action_item = package.get_action_item_for_type(self.ACTION_ITEM_TYPE_NAME)
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
                    'http://release.debian.org/migration/testing.pl'
                    '?{query_string}'.format(query_string=query_string))

        action_item.extra_data = extra_data
        action_item.save()

    def _remove_obsolete_action_items(self, problematic):
        """
        Remove action items for packages which are no longer problematic.
        """
        obsolete_items = ActionItem.objects.filter(
            item_type=self.action_item_type)
        obsolete_items = obsolete_items.exclude(
            package__name__in=problematic.keys())
        obsolete_items.delete()

    def _get_update_excuses_content(self):
        """
        Function returning the content of the update_excuses.html file as an
        terable of lines.
        Returns ``None`` if the content in the cache is up to date.
        """
        url = 'http://ftp-master.debian.org/testing/update_excuses.html'
        response, updated = self.cache.update(url, force=self.force_update)
        if not updated:
            return

        content_lines = response.iter_lines()

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
    ITEM_DESCRIPTION = "Build log checks report {report}"

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateBuildLogCheckStats, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        self.action_item_type, _ = ActionItemType.objects.get_or_create(
            type_name=self.ACTION_ITEM_TYPE_NAME)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def _get_buildd_content(self):
        url = 'http://qa.debian.org/bls/logcheck.txt'
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

    def _remove_obsolete_action_items(self, stats):
        obsolete_items = ActionItem.objects.filter(item_type=self.action_item_type)
        obsolete_items = obsolete_items.exclude(package__name__in=stats.keys())
        obsolete_items.delete()

    def create_action_item(self, package, stats):
        """
        Creates a :class:`pts.core.models.ActionItem` instance for the given
        package if the build logcheck stats indicate
        """
        action_item = package.get_action_item_for_type(self.ACTION_ITEM_TYPE_NAME)

        errors = stats.get('errors', 0) > 0
        warnings = stats.get('warnings', 0) > 0

        if not errors and not warnings:
            # Remove the previous action item since the package no longer has
            # errors/warnings.
            if action_item is not None:
                action_item.delete()
            return

        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_item_type,
                full_description_template='debian/logcheck-action-item.html')

        if errors and warnings:
            report = 'errors and warnings'
            action_item.set_severity('high')
        elif errors:
            report = 'errors'
            action_item.set_severity('high')
        elif warnings:
            report = 'warnings'
            action_item.set_severity('low')

        action_item.short_description = self.ITEM_DESCRIPTION.format(report=report)
        action_item.extra_data = stats
        action_item.save()


    def execute(self):
        # Build a dict with stats from both buildd and clang
        stats = self.get_buildd_stats()

        BuildLogCheckStats.objects.all().delete()
        self._remove_obsolete_action_items(stats)

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
