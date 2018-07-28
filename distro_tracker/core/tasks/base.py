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
from distro_tracker.core.utils.plugins import PluginRegistry

logger = logging.getLogger('distro_tracker.tasks')


class BaseTask(metaclass=PluginRegistry):
    """
    A class representing the base class for all data processing tasks of
    Distro Tracker.

    ..note::
      Subclasses of this class are automatically registered when created which
      allows the :class:`BaseTask` to have the full picture of all tasks and
      their mutual dependencies. However, to make sure the subclass is always
      loaded, make sure to place it in a ``tracker_tasks`` module at the top
      level of a Django app.
    """

    class ConcurrentDataUpdate(RuntimeError):
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
        pass

    @property
    def data(self):
        """
        A data dictionnary that matches the corresponding
        :class:`~distro_tracker.core.models.TaskData`. It is loaded from the
        database on first access, and it's saved when you call
        the :meth:`.save_data` method.
        """
        if hasattr(self, '_data'):
            return self._data
        task_data, _ = TaskData.objects.get_or_create(
            task_name=self.task_name())
        self._data = task_data.data
        self._task_data = task_data
        return self._data

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

    def execute(self):
        """
        Performs the actual processing of the task.
        """
        pass

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
