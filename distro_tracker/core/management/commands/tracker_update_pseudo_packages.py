# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements a command to update available pseudo packages."""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from distro_tracker.core.models import PseudoPackageName
from distro_tracker.core.retrieve_data import update_pseudo_package_list


class Command(BaseCommand):
    """
    A Django management command which performs the update of available pseudo
    packages.
    """
    help = "Update the available pseudo packages"

    def handle(self, *args, **kwargs):
        verbose = int(kwargs['verbosity']) > 1
        if verbose:
            self.stdout.write('Retrieving new list of pseudo-packages...')

        update_pseudo_package_list()

        if verbose:
            self.stdout.write("The updated list of pseudo-packages is:")
            for package in PseudoPackageName.objects.all():
                self.stdout.write('- ' + str(package))
