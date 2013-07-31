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
Implements a command to start a number of available PTS tasks.
A task is a subclass of :class:`pts.core.tasks.BaseTask`.
"""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from optparse import make_option
from pts.core.tasks import run_task
import traceback


class Command(BaseCommand):
    """
    A management command which starts a number of PTS tasks.
    A task is a subclass of :class:`pts.core.tasks.BaseTask`.
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
        verbose = int(kwargs.get('verbosity', 1)) > 1
        additional_arguments = None
        if kwargs['force']:
            additional_arguments = {
                'force_update': True
            }
        for task_name in args:
            task_name = task_name.decode('utf-8')
            try:
                run_task(task_name, additional_arguments)
            except:
                if verbose:
                    self.stdout.write(task_name + ' failed!')
                    traceback.print_exc(file=self.stdout)
