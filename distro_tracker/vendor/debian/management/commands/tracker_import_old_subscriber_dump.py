# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
from django.db import transaction
from django.core.management.base import BaseCommand

from distro_tracker.core.models import Subscription

import sys


class Command(BaseCommand):
    """
    Import the old PTS package subscriptions.
    The expected input is the output of the ``bin/dump.pl`` file on stdin.
    """
    stdin = sys.stdin

    def write(self, message):
        if self.verbose:
            self.stdout.write(message)

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs.get('verbosity', 1)) > 1

        # Each packages subscriptions are output in a separate line each in the
        # following format:
        # <package-name> => [ <email1> <email2> ... ]
        for line in self.stdin:
            package_name, emails = line.split('=>', 1)
            package_name = package_name.strip()
            try:
                emails = emails.strip().strip('[]').strip().split()
            except:
                self.write("Malformed line: {}".format(line))
                continue
            emails = [email.strip() for email in emails]
            # For each email create a subscription to the package
            self.write(
                "Importing subscriptions for package {}".format(package_name))
            for email in emails:
                Subscription.objects.create_for(package_name, email)
