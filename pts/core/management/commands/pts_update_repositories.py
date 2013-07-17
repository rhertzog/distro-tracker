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
from django.core.management.base import BaseCommand
from optparse import make_option
from pts.core.retrieve_data import UpdateRepositoriesTask
from pts.core.tasks import run_task


class Command(BaseCommand):
    """
    A Django management command which performs the update of available pseudo
    pacakges.
    """
    help = "Update the package information found in registered repositories"
    option_list = BaseCommand.option_list + (
        make_option('--force',
                    action='store_true',
                    dest='force',
                    default=False,
                    help=(
                        'Force the update. '
                        'This clears any caches and makes a full update'
                    )),
    )

    def handle(self, *args, **kwargs):
        additional_arguments = None
        if kwargs['force']:
            additional_arguments = {
                'force_update': True
            }
        run_task(UpdateRepositoriesTask, additional_arguments)
