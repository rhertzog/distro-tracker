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
import importlib
from datetime import timedelta

from django.conf import settings

from distro_tracker.core.models import TaskData
from distro_tracker.core.tasks.schedulers import Scheduler
from distro_tracker.core.utils import now
from distro_tracker.core.utils.misc import (
    call_methods_with_prefix,
    get_data_checksum,
)
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

    def __init__(self, *args, **kwargs):
        self.scheduler = self.Scheduler(self)
        self.data_is_modified = False
        self.event_handlers = {}
        self.initialize(*args, **kwargs)
        super().__init__()

    def initialize(self, *args, **kwargs):
        """
        Process arguments passed to :meth:`__init__()`. Can be overriden
        to do other runtime preparation.

        For proper cooperation, you should usually call the method on the
        object returned by ``super()`` (if it exists).
        """
        self.force_update = kwargs.get('force_update', False)
        self.fake_update = kwargs.get('fake_update', False)
        self.parameters = kwargs

        # Call other implementations of the initialize method
        super_object = super()
        if super_object and hasattr(super_object, 'initialize'):
            super_object.initialize(*args, **kwargs)

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
        if self.data_is_modified is False:
            self.data_is_modified = None
        return self._data

    def data_mark_modified(self):
        """
        Record the fact that the data dictionnary has been modified and will
        have to be saved.
        """
        self.data_is_modified = True

    @property
    def task_data(self):
        """
        Returns the corresponding :class:`~distro_tracker.core.models.TaskData`.
        """
        if not hasattr(self, '_task_data'):
            self.refresh_data()
        return self._task_data

    def save_data(self, **kwargs):
        """
        Save the :attr:`.data` attribute in the corresponding
        :class:`~distro_tracker.core.models.TaskData` model in a way
        that ensures that we don't overwrite any concurrent update.

        :raises BaseTask.ConcurrentUpdateError: when the update is not possible
            without risking to lose another update that happened in parallel.
        """
        kwargs['data'] = self._data
        if not self._task_data.versioned_update(**kwargs):
            raise self.ConcurrentDataUpdate(
                'Data from task {} have been updated in parallel'.format(
                    self.task_name()))
        self.data_is_modified = False

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
            self.handle_event('execute-started')
            call_methods_with_prefix(self, 'execute_')
            self.handle_event('execute-finished')
        except Exception:
            self.handle_event('execute-failed')
            raise
        finally:
            self.update_field('run_lock', None)

        if self.data_is_modified is True:
            self.save_data()
        elif self.data_is_modified is None:
            checksum = get_data_checksum(self._data)
            if checksum != self.task_data.data_checksum:
                self.save_data(data_checksum=checksum)

        self.update_last_completed_run(timestamp)
        self.update_task_is_pending(False)

    def register_event_handler(self, event, function):
        """
        Register a function to execute in response to a specific event.

        There's no validation done on the event name. The following events are
        known to be in use:
        - execute-started (at the start of the execute method)
        - execute-finished (at the end of the execute method, in case of
          success)
        - execute-failed (at the end of the execute method, in case of failure)

        :param str event: the name of the event to handle
        :param function: a function or any callable object
        """
        handlers = self.event_handlers.setdefault(event, [])
        if function not in handlers:
            handlers.append(function)

    def handle_event(self, event, *args, **kwargs):
        """
        This method is called at various places (with different values passed
        to the event parameter) and is a way to let sub-classes, mixins, and
        users add their own behaviour.

        :param str event: a string describing the event that happened
        """
        for function in self.event_handlers.get(event, []):
            function(*args, **kwargs)

    def lock_expires_soon(self, delay=600):
        """
        :param int delay: The number of seconds allowed before the lock is
            considered to expire soon.
        :return: True if the lock is about to expire in the given delay. Returns
            False otherwise.
        :rtype: bool
        """
        if self.task_data.run_lock is None:
            return False
        return self.task_data.run_lock <= now() + timedelta(seconds=delay)

    def extend_lock(self, delay=1800, expire_delay=600):
        """
        Extends the duration of the lock with the given `delay` if it's
        about to expire soon (as defined by the `expire_delay` parameter).

        :param int expire_delay: The number of seconds allowed before the lock
            is considered to expire soon.
        :param int delay: The number of seconds to add the expiration time of
            the lock.
        """
        if self.lock_expires_soon(delay=expire_delay):
            self.task_data.extend_run_lock(delay=delay)
            return True
        return False


def import_all_tasks():
    """
    Imports tasks found in each installed app's ``tracker_tasks`` module.
    """
    for app in settings.INSTALLED_APPS:
        try:
            module_name = app + '.' + 'tracker_tasks'
            importlib.import_module(module_name)
        except ImportError:
            # The app does not implement Distro Tracker tasks.
            pass
    # This one is an exception, many core tasks are there
    import distro_tracker.core.retrieve_data  # noqa


def run_task(task, *args, **kwargs):
    """
    Executes the requested task.

    :param task: The task which should be run. Either the class object
        of the task, or a string giving the task's name, or the task object
        itself.
    :type task: :class:`BaseTask` subclass or :class:`str`

    :returns: True is the task executed without errors, False if it raised
        an exception during its execution.
    """
    # Import tasks implemented by all installed apps
    import_all_tasks()

    task_class = None
    if isinstance(task, str):
        task_name = task
        task_class = BaseTask.get_task_class_by_name(task_name)
        if not task_class:
            raise ValueError("Task '%s' doesn't exist." % task_name)
        task = task_class(*args, **kwargs)
    elif isinstance(task, BaseTask):
        pass
    elif callable(task) and hasattr(task, 'execute'):
        task_class = task
        task = task_class(*args, **kwargs)
    else:
        raise ValueError("Can't run a task with a '{}'.".format(repr(task)))
    logger.info("Starting task %s", task.task_name())
    try:
        task.execute()
    except Exception:
        logger.exception("Task %s failed with the following traceback.",
                         task.task_name())
        return False
    logger.info("Completed task %s", task.task_name())
    return True


def build_all_tasks(*args, **kwargs):
    """
    Builds all the task objects out of the BaseTask sub-classes registered.

    :returns: a dict mapping the task name to the corresponding Task instance.
    :rtype dict:
    :raises ValueError: if multiple tasks have the same name.
    """
    import_all_tasks()
    tasks = {}
    for task_class in BaseTask.plugins:
        task_name = task_class.task_name()
        if task_name in tasks:
            raise ValueError("Multiple tasks with the same name: {}".format(
                task_name))
        tasks[task_class.task_name()] = task_class(*args, **kwargs)
    return tasks


def run_all_tasks(*args, **kwargs):
    """
    Builds all task and then iterates over them to check if they need
    to be scheduled. If yes, then executes them with :func:`run_task`.

    The special task "UpdateRepositoriesTask" is always executed
    first. The execution order of the other tasks is undetermined.
    """
    tasks = build_all_tasks(*args, **kwargs)

    for task in tasks.values():
        task.schedule()

    if 'UpdateRepositoriesTask' in tasks:
        task = tasks.pop('UpdateRepositoriesTask')
        if task.task_is_pending:
            run_task(task)

    for task in tasks.values():
        if task.task_is_pending:
            run_task(task)
