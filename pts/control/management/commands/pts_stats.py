# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from __future__ import print_function
from django.core.management.base import BaseCommand
from django.utils import timezone
from optparse import make_option

import json

from pts.core.models import Package, Subscription, EmailUser


class Command(BaseCommand):
    """
    A Django management command which outputs some statistics about the PTS.
    """
    option_list = BaseCommand.option_list + (
        make_option('--json',
                    action='store_true',
                    dest='json',
                    default=False,
                    help='Output the result encoded as a JSON object'),
    )

    help = (
        "Get some statistics about the Package Tracking System\n"
        "- Total number of source packages with at least one subscription\n"
        "- Total number of subscriptions\n"
        "- Total number of unique emails\n"
    )

    def handle(self, *args, **kwargs):

        from collections import OrderedDict
        # Necessary to keep ordering because of the legacy output format.
        stats = OrderedDict((
            ('package_number', Package.objects.count()),
            ('subscription_number', Subscription.objects.count()),
            ('date', timezone.now().strftime('%Y-%m-%d')),
            ('unique_emails_number', EmailUser.objects.count()),
        ))

        if kwargs['json']:
            self.stdout.write(json.dumps(stats))
        else:
            # Legacy output format
            self.stdout.write('Src pkg\tSubscr.\tDate\t\tNb email')
            self.stdout.write('\t'.join(map(str, stats.values())))

    def output_package(self, package, inactive=False):
        """
        Includes the subscribers of the given package in the output.
        """
        subscriptions = package.subscription_set.filter(active=not inactive)
        self.out_packages[package.name] = [
            str(sub.email_user)
            for sub in subscriptions
        ]

    def render_packages(self, use_json=False):
        """
        Prints the packages and their subscribers to the output stream.
        """
        if use_json:
            self.stdout.write(json.dumps(self.out_packages))
        else:
            for package, subscribers in self.out_packages.items():
                subscriber_out = ' '.join(str(email) for email in subscribers)
                self.stdout.write(package + ' => [ ' + subscriber_out + ' ]')

    def _output(self, packages, inactive=False):
        """
        Outputs the subscribers for the packages found in the iterable
        ``packages``. Members of the iterable should be tuples where the first
        member is the package name and the second is the ``Package`` object.
        """
        for package_name, package in packages:
            if not package:
                self.stdout.write("Warning: {package} does not exist.".format(
                    package=str(package_name)))
            else:
                subscriptions = package.subscription_set.filter(
                    active=not inactive)
                out = [
                    '{package} '.format(package=package_name),
                    ' => [ ',
                    ' '.join(str(sub.email_user) for sub in subscriptions),
                    ' ]'
                ]
                self.stdout.write(''.join(out))
