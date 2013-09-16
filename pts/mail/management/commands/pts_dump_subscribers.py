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
Implements the command which outputs all subscribers for given packages.
"""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from optparse import make_option

import json

from pts.core.models import PackageName
from pts.core.utils import get_or_none


class Command(BaseCommand):
    """
    A Django management command which outputs all subscribers for the given
    packages or for all packages, depending on the input parameters.
    emails.
    """
    args = '[package ...]'

    option_list = BaseCommand.option_list + (
        make_option('--inactive',
                    action='store_true',
                    dest='inactive',
                    default=False,
                    help='Show inactive (non-confirmed) subscriptions'),
        make_option('--json',
                    action='store_true',
                    dest='json',
                    default=False,
                    help='Output the result encoded as a JSON object'),
        make_option('--udd-format',
                    action='store_true',
                    dest='udd_format',
                    default=False,
                    help='Output the result in a UDD compatible format'),
    )

    help = ("Get the subscribers for the given packages.\n"
            "Outputs subscribers to all packges if no arguments are given")

    def warn(self, message):
        if self.verbose:
            self.stderr.write("Warning: {}".format(message))

    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs.get('verbosity', 1)) > 1
        inactive = kwargs['inactive']
        self.out_packages = {}
        if len(args) == 0:
            for package in PackageName.objects.all():
                self.output_package(package, inactive)
        else:
            for package_name in args:
                package = get_or_none(PackageName, name=package_name)
                if package:
                    self.output_package(package, inactive)
                else:
                    self.warn("{package} does not exist.".format(
                            package=str(package_name)))

        format = 'default'
        if kwargs['json']:
            format = 'json'
        elif kwargs.get('udd_format', False):
            format = 'udd'

        return self.render_packages(format)

    def output_package(self, package, inactive=False):
        """
        Includes the subscribers of the given package in the output.

        :param package: Package whose subscribers should be output
        :type package: :py:class:`Package <pts.core.models.Package>`

        :param inactive: Signals whether inactive or active subscriptions
            should be output.
        """
        subscriptions = package.subscription_set.filter(active=not inactive)
        self.out_packages[package.name] = [
            str(sub.email_user)
            for sub in subscriptions
        ]

    def render_packages(self, format):
        """
        Prints the packages and their subscribers to the output stream.

        :param use_json: If ``True`` the output is rendered as JSON.
            Otherwise, a legacy format is used.
        :type use_json: Boolean
        """
        if format == 'json':
            self.stdout.write(json.dumps(self.out_packages))
        elif format == 'udd':
            for package, subscribers in self.out_packages.items():
                subscriber_out = ', '.join(str(email) for email in subscribers)
                self.stdout.write("{}\t{}".format(package, subscriber_out))
        else:
            for package, subscribers in self.out_packages.items():
                subscriber_out = ' '.join(str(email) for email in subscribers)
                self.stdout.write(package + ' => [ ' + subscriber_out + ' ]')
