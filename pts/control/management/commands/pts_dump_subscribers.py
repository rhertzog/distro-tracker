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
from optparse import make_option

from pts.core.models import Package
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
    )

    help = ("Get the subscribers for the given packages.\n"
            "Outputs subscribers to all packges if no arguments are given")

    def handle(self, *args, **kwargs):
        inactive = kwargs['inactive']
        if len(args) == 0:
            self._output(
                ((package.name, package) for package in Package.objects.all()),
                inactive)
        else:
            self._output(
                ((package_name, get_or_none(Package, name=package_name))
                 for package_name in args),
                inactive
            )

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
