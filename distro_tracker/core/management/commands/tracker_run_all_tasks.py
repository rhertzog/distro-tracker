# Copyright 2013-2018 The Distro Tracker Developers
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
import logging

from django.core.management.base import BaseCommand

from distro_tracker.core.tasks import run_all_tasks

logger = logging.getLogger('distro_tracker.tasks')


class Command(BaseCommand):
    """
    A management command which starts all Distro Tracker tasks that can
    be run according to their scheduling policy.
    """
    help = "Start all Distro Tracker tasks that can be run."  # noqa

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-update',
            action='store_true',
            dest='force_update',
            default=False,
            help=(
                'Force the update. '
                'This clears any caches and makes a full update'
            )
        )
        parser.add_argument(
            '--fake-update',
            action='store_true',
            dest='fake_update',
            default=False,
            help=(
                'Instruct the task to not do anything except recording that '
                'everything has been done.'
            )
        )

    def handle(self, *args, **kwargs):
        params = {}
        if kwargs['force_update']:
            params['force_update'] = True
        if kwargs['fake_update']:
            params['fake_update'] = True
        logger.info(
            'Starting all tasks (from ./manage.py tracker_run_all_tasks')
        run_all_tasks(**params)
        logger.info(
            'Finished to run all tasks (from ./manage.py tracker_run_all_tasks')
