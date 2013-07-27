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

from pts.core.tasks import BaseTask
from pts.core.models import ContributorEmail
from pts.core.models import PackageBugStats
from pts.core.models import BinaryPackageBugStats
from pts.core.models import PackageName
from pts.core.models import BinaryPackageName
from pts.core.utils.http import HttpCache
from .models import DebianContributor
import re
from debian import deb822

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
