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
Implements the command which outputs statistics.
"""
from __future__ import unicode_literals
from __future__ import print_function
from django.core.management.base import BaseCommand
from django.utils import timezone

import json

from distro_tracker.core.models import SourcePackageName, Subscription
from distro_tracker.core.models import UserEmail


class Command(BaseCommand):
    """
    A Django management command which outputs some statistics.
    """

    help = (
        "Get some statistics about the package tracker:\n"
        "- Total number of source packages with at least one subscription\n"
        "- Total number of subscriptions\n"
        "- Total number of unique emails\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output the result encoded as a JSON object'
        )

    def handle(self, *args, **kwargs):

        from collections import OrderedDict
        # Necessary to keep ordering because of the legacy output format.
        stats = OrderedDict((
            ('package_number',
             SourcePackageName.objects.all_with_subscribers().count()),
            ('subscription_number', Subscription.objects.count()),
            ('date', timezone.now().strftime('%Y-%m-%d')),
            ('unique_emails_number', UserEmail.objects.count()),
        ))

        if kwargs['json']:
            self.stdout.write(json.dumps(stats))
        else:
            # Legacy output format
            self.stdout.write('Src pkg\tSubscr.\tDate\t\tNb email')
            self.stdout.write('\t'.join(map(str, stats.values())))
