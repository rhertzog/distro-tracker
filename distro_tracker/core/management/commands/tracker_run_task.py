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
Implements a command to start a number of available Distro Tracker tasks.
A task is a subclass of :class:`distro_tracker.core.tasks.BaseTask`.
"""
import logging

from django.core.management.base import BaseCommand

from distro_tracker.core.tasks import run_task

logger = logging.getLogger('distro_tracker.tasks')


class Command(BaseCommand):
    """
    A management command which starts a number of Distro Tracker tasks.
    A task is a subclass of :class:`distro_tracker.core.tasks.BaseTask`.
    """
    help = "Start all the Distro Tracker tasks given by name."

    def add_arguments(self, parser):
        parser.add_argument('tasks', nargs='+', help='Tasks to be run')
        parser.add_argument(
            '--force-update',
            action='store_true',
            dest='force_update',
            default=False,
            help=(
                'Force the update. '
                'This clears any caches and makes a full update.'
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
        for task_name in kwargs['tasks']:
            if isinstance(task_name, bytes):
                task_name = task_name.decode('utf-8')
            logger.info("./manage.py tracker_run_task %s", task_name)
            if not run_task(task_name, **params):
                self.stderr.write('Task {} failed to run.\n'.format(task_name))
