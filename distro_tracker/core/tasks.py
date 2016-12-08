# Copyright 2013-2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a framework for implementing interdependent tasks.

It provides a way to run all tasks dependent on the original task
automatically.
"""
from __future__ import unicode_literals
from distro_tracker.core.utils.plugins import PluginRegistry
from distro_tracker.core.utils.datastructures import DAG
from distro_tracker.core.models import RunningJob
from django.utils import six
from django.conf import settings

from collections import defaultdict
import importlib
import logging
import sys

logger = logging.getLogger('distro_tracker.tasks')


class BaseTask(six.with_metaclass(PluginRegistry)):
    """
    A class representing the base class for all data processing tasks of
    Distro Tracker.

    Each task can produce or depend on certain events.

    The list :attr:`DEPENDS_ON_EVENTS` gives a list of events that, if raised
    during the processing of another task, cause this task to run as well.

    Events defined in the :attr:`PRODUCES_EVENTS` list are the ones this task
    is allowed to produce. Other tasks which depend on those events can then
    be registered.
    It is possible that the task does not produce all events given in this list
    in which case only tasks depending on the events which *were* raised are
    initiated afterwards.

    ..note::
      Subclasses of this class are automatically registered when created which
      allows the :class:`BaseTask` to have the full picture of all tasks and
      their mutual dependencies. However, to make sure the subclass is always
      loaded, make sure to place it in a ``tracker_tasks`` module at the top
      level of a Django app.
    """
    DEPENDS_ON_EVENTS = ()
    PRODUCES_EVENTS = ()

    @classmethod
    def task_name(cls):
        """
        The classmethod should return the name of the task.

        It can be given as a ``NAME`` class-level attribute or by overriding
        this classmethod.

        If none of those is done, the default value is the name of the class,
        i.e. the ``__name__`` attribute of the class.
        """
        if hasattr(cls, 'NAME'):
            return cls.NAME
        else:
            return cls.__name__

    def __init__(self, job=None):
        #: A flag signalling whether the task has received any events.
        #: A task with no received events does not need to run.
        self.event_received = False
        self._raised_events = []
        #: A reference to the job to which this task belongs, if any
        self.job = job

    def is_initial_task(self):
        """
        :returns True: If the task is the first task in a job (or if it's not
            part of a job).
        :returns False: If the task is not the first task in a job.
        """
        if self.job is None:
            return True
        return len(self.job.job_state.processed_tasks) == 0

    def execute(self):
        """
        Performs the actual processing of the task.

        This method must raise appropriate events by using the
        :meth:`raise_event` method during the processing so that tasks which are
        dependent on those events can be notified.
        """
        pass

    @property
    def raised_events(self):
        """
        :returns: Events which the task raised during its execution
        :rtype: ``iterable`` of :class:`Event`
        """
        return self._raised_events

    def raise_event(self, event_name, arguments=None):
        """
        Helper method which should be used by subclasses to signal that an
        event has been triggered.

        :param event_name: The name of the event to be raised.
        :type event_name: string

        :param arguments: Passed on to to the :class:`Event` instance's
            :attr:`arguments <Event.arguments>`. It becomes available to any
            tasks which receive the raised event.
        :type arguments: dict
        """
        self._raised_events.append(Event(event_name, arguments))

    def clear_events(self):
        """
        Clears all events the task raised.
        """
        self._raised_events = []

    def get_all_events(self):
        """
        Returns all events raised during the processing of a job which are
        relevant for this task.

        If the task is running independently of a job, an empty list is
        returned.
        """
        if self.job:
            return self.job.job_state.events_for_task(self)
        else:
            return []

    def set_parameters(self, parameters):
        """
        Allows clients to set additional task-specific parameters once a task
        is already created.

        :param parameters: The extra parameters.
        :type parameters: dict
        """
        pass

    @classmethod
    def get_task_class_by_name(cls, task_name):
        """
        Returns a :class:`BaseTask` subclass which has the given name, i.e. its
        :meth:`task_name` method returns the ``task_name`` given in the
        parameters.

        :param task_name: The name of the task which should be returned.
        """
        for task_class in cls.plugins:
            if task_class.task_name() == task_name:
                return task_class
        return None

    @classmethod
    def build_full_task_dag(cls):
        """
        A class method which builds a full :class:`TaskDAG` where only
        subclasses of ``cls`` are included in the DAG.
        If `cls` is :class:`BaseTask` then the DAG contains all tasks.

        The :class:`TaskDAG` instance represents the dependencies between
        :class:`BaseTask` subclasses based on the events they produce and
        depend on.

        :rtype: :class:`TaskDAG`
        """
        dag = TaskDAG()
        # Add all existing tasks to the dag.
        for task in BaseTask.plugins:
            if task is not cls and issubclass(task, cls):
                dag.add_task(task)

        # Create the edges of the graph by creating an edge between each pair of
        # tasks T1, T2 where T1 produces an event E and T2 depends on the event
        # E.
        from itertools import product as cross_product
        events = cls.build_task_event_dependency_graph()
        for event_producers, event_consumers in events.values():
            for task1, task2 in cross_product(event_producers, event_consumers):
                dag.add_dependency(task1, task2)

        return dag

    @classmethod
    def build_task_event_dependency_graph(cls):
        """
        Returns a dict mapping event names to a two-tuple of a list of task
        classes which produce the event and a list of task classes which depend
        on the event, respectively.
        Only tasks which are subclassed from `cls` are included.

        .. note::
           "Task classes" are all subclasses of :class:`BaseTask`
        """
        events = defaultdict(lambda: ([], []))
        for task in BaseTask.plugins:
            if task is cls or not issubclass(task, cls):
                continue
            for event in task.PRODUCES_EVENTS:
                events[event][0].append(task)
            for event in task.DEPENDS_ON_EVENTS:
                events[event][1].append(task)

        return events

    def log(self, message, *args, **kwargs):
        """Log a message about the progress of the task"""
        if 'level' in kwargs:
            level = kwargs['level']
            del kwargs['level']
        else:
            level = logging.INFO
        message = "{} {}".format(self.task_name(), message)
        logger.log(level, message, *args, **kwargs)


class Event(object):
    """
    A class representing a particular event raised by a task.
    """
    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class TaskDAG(DAG):
    """
    A :class:`DAG <distro_tracker.core.utils.datastructures.DAG>` subclass which
    exposes some methods specific for DAGs of dependent tasks.
    """
    @property
    def all_tasks(self):
        return self.all_nodes

    def all_dependent_tasks(self, task):
        """
        Returns all tasks that are dependent on the given ``task``.

        Effectively, this means all tasks reachable from this one in the DAG of
        tasks.

        :type task: :class:`BaseTask` subclass
        :rtype: ``list`` of :class:`BaseTask` subclasses
        """
        return self.nodes_reachable_from(task)

    def directly_dependent_tasks(self, task):
        """
        Returns only tasks which are directly dependent on the given ``task``

        This means all tasks to which this task has a direct edge
        (neighbour nodes).

        :type task: :class:`BaseTask` subclass
        :rtype: ``list`` of :class:`BaseTask` subclasses
        """
        return self.dependent_nodes(task)

    def remove_task(self, task):
        """
        Removes the given ``task`` from the DAG.

        :type task: :class:`BaseTask` subclass
        """
        return self.remove_node(task)

    def add_task(self, task):
        """
        Adds the given ``task`` to the DAG.

        :type task: :class:`BaseTask` subclass
        """
        return self.add_node(task)

    def add_dependency(self, task1, task2):
        """
        Registers the dependency between these two tasks.
        """
        return self.add_edge(task1, task2)


class JobState(object):
    """
    Represents the current state of a running job.

    Provides a way to persist the state and reconstruct it in order to re-run
    failed tasks in a job.
    """
    def __init__(self, initial_task_name, additional_parameters=None):
        self.initial_task_name = initial_task_name
        self.additional_parameters = additional_parameters
        self.events = []
        self.processed_tasks = []

        self._running_job = None

    @classmethod
    def deserialize_running_job_state(cls, running_job):
        """
        Deserializes a :class:`RunningJob
        <distro_tracker.core.models.RunningJob>` instance and returns a matching
        :class:`JobState`.
        """
        instance = cls(running_job.initial_task_name)
        instance.additional_parameters = running_job.additional_parameters
        instance.events = [
            Event(name=event['name'], arguments=event.get('arguments', None))
            for event in running_job.state['events']
        ]
        instance.processed_tasks = running_job.state['processed_tasks']
        instance._running_job = running_job

        return instance

    def add_processed_task(self, task):
        """
        Marks a task as processed.

        :param task: The task which should be marked as processed
        :type task: :class:`BaseTask` subclass instance
        """
        self.events.extend(task.raised_events)
        self.processed_tasks.append(task.task_name())

    def save_state(self):
        """
        Saves the state to persistent storage.
        """
        state = {
            'events': [
                {
                    'name': event.name,
                    'arguments': event.arguments,
                }
                for event in self.events
            ],
            'processed_tasks': self.processed_tasks,
        }
        if not self._running_job:
            self._running_job = RunningJob(
                initial_task_name=self.initial_task_name,
                additional_parameters=self.additional_parameters)
        self._running_job.state = state
        self._running_job.save()

    def mark_as_complete(self):
        """
        Signals that the job is finished.
        """
        self._running_job.is_complete = True
        self.save_state()

    def events_for_task(self, task):
        """
        :param task: The task for which relevant :class:`Event` instances
            should be returned.
        :returns: Raised events which are relevant for the given ``task``
        :rtype: ``generator``
        """
        return (
            event
            for event in self.events
            if event.name in task.DEPENDS_ON_EVENTS
        )


class Job(object):
    """
    A class used to initialize and run a set of interdependent tasks.
    """
    def __init__(self, initial_task, base_task_class=BaseTask):
        """
        Instantiates a new :class:`Job` instance based on the given
        ``initial_task``.

        The job constructs a :class:`TaskDAG` instance by using all
        possible dependencies between tasks.

        Tasks are run in toplogical sort order and it is left up to them to
        inspect the raised events and decide how to process them.

        .. note::
           "Task classes" are all subclasses of :class:`BaseTask`
        """
        # Build this job's DAG based on the full DAG of all tasks.
        self.job_dag = base_task_class.build_full_task_dag()
        # The full DAG contains dependencies between Task classes, but the job
        # needs to have Task instances, so it instantiates the Tasks dependent
        # on the initial task.
        reachable_tasks = self.job_dag.all_dependent_tasks(initial_task)
        for task_class in self.job_dag.all_tasks:
            if task_class is initial_task or task_class in reachable_tasks:
                task = task_class(job=self)
                if task_class is initial_task:
                    # The initial task gets flagged with an event so that we
                    # make sure that it is not skipped.
                    task.event_received = True
                self.job_dag.replace_node(task_class, task)
            else:
                # Remove tasks which are not reachable from the initial task
                # from the job Tasks DAG, since those are in no way dependent
                # on it and will not need to run.
                self.job_dag.remove_task(task_class)

        self.job_state = JobState(initial_task.task_name())

    @classmethod
    def reconstruct_job_from_state(cls, job_state):
        """
        The method takes a :class:`JobState` and reconstructs a job if possible.

        :param job_state: The job state based on which the job should be
            reconstructed
        :type job_state: :class:`JobState`

        :returns: the reconstructed :class:`Job` instance.
            Calling the run method of this instance will continue execution of
            the job at the task following the last executed task in the job
            state.
        :rtype: :class:`Job`
        """
        job = cls(BaseTask.get_task_class_by_name(job_state.initial_task_name))
        job.job_state = job_state

        # Update the task instances event_received for all events which are
        # found in the job's state.
        raised_events_names = set(
            event.name
            for event in job_state.events
        )
        for task in job.job_dag.all_tasks:
            if task.event_received:
                continue
            for task_depends_event_name in task.DEPENDS_ON_EVENTS:
                if task_depends_event_name in raised_events_names:
                    task.event_received = True
                    break

        return job

    def _update_task_events(self, processed_task):
        """
        Performs an update of tasks in the job based on the events raised by
        ``processed_task``.

        Flags all tasks which are registered to depend on one of the raised
        events so that they are guaranteed to run.
        Tasks which are never flagged are skipped; there is no need to run them
        since no event they depend on was raised during the job's processing.

        :param processed_task: A finished task
        :type processed_task: :class:`BaseTask` subclass
        """
        event_names_raised = set(
            event.name
            for event in processed_task.raised_events
        )
        for dependent_task in \
                self.job_dag.directly_dependent_tasks(processed_task):
            if dependent_task.event_received:
                continue
            # Update this task's raised events.
            for event_name in event_names_raised:
                if event_name in dependent_task.DEPENDS_ON_EVENTS:
                    dependent_task.event_received = True
                    break

    def run(self, parameters=None):
        """
        Starts the Job processing.

        It runs all tasks which depend on the given initial task.

        :param parameters: Additional parameters which are given to each task
            before it is executed.
        """
        self.job_state.additional_parameters = parameters
        for task in self.job_dag.topsort_nodes():
            # This happens if the job was restarted. Skip such tasks since they
            # considered finish by this job. All its events will be propagated
            # to the following tasks correctly.
            if task.task_name() in self.job_state.processed_tasks:
                continue
            # A task does not need to run if none of the events it depends on
            # have been raised by this point.
            # If it's that task's turn in topological sort order when all
            # dependencies are used to construct the graph, it is guaranteed
            # that none of its dependencies will ever be raised since the tasks
            # which come afterwards do not raise any events which this task
            # depends on.
            # (Otherwise that task would have to be ahead of this one in the
            #  topological sort order.)
            if task.event_received:
                # Run task
                try:
                    # Inject additional parameters, if any
                    if parameters:
                        task.set_parameters(parameters)
                    logger.info("Starting task {task}".format(
                        task=task.task_name()))
                    task.execute()
                    logger.info("Successfully executed task {task}".format(
                        task=task.task_name()))
                except Exception:
                    logger.exception("Problem processing a task.")
                # Update dependent tasks based on events raised.
                # The update is performed regardless of a possible failure in
                # order not to miss some events.
                self._update_task_events(task)

            self.job_state.add_processed_task(task)
            self.job_state.save_state()

        self.job_state.mark_as_complete()
        logger.info("Finished all tasks")


def clear_all_events_on_exception(func):
    """
    Decorator which makes sure that all events a task wanted to raise are
    cleared in case an exception is raised during its execution.

    This may not be what all tasks want so it is provided as a convenience
    decorator for those that do.
    """
    def wrapper(self):
        try:
            func(self)
        except Exception:
            self.clear_events()
            six.reraise(*sys.exc_info())
    return wrapper


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


def run_task(initial_task, parameters=None):
    """
    Receives a class of the task which should be executed and makes sure that
    all the tasks which have data dependencies on this task are ran after it.

    This is a convenience function which delegates this to a :class:`Job` class
    instance.

    :param initial_task: The task which should be run. Either the class object
        of the task or a string giving the task's name.
    :type initial_task: :class:`BaseTask` subclass or :class:`string`

    :param parameters: Additional parameters which are given to each task
    before it is executed.
    """
    # Import tasks implemented by all installed apps
    import_all_tasks()

    if isinstance(initial_task, six.text_type):
        task_name = initial_task
        initial_task = BaseTask.get_task_class_by_name(initial_task)
        if not initial_task:
            raise ValueError("Task '%s' doesn't exist." % task_name)
    job = Job(initial_task)
    return job.run(parameters)


def run_all_tasks(parameters=None):
    """
    Runs all registered tasks which do not have any dependencies.

    :param parameters: Additional parameters which are given to each task
    before it is executed.
    """
    import_all_tasks()

    for task in BaseTask.plugins:
        if task is BaseTask:
            continue
        if not task.DEPENDS_ON_EVENTS:
            logger.info("Starting task %s", task.task_name())
            run_task(task)


def continue_task_from_state(job_state):
    """
    Continues execution of a job from the last point in the given ``job_state``

    :param job_state: The state of the job from which it should be continued
    :type job_state: :class:`JobState`
    """
    job = Job.reconstruct_job_from_state(job_state)
    return job.run(job_state.additional_parameters)
