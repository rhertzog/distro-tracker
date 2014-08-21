# Copyright 2013-2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a command to start a number of available Distro Tracker tasks.
A task is a subclass of :class:`distro_tracker.core.tasks.BaseTask`.
"""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from optparse import make_option
from distro_tracker.core.tasks import run_task
import traceback
import logging

logger = logging.getLogger('distro_tracker.tasks')


class Command(BaseCommand):
    """
    A management command which starts a number of Distro Tracker tasks.
    A task is a subclass of :class:`distro_tracker.core.tasks.BaseTask`.
    """
    help = "Start all the Distro Tracker tasks given by name."
    args = "task [task ...]"
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
        verbose = int(kwargs.get('verbosity', 1)) > 0
        additional_arguments = None
        if kwargs['force']:
            additional_arguments = {
                'force_update': True
            }
        for task_name in args:
            if isinstance(task_name, bytes):
                task_name = task_name.decode('utf-8')
            logger.info("Starting task %s (from ./manage.py tracker_run_task)",
                        task_name)
            try:
                run_task(task_name, additional_arguments)
            except:
                logger.exception("Task %s failed:", task_name)
                if verbose:
                    self.stdout.write('Task {} failed:\n'.format(task_name))
                    traceback.print_exc(file=self.stdout)
