# Copyright 2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Task schedulers.

A task scheduler is tied to a task and is able to answer the question
whether the task needs to run or not.
"""
import logging
from datetime import timedelta

from distro_tracker.core.utils import now

logger = logging.getLogger('distro_tracker.tasks')


class Scheduler(object):
    """
    Base class of all schedulers.

    It doesn't implement any logic, it just always responds True to
    the :meth:`.needs_to_run` query.
    """

    def __init__(self, task):
        self.task = task

    def needs_to_run(self):
        """
        Checks whether the associated task needs to run.

        :return: True if the task needs to run, False otherwise
        :rtype: bool
        """
        return True


class IntervalScheduler(Scheduler):
    """
    An IntervalScheduler runs the task at a regular interval. The interval
    must be specified in the :attr:`interval` class attribute of any sub-class.
    """

    def get_interval(self):
        """
        Returns the interval between two runs in seconds.

        :raises ValueError: when the :attr:`.interval` attribute is not parsable
        :return: the interval in seconds
        :rtype: int
        """
        return int(self.interval)

    def needs_to_run(self):
        last_try = self.task.last_attempted_run
        if last_try is None:
            return True
        next_try = last_try + timedelta(seconds=self.get_interval())
        return now() >= next_try
