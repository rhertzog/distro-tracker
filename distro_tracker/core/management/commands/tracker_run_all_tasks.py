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
Implements a command which starts all independent Distro Tracker tasks.
A task is a subclass of :class:`distro_tracker.core.tasks.BaseTask`.
"""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from distro_tracker.core.tasks import run_all_tasks
import logging

logger = logging.getLogger('distro_tracker.tasks')


class Command(BaseCommand):
    """
    A management command which starts all independent Distro Tracker tasks.
    """
    help = "Start all independent Distro Tracker tasks."

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

        logger.info(
            'Starting all tasks (from ./manage.py tracker_run_all_tasks')
        run_all_tasks(additional_arguments)
