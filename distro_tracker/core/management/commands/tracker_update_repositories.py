# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a command to initiate the update of package information found in
registered repositories.

It launches an
:class:`UpdateRepositoriesTask
<distro_tracker.core.retrieve_data.UpdateRepositoriesTask>` task.
"""
from django.core.management.base import BaseCommand

from distro_tracker.core.retrieve_data import UpdateRepositoriesTask
from distro_tracker.core.tasks import run_task


class Command(BaseCommand):
    """
    A management command which updates package information found in all
    registered repositories.
    """
    help = "Update the package information found in registered repositories"

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            default=False,
            help=(
                'Force the update. '
                'This clears any caches and makes a full update'
            )
        )

    def handle(self, *args, **kwargs):
        additional_arguments = None
        if kwargs['force']:
            additional_arguments = {
                'force_update': True
            }
        run_task(UpdateRepositoriesTask, additional_arguments)
