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
from pts.core.tasks import BaseTask
from pts.core.models import Developer
from .models import DebianDeveloper
import requests
import re


class RetrieveLowThresholdNmuTask(BaseTask):
    def _retrieve_emails(self):
        response = requests.get('http://wiki.debian.org/LowThresholdNmu?action=raw')
        response.raise_for_status()

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
            qs = DebianDeveloper.objects.filter(agree_with_low_threshold_nmu=True)
            qs.update(agree_with_low_threshold_nmu=False)
            for email in emails:
                developer, _ = Developer.objects.get_or_create(email=email)
                developer, _ = DebianDeveloper.objects.get_or_create(developer=developer)

                developer.agree_with_low_threshold_nmu = True
                developer.save()
