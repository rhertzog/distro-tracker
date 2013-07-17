# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from pts.core.utils.plugins import PluginRegistry
from pts.core.utils.datastructures import DAG
from django.utils import six

from collections import defaultdict
import logging
import sys

logger = logging.getLogger(__name__)


class BaseTask(six.with_metaclass(PluginRegistry)):
    """
    A class representing the base class for all data processing tasks of the
    PTS.

    The subclasses of this class are automatically registered when created.
    """
    DEPENDS_ON_EVENTS = ()
    PRODUCES_EVENTS = ()

    @classmethod
    def task_name(cls):
        if hasattr(cls, 'NAME'):
            return cls.NAME
        else:
            return cls.__name__

    def __init__(self):
        #: A flag signalling whether the task has received any events.
        #: A task with no received events does not need to run.
        self.event_received = False
        self._raised_events = []

    def execute(self):
        """
        Performs the actual processing of the task.

        This method must raise appropriate events by using the `raise_event`
        method during the processing so that tasks which are dependent on those
        events can be notified.
        """
        pass

    @property
    def raised_events(self):
        """
        Return an iterable of Events which the task raised during its execution
        """
        return self._raised_events

    def raise_event(self, event_name, arguments=None):
        """
        Helper method which should be used by subclasses to signal that an
        event has been triggered. The object given in the arguments parameter
        will be passed on to to the `Event` instance's arguments and become
        available to any tasks which receive this event.
        """
        self._raised_events.append(Event(event_name, arguments))

    def clear_events(self):
        """
        Clears all events the task raised.
        """
        self._raised_events = []

    def receive_event(self, event):
        """
        This method is used by clients to notify the task that a specific event
        has been triggered while processing another task.

        If the task depends on this event, the `event_received` flag is set and
        additional, subclass specific, processing is initiated (by calling the
        `process_event` method).
        """
        if event.name in self.DEPENDS_ON_EVENTS:
            # In the general case, an event can come with some arguments, but
            # BaseTask subclasses need to implement this specifically.
            self.process_event(event)
            self.event_received = True

    def process_event(self, event):
        """
        Helper method which should be implemented by subclasses which require
        specific processing of received events.
        """
        pass

    def set_parameters(self, parameters):
        """
        Allows clients to set additional task-specific parameters once a task
        is already created.
        """
        pass

    @classmethod
    def build_full_task_dag(cls):
        """
        A class method which builds a full TaskDAG where only subclasses of
        `cls` are included in the DAG. If `cls` is `BaseTask` then the DAG
        contains all tasks.

        The TaskDAG instance represents the dependencies between Task classes
        based on the events they produce and depend on.
        """
        dag = TaskDAG()
        # Add all existing tasks to the dag.
        for task in BaseTask.plugins:
            if task is not cls and issubclass(task, cls):
                dag.add_task(task)

        # Create the edges of the graph by creating an edge between each pair of
        # tasks T1, T2 where T1 produces an event E and T2 depends on the event E.
        from itertools import product as cross_product
        events = cls.build_task_event_dependency_graph()
        for event_producers, event_consumers in events.values():
            for task1, task2 in cross_product(event_producers, event_consumers):
                dag.add_dependency(task1, task2)

        return dag

    @classmethod
    def build_task_event_dependency_graph(cls):
        """
        Returns a dict mapping event names to a two-tuple of a list of task classes
        which produce the event and a list of task classes which depend on the
        event, respectively.
        Only tasks which are subclassed from `cls` are included.
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
    A DAG subclass which exposes some methods specific for DAGs of dependent
    tasks.
    """
    @property
    def all_tasks(self):
        return self.all_nodes

    def all_dependent_tasks(self, task):
        """
        Returns all tasks that are dependent on this task.

        Effectively, this means all tasks reachable from this one in the DAG of
        tasks.
        """
        return self.nodes_reachable_from(task)

    def directly_dependent_tasks(self, task):
        """
        Returns only tasks which are directly dependent on this task.

        This means all tasks to which this task has a direct edge
        (neighbour nodes).
        """
        return self.dependent_nodes(task)

    def remove_task(self, task):
        """
        Removes the given task from the DAG.
        """
        return self.remove_node(task)

    def add_task(self, task):
        """
        Adds the given task to the DAG.
        """
        return self.add_node(task)

    def add_dependency(self, task1, task2):
        """
        Registers the dependency between these two tasks.
        """
        return self.add_edge(task1, task2)


class Job(object):
    """
    A class used to initialize and run a set of interdependent tasks.
    """
    def __init__(self, initial_task, base_task_class=BaseTask):
        """
        Instantiates a new Job instance based on the given initial_task.

        The task contains a DAG instance which is constructed by using all
        possible dependencies between tasks. While running the tasks, the
        job keeps track of emitted events and makes sure that a task with
        no received events is not run, even though we used those dependencies
        when constructing the DAG.

        This way, we are guaranteed that tasks execute in the correct order and
        at most once -- after all the tasks which could possibly raise an event
        which that task depends on.
        """
        # Build this job's DAG based on the full DAG of all tasks.
        self.job_dag = base_task_class.build_full_task_dag()
        # The full DAG contains dependencies between Task classes, but the job
        # needs to have Task instances, so it instantiates the Tasks dependent
        # on the initial task.
        reachable_tasks = self.job_dag.all_dependent_tasks(initial_task)
        for task_class in self.job_dag.all_tasks:
            if task_class is initial_task or task_class in reachable_tasks:
                task = task_class()
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

    def _update_task_events(self, processed_task):
        """
        Updates the received events of all tasks which depend on events the
        processed_task has raised.
        """
        for dependent_task in self.job_dag.directly_dependent_tasks(processed_task):
            # Update this task's raised events.
            for event in processed_task.raised_events:
                dependent_task.receive_event(event)

    def run(self, parameters=None):
        """
        Starts the Job processing.

        It runs all tasks which depend on the given initial task, but only if
        the required events are emitted and received.
        """
        for task in self.job_dag.topsort_nodes():
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
                except Exception as e:
                    logger.error(
                        "Problem processing a task. "
                        "Exception: {e}".format(e=e))
                # Update dependent tasks based on events raised.
                # The update is performed regardless of a possible failure in
                # order not to miss some events.
                self._update_task_events(task)
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
        except Exception as e:
            self.clear_events()
            six.reraise(*sys.exc_info())
    return wrapper


def run_task(initial_task, parameters=None):
    """
    Receives a class of the task which should be executed and makes sure that
    all the tasks which have data dependencies on this task are ran after it.

    This is a convenience function which delegates this to a Job class instance
    """
    job = Job(initial_task)
    return job.run(parameters)
