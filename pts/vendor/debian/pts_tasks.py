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
from django.conf import settings
from django.utils import six
from django.core.urlresolvers import reverse

from pts.core.tasks import BaseTask
from pts.core.models import ContributorEmail
from pts.core.models import PackageBugStats
from pts.core.models import BinaryPackageBugStats
from pts.core.models import PackageName
from pts.core.models import BinaryPackageName
from pts.vendor.debian.models import LintianStats
from pts.vendor.debian.models import PackageTransition
from pts.vendor.debian.models import PackageExcuses
from pts.core.utils.http import HttpCache
from .models import DebianContributor
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

    def _get_response(self, url):
        """
        Helper method which returns either the resource at the given URL or
        ``None``, depending on the :attr:`UpdatePackageBugStats.force_update`
        flag and cache status.

        :param url: The URL of the resource to retrieve.

        :returns None: If the resource found at the given URL is still fresh in
            the cache and the :attr:`UpdatePackageBugStats.force_update` was
            set to ``False``
        :returns requests.Response: If the cached resource has expired or
            :attr:`UpdatePackageBugStats.force_update` was set to ``True``
        """
        if not self.force_update and not self.cache.is_expired(url):
            return
        response, updated = self.cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return
        return response

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


    def update_source_and_pseudo_bugs(self):
        """
        Performs the update of bug statistics for source and pseudo packages.
        """
        url = 'http://udd.debian.org/cgi-bin/ddpo-bugs.cgi'
        response = self._get_response(url)
        if not response:
            return

        # Each line in the response should be bug stats for a single package
        bug_stats = {}
        for line in response.iter_lines():
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

        # Add in help bugs from the BTS SOAP interface
        try:
            help_bugs = self._get_tagged_bug_stats('help')
            self._extend_bug_stats(bug_stats, help_bugs, 'help')
        except:
            logger.exception("Could not get bugs tagged help")

        # Add in gift bugs from the BTS SOAP interface
        try:
            gift_bugs = self._get_tagged_bug_stats('gift', 'debian-qa@lists.debian.org')
            self._extend_bug_stats(bug_stats, help_bugs, 'help')
        except:
            logger.exception("Could not get bugs tagged gift")

        with transaction.commit_on_success():
            # Clear previous stats
            PackageBugStats.objects.all().delete()
            packages = PackageName.objects.filter(name__in=bug_stats.keys())
            # Create new stats in a single query
            stats = [
                PackageBugStats(package=package, stats=bug_stats[package.name])
                for package in packages
            ]
            PackageBugStats.objects.bulk_create(stats)

    def update_binary_bugs(self):
        """
        Performs the update of bug statistics for binary packages.
        """
        url = 'http://udd.debian.org/cgi-bin/bugs-binpkgs-pts.cgi'
        response = self._get_response(url)
        if not response:
            return

        # Extract known binary package bug stats: each line is a separate pkg
        bug_stats = {}
        for line in response.iter_lines():
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
    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateLintianStatsTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

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

    def execute(self):
        all_lintian_stats = self.get_lintian_stats()
        if not all_lintian_stats:
            return

        # Discard all old stats
        LintianStats.objects.all().delete()
        # Create all the new stats in a single SQL query.
        packages = PackageName.objects.filter(name__in=all_lintian_stats.keys())
        stats = [
            LintianStats(package=package, stats=all_lintian_stats[package.name])
            for package in packages
        ]
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
                    # Skip transitions with an unwated status
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
    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateExcusesTask, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.cache = HttpCache(settings.PTS_CACHE_DIRECTORY)

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

    def _get_excuses(self, content_lines):
        """
        Gets the excuses for each package from the given iterator of lines
        representing the excuses html file.
        Returns them as a dict mapping package names to a list of excuses.
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

                # Extract the rest of the excuses
                # If it contains a link to an anchor convert it to a link to a
                # package page.
                excuses.append(self._adapt_excuse_links(subline))

        return package_excuses

    def execute(self):
        url = 'http://ftp-master.debian.org/testing/update_excuses.html'
        response, updated = self.cache.update(url, force=self.force_update)
        if not updated:
            return

        content_lines = response.iter_lines()
        package_excuses = self._get_excuses(content_lines)
        if not package_excuses:
            return

        PackageExcuses.objects.all().delete()
        # Save the excuses now
        packages = PackageName.objects.filter(name__in=package_excuses.keys())
        excuses = [
            PackageExcuses(
                package=package,
                excuses=package_excuses[package.name])
            for package in packages
        ]
        PackageExcuses.objects.bulk_create(excuses)
