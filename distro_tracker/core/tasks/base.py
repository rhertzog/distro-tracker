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
Base class to implement Tasks.

Tasks are used to execute (possibly long-running) operations that need
to happen regularly to update distro-tracker's data.
"""
import logging

from distro_tracker.core.models import TaskData
from distro_tracker.core.tasks.schedulers import Scheduler
from distro_tracker.core.utils import now
from distro_tracker.core.utils.misc import call_methods_with_prefix
from distro_tracker.core.utils.plugins import PluginRegistry

logger = logging.getLogger('distro_tracker.tasks')


class BaseTask(metaclass=PluginRegistry):
    """
    A class representing the base class for all data processing tasks of
    Distro Tracker.

    Sub-classes should provide 'execute_*' methods that do the real work
    of the task. They should also override the 'Scheduler' class to have
    a more useful scheduling policy than the default (which will always
    decide to run the task).

    ..note::
      Subclasses of this class are automatically registered when created which
      allows the :class:`BaseTask` to have the full picture of all tasks and
      their mutual dependencies. However, to make sure the subclass is always
      loaded, make sure to place it in a ``tracker_tasks`` module at the top
      level of a Django app.
    """

    class ConcurrentDataUpdate(RuntimeError):
        pass

    class LockError(RuntimeError):
        pass

    class Scheduler(Scheduler):
        """
        Each task has an associated
        :class:`~distro_tracker.core.tasks.schedulers.Scheduler` class that
        will be used to decide when to run the task. This class
        is meant to be overriden by a custom class deriving from a more
        useful Scheduler class provided in
        :mod:`distro_tracker.core.tasks.schedulers`.
        """
        pass

    @classmethod
    def task_name(cls):
        """
        Returns the name of the task. By default, it uses the class name
        but this can be overriden by setting a :py:attr:`.NAME` attribute on the
        class.

        This name is used to uniquely identify the task, notably to store
        its internal data into :class:`~distro_tracker.core.models.TaskData`.

        :return: the name of the task
        :rtype: str
        """
        if hasattr(cls, 'NAME'):
            return cls.NAME
        else:
            return cls.__name__

    def __init__(self):
        self.scheduler = self.Scheduler(self)

    @property
    def data(self):
        """
        A data dictionnary that matches the corresponding
        :class:`~distro_tracker.core.models.TaskData`. It is loaded from the
        database on first access, and it's saved when you call
        the :meth:`.save_data` method.
        """
        if not hasattr(self, '_data'):
            self.refresh_data()
        return self._data

    @property
    def task_data(self):
        """
        Returns the corresponding :class:`~distro_tracker.core.models.TaskData`.
        """
        if not hasattr(self, '_task_data'):
            self.refresh_data()
        return self._task_data

    def save_data(self):
        """
        Save the :attr:`.data` attribute in the corresponding
        :class:`~distro_tracker.core.models.TaskData` model in a way
        that ensures that we don't overwrite any concurrent update.

        :raises BaseTask.ConcurrentUpdateError: when the update is not possible
            without risking to lose another update that happened in parallel.
        """
        if not self._task_data.versioned_update(data=self._data):
            raise self.ConcurrentDataUpdate(
                'Data from task {} have been updated in parallel'.format(
                    self.task_name()))

    def refresh_data(self):
        """
        Load (or reload) task data from the database.
        """
        task_data, _ = TaskData.objects.get_or_create(
            task_name=self.task_name())
        self._data = task_data.data
        self._task_data = task_data

    def update_field(self, field, value):
        """
        Update a field of the associated TaskData with the given value
        and save it to the database. None of the other fields are saved.
        This update does not increase the version in the TaskData.

        :param str field: The name of the field to update.
        :param str value: The value to store in the field.
        """
        setattr(self.task_data, field, value)
        self.task_data.save(update_fields=[field])

    def update_last_attempted_run(self, value):
        self.update_field('last_attempted_run', value)

    def update_last_completed_run(self, value):
        self.update_field('last_completed_run', value)

    def update_task_is_pending(self, value):
        self.update_field('task_is_pending', value)

    @property
    def task_is_pending(self):
        return self.task_data.task_is_pending

    @property
    def last_attempted_run(self):
        return self.task_data.last_attempted_run

    @property
    def last_completed_run(self):
        return self.task_data.last_completed_run

    def log(self, message, *args, **kwargs):
        """Log a message about the progress of the task"""
        if 'level' in kwargs:
            level = kwargs['level']
            del kwargs['level']
        else:
            level = logging.INFO
        message = "{} {}".format(self.task_name(), message)
        logger.log(level, message, *args, **kwargs)

    @classmethod
    def get_task_class_by_name(cls, task_name):
        """
        Returns a :class:`BaseTask` subclass which has the given name, i.e. its
        :meth:`.task_name` method returns the ``task_name`` given in the
        parameters.

        :param str task_name: The name of the task which should be returned.
        """
        for task_class in cls.plugins:
            if task_class.task_name() == task_name:
                return task_class
        return None

    def schedule(self):
        """
        Asks the scheduler if the task needs to be executed. If yes, then
        records this information in the ``task_is_pending`` field. If the task
        is already marked as pending, then returns True immediately.

        :return: True if the task needs to be executed, False otherwise.
        :rtype: bool
        """
        if self.task_is_pending:
            return True
        if self.scheduler.needs_to_run():
            self.update_task_is_pending(True)
        return self.task_is_pending

    def execute(self):
        """
        Performs the actual processing of the task.

        First records the timestamp of the run, stores it in the
        'last_attempted_run' field, then executes all the methods whose names
        are starting with 'execute_', then updates the 'last_completed_run'
        field with the same timestamp (thus documenting the success of the last
        run) and clears the 'task_is_pending' flag.
        """
        if not self.task_data.get_run_lock():
            raise self.LockError('Could not get lock for task {}'.format(
                self.task_name()))

        try:
            timestamp = now()
            self.update_last_attempted_run(timestamp)
            call_methods_with_prefix(self, 'execute_')
        finally:
            self.update_field('run_lock', None)

        self.update_last_completed_run(timestamp)
        self.update_task_is_pending(False)

    # TO DROP LATER: kept only for temporary API compatibility
    def is_initial_task(self):
        # We force a full run
        return True

    def get_all_events(self):
        return []

    def raise_event(self, event_name, arguments=None):
        pass

    def set_parameters(self, parameters):
        """
        Allows clients to set additional task-specific parameters once a task
        is already created.

        :param parameters: The extra parameters.
        :type parameters: dict
        """
        pass
