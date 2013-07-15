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
from pts.core.models import Developer
from pts.core.utils.http import HttpCache
from .models import DebianContributor
import requests
import re
from debian import deb822


class RetrieveDebianMaintainersTask(BaseTask):
    def execute(self):
        cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        url = "http://ftp-master.debian.org/dm.txt"
        if not cache.is_expired(url):
            # No need to do anything when the previously cached value is fresh
            return
        response, updated = cache.update(url)
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
            qs = DebianContributor.objects.filter(debian_maintainer=True)
            qs.update(debian_maintainer=False)

            for email, packages in maintainers.items():
                developer, _ = Developer.objects.get_or_create(email=email)
                developer, _ = DebianContributor.objects.get_or_create(
                    developer=developer)

                developer.debian_maintainer = True
                developer.allowed_packages = packages
                developer.save()


class RetrieveLowThresholdNmuTask(BaseTask):
    def _retrieve_emails(self):
        url = 'http://wiki.debian.org/LowThresholdNmu?action=raw'
        cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
        if not cache.is_expired(url):
            return
        response, updated = cache.update(url)
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
                developer, _ = Developer.objects.get_or_create(email=email)
                developer, _ = DebianContributor.objects.get_or_create(developer=developer)

                developer.agree_with_low_threshold_nmu = True
                developer.save()
