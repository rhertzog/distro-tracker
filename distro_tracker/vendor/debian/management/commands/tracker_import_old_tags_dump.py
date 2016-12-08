# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
from __future__ import unicode_literals
from django.db import transaction
from django.core.management.base import BaseCommand

from distro_tracker.core.models import Subscription
from distro_tracker.core.models import Keyword
from distro_tracker.core.models import UserEmail
from distro_tracker.core.models import EmailSettings

import sys


class Command(BaseCommand):
    """
    Import the old PTS user default keywords and package-specific keywords.
    The expected input is the output of the ``bin/dump-tags.pl`` file on stdin.
    """
    stdin = sys.stdin

    def write(self, message):
        if self.verbose:
            self.stdout.write(message)

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs.get('verbosity', 1)) > 1

        # Each line can have one of the two possible formats:
        # <email>: <tag1>,<tag2>,...
        # or
        # <email>#<package-name>: <tag1>,<tag2>

        for line in self.stdin:
            email, tags = line.rsplit(':', 1)
            tags = tags.strip().split(',')
            tags = [tag.strip() for tag in tags]
            # Map the keyword names that have been changed to their new values
            legacy_mapping = {
                'katie-other': 'archive',
                'buildd': 'build',
                'ddtp': 'translation',
                'cvs': 'vcs',
            }
            keywords = [
                legacy_mapping.get(tag, tag)
                for tag in tags
            ]
            keywords = Keyword.objects.filter(name__in=keywords)
            email = email.strip()
            if '#' in email:
                # A subscription specific set of keywords
                email, package = email.split('#', 1)
                try:
                    subscription = Subscription.objects.get(
                        package__name=package,
                        email_settings__user_email__email=email)
                except Subscription.DoesNotExist:
                    continue
                subscription.keywords.clear()
                for keyword in keywords:
                    subscription.keywords.add(keyword)
            else:
                # User default keywords
                user_email, _ = UserEmail.objects.get_or_create(email=email)
                email_settings, _ = \
                    EmailSettings.objects.get_or_create(user_email=user_email)
                email_settings.default_keywords = keywords
