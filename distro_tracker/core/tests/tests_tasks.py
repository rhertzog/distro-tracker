# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core's tasks framework.
"""
from __future__ import unicode_literals
from distro_tracker.test import TestCase
from unittest import mock
from distro_tracker.core.models import RunningJob
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks import Event
from distro_tracker.core.tasks import JobState
from distro_tracker.core.tasks import run_task, continue_task_from_state
from distro_tracker.core.tasks import run_all_tasks
import logging
logging.disable(logging.CRITICAL)


# Don't let any other module's tests be loaded.
@mock.patch('distro_tracker.core.tasks.import_all_tasks')
class JobTests(TestCase):
    def create_task_class(self, produces, depends_on, raises, fail=False):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        self._created_task_count += 1
        exec_list = self.execution_list

        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on
            NAME = 'a' * self._created_task_count

            def execute(self):
                for event in raises:
                    self.raise_event(event)
                exec_list.append(self.__class__)
                if fail:
                    raise Exception("This task fails")
        return TestTask

    def assert_contains_all(self, items, container):
        """
        Asserts that all of the given items are found in the given container.
        """
        for item in items:
            self.assertIn(item, container)

    def setUp(self):
        #: Tasks which execute add themselves to this list.
        self._created_task_count = 0
        self.execution_list = []
        self.original_plugins = [
            plugin
            for plugin in BaseTask.plugins
        ]
        # Now ignore all original plugins.
        BaseTask.plugins = [BaseTask]

    def assert_executed_tasks_equal(self, expected_tasks):
        """
        Helper method which checks whether the given list of expected tasks
        matches the actual list of executed tasks.
        """
        self.assertEqual(len(expected_tasks), len(self.execution_list))
        self.assert_contains_all(expected_tasks, self.execution_list)

    def assert_task_dependency_preserved(self, task, dependent_tasks):
        """
        Helper method which cheks whether the given dependent tasks were
        executed after their dependency was satisfied.
        """
        task_index = self.execution_list.index(task)
        for task in dependent_tasks:
            self.assertTrue(self.execution_list.index(task) > task_index)

    def tearDown(self):
        # Remove any extra plugins which may have been created during a test run
        BaseTask.plugins = self.original_plugins

    def test_simple_dependency(self, *args, **kwargs):
        """
        Tests creating a DAG of task dependencies when there is only one event
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        # Is the event dependency built correctly
        events = BaseTask.build_task_event_dependency_graph()
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events['a'][0]), 1)
        self.assertIn(A, events['a'][0])
        self.assertEqual(len(events['a'][1]), 1)
        self.assertIn(B, events['a'][1])

        # Is the DAG built correctly
        g = BaseTask.build_full_task_dag()
        self.assertEqual(len(g.all_nodes), 2)
        self.assertIn(A, g.all_nodes)
        self.assertIn(B, g.all_nodes)
        # B depends on A
        self.assertIn(B, g.dependent_nodes(A))

    def test_multiple_dependency(self, *args, **kwargs):
        """
        Tests creating a DAG of tasks dependencies when there are multiple
        events.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('A',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        g = BaseTask.build_full_task_dag()
        self.assertEqual(len(g.dependent_nodes(T0)), 5)
        self.assert_contains_all([T1, T2, T3, T4, T7], g.dependent_nodes(T0))

        self.assertEqual(len(g.dependent_nodes(T1)), 2)
        self.assert_contains_all([T5, T7], g.dependent_nodes(T1))

        self.assertEqual(len(g.dependent_nodes(T2)), 1)
        self.assert_contains_all([T6], g.dependent_nodes(T2))

        self.assertEqual(len(g.dependent_nodes(T3)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T3))

        self.assertEqual(len(g.dependent_nodes(T4)), 0)

        self.assertEqual(len(g.dependent_nodes(T5)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T5))

        self.assertEqual(len(g.dependent_nodes(T6)), 1)
        self.assert_contains_all([T8], g.dependent_nodes(T6))

        self.assertEqual(len(g.dependent_nodes(T7)), 0)

        self.assertEqual(len(g.dependent_nodes(T8)), 0)

    def test_run_job_simple(self, *args, **kwargs):
        """
        Tests running a job consisting of a simple dependency.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A, B])
        self.assert_task_dependency_preserved(A, [B])

    def test_run_job_by_task_name(self, *args, **kwargs):
        """
        Tests that the :func:`distro_tracker.core.tasks.run_task` function
        correctly runs a task when given its name, not a task class object.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        run_task(A.task_name())

        self.assert_executed_tasks_equal([A, B])
        self.assert_task_dependency_preserved(A, [B])

    def test_run_job_no_dependency(self, *args, **kwargs):
        """
        Tests running a job consisting of no dependencies.
        """
        self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class(('b',), (), ('b',))

        run_task(B)

        self.assert_executed_tasks_equal([B])

    def test_run_job_no_events_emitted(self, *args, **kwargs):
        """
        Tests running a job consisting of a simple dependency, but the event is
        not emitted during execution.
        """
        A = self.create_task_class(('a',), (), ())
        self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A])

    def test_run_job_complex_1(self, *args, **kwargs):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('A',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        self.create_task_class(('E',), ('B',), ('E',))  # T3
        self.create_task_class((), ('B',), ())  # T4
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        # Make sure the tasks which didn't have the appropriate events raised
        # during execution were not executed. These are tasks T3 and T4 in this
        # instance.
        self.assert_executed_tasks_equal([T0, T1, T2, T5, T6, T7, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T1, T2, T7])
        # Even though task T1 does not emit the event D1, it still needs to
        # execute before task T7.
        self.assert_task_dependency_preserved(T1, [T5, T7])
        self.assert_task_dependency_preserved(T2, [T6])
        self.assert_task_dependency_preserved(T5, [T8])
        self.assert_task_dependency_preserved(T6, [T8])

    def test_run_job_complex_2(self, *args, **kwargs):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        self.create_task_class(('D', 'D1'), ('A',), ('D'))  # T1
        self.create_task_class(('C',), ('A',), ('C',))      # T2
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        self.create_task_class(('evt-5',), ('D',), ('evt-5',))  # T5
        self.create_task_class(('evt-6',), ('C'), ('evt-6',))   # T6
        self.create_task_class((), ('D1', 'A'), ())             # T7
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        # In this test case, unlike test_run_job_complex_1, T0 emits event B so
        # no tasks depending on event A need to run.
        self.assert_executed_tasks_equal([T0, T3, T4, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T3, T4])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_3(self, *args, **kwargs):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B', 'B1'), (), ('B', 'B1'))
        self.create_task_class(('D', 'D1'), ('A',), ('D'))  # T1
        self.create_task_class(('C',), ('A',), ('C',))      # T2
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        self.create_task_class(('evt-5',), ('D',), ('evt-5',))  # T5
        self.create_task_class(('evt-6',), ('C'), ('evt-6',))   # T6
        T7 = self.create_task_class((), ('D1', 'A', 'B1'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        self.assert_executed_tasks_equal([T0, T3, T4, T7, T8])
        self.assert_task_dependency_preserved(T0, [T3, T4, T7])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_4(self, *args, **kwargs):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        self.create_task_class(('A', 'B'), (), ('B',))  # T0
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        self.create_task_class(('C',), ('A',), ('C',))  # T2
        self.create_task_class(('E',), ('B',), ('E',))  # T3
        self.create_task_class((), ('B',), ())          # T4
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        self.create_task_class(('evt-6',), ('C'), ('evt-6',))  # T6
        self.create_task_class((), ('D1', 'A'), ())            # T7
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8])

    def test_run_job_complex_5(self, *args, **kwargs):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        self.create_task_class(('A', 'B'), (), ('B',))  # T0
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D', 'D1'))
        self.create_task_class(('C',), ('A',), ('C',))  # T2
        self.create_task_class(('E',), ('B',), ('E',))  # T3
        self.create_task_class((), ('B',), ())          # T4
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        self.create_task_class(('evt-6',), ('C'), ('evt-6',))  # T6
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8, T7])

        self.assert_task_dependency_preserved(T1, [T7, T5])
        self.assert_task_dependency_preserved(T5, [T8])

    def test_run_all_tasks(self, *args, **kwargs):
        """
        Tests that all tasks are ran by calling the
        :func:`distro_tracker.core.tasks.run_all_tasks` function.
        """
        dependent_tasks = [
            self.create_task_class((), ('A',), ()),
            self.create_task_class((), ('B',), ()),
        ]
        independent_tasks = [
            self.create_task_class(('A',), (), ('A',)),
            self.create_task_class(('B',), (), ()),
        ]

        run_all_tasks()

        # All independent tasks were ran, along with the task whose dependency
        # was satisfied.
        self.assert_executed_tasks_equal(
            independent_tasks + [dependent_tasks[0]])
        # Makes sure the depenent task was executed after the dependency...
        self.assert_task_dependency_preserved(
            independent_tasks[0],
            [dependent_tasks[0]])

    def test_run_job_with_fail_task(self, *args, **kwargs):
        """
        Tests that running a job where one task fails works as expected.
        """
        fail_task = self.create_task_class(('fail',), (), ('fail'), fail=True)

        run_task(fail_task)

        # The job has gracefully exited without raising an exception.
        self.assert_executed_tasks_equal([fail_task])

    def test_run_job_with_fail_task_dependency(self, *args, **kwargs):
        """
        Tests that even though a task has failed, any events it raised while
        running affect the rest of the tasks.
        """
        root_task = self.create_task_class(('A',), (), ('A',))
        fail_task = self.create_task_class(('fail',), ('A',), ('fail',), True)
        depends_on_fail = self.create_task_class((), ('fail',), ())
        do_run = self.create_task_class((), ('A',), ())

        run_task(root_task)

        self.assert_executed_tasks_equal(
            [root_task, fail_task, depends_on_fail, do_run]
        )


class JobPersistenceTests(TestCase):
    def create_mock_event(self, event_name, event_arguments=None):
        mock_event = mock.create_autospec(Event)
        mock_event.name = event_name
        mock_event.arguments = event_arguments
        return mock_event

    def create_mock_task(self, task_name, events=()):
        mock_task = mock.create_autospec(BaseTask)
        mock_task.task_name.return_value = task_name
        mock_task.raised_events = [
            self.create_mock_event(event['name'], event.get('arguments', None))
            for event in events
        ]
        return mock_task

    def test_serialize_start(self):
        """
        Tests serializing a job's state to a RunningJob instance.
        """
        state = JobState('initial-task-name')
        state.save_state()

        # A running job was created.
        self.assertEqual(RunningJob.objects.count(), 1)
        job = RunningJob.objects.all()[0]
        self.assertEqual(job.initial_task_name, 'initial-task-name')
        self.assertIsNone(job.additional_parameters)
        self.assertFalse(job.is_complete)

    def test_serialize_after_processed_task(self):
        """
        Tests serializing a job's state to a RunningJob instance.
        """
        task_name = 'task-1'
        state = JobState(task_name)
        state.save_state()
        expected_events = [
            {
                'name': 'event-1',
                'arguments': ['a', 'b'],
            },
            {
                'name': 'event-2',
                'arguments': None,
            }
        ]
        mock_task = self.create_mock_task(task_name, expected_events)

        state.add_processed_task(mock_task)
        state.save_state()

        # Stil only one running job instance
        self.assertEqual(RunningJob.objects.count(), 1)
        job = RunningJob.objects.all()[0]
        self.assertSequenceEqual(job.state['events'], expected_events)
        self.assertSequenceEqual(job.state['processed_tasks'], [task_name])
        self.assertFalse(job.is_complete)

    def test_serialize_after_finish(self):
        """
        Tests serializing a job's state to a RunningJob instance.
        """
        task_name = 'task-1'
        state = JobState(task_name)
        state.save_state()
        expected_events = [
            {
                'name': 'event-1',
                'arguments': ['a', 'b'],
            },
            {
                'name': 'event-2',
                'arguments': None,
            }
        ]
        mock_task = self.create_mock_task(task_name, expected_events)

        state.add_processed_task(mock_task)
        state.save_state()
        state.mark_as_complete()

        # Stil only one running job instance
        self.assertEqual(RunningJob.objects.count(), 1)
        job = RunningJob.objects.all()[0]
        self.assertSequenceEqual(job.state['events'], expected_events)
        self.assertSequenceEqual(job.state['processed_tasks'], [task_name])
        self.assertTrue(job.is_complete)

    def test_serialize_after_update(self):
        """
        Tests serializing a job's state after multiple tasks have finished.
        """
        task_names = ['task-1', 'task-2']
        state = JobState(task_names[0])
        state.save_state()
        expected_events = [
            {
                'name': 'event-1',
                'arguments': {
                    'a': 1,
                    'b': '2'
                },
            },
            {
                'name': 'event-2',
                'arguments': None,
            }
        ]
        mock_task_1 = self.create_mock_task(task_names[0], [expected_events[0]])
        state.add_processed_task(mock_task_1)
        state.save_state()

        mock_task_2 = self.create_mock_task(task_names[1], [expected_events[1]])
        state.add_processed_task(mock_task_2)
        state.save_state()

        # Stil only one running job instance
        self.assertEqual(RunningJob.objects.count(), 1)
        job = RunningJob.objects.all()[0]
        # All events found now
        self.assertSequenceEqual(job.state['events'], expected_events)
        # Both tasks processed
        self.assertSequenceEqual(job.state['processed_tasks'], task_names)
        self.assertFalse(job.is_complete)

    def test_deserialize(self):
        """
        Tests deserializing a RunningJob instance to a JobState.
        """
        initial_task_name = 'initial-task'
        additional_parameters = {
            'param1': 1
        }
        job = RunningJob.objects.create(
            initial_task_name=initial_task_name,
            additional_parameters=additional_parameters)
        processed_tasks = ['initial-task', 'task-1']
        job.state = {
            'events': [
                {
                    'name': 'event-1',
                },
                {
                    'name': 'event-2',
                    'arguments': {
                        'a': 1,
                        'b': '2'
                    }
                }
            ],
            'processed_tasks': processed_tasks
        }
        job.save()

        state = JobState.deserialize_running_job_state(job)

        self.assertEqual(state.initial_task_name, 'initial-task')
        self.assertEqual(state.additional_parameters, additional_parameters)
        self.assertEqual(state.processed_tasks, processed_tasks)

        self.assertEqual(len(state.events), 2)
        self.assertEqual(state.events[0].name, 'event-1')
        self.assertIsNone(state.events[0].arguments)
        self.assertEqual(state.events[1].arguments, {
            'a': 1,
            'b': '2'
        })
        self.assertEqual(state._running_job, job)


class ContinuePersistedJobsTest(TestCase):
    def setUp(self):
        #: Tasks which execute add themselves to this list.
        self._created_task_count = 0
        self.execution_list = []
        self.original_plugins = [
            plugin
            for plugin in BaseTask.plugins
        ]
        # Now ignore all original plugins.
        BaseTask.plugins = []

    def tearDown(self):
        # Remove any extra plugins which may have been created during a test run
        BaseTask.plugins = self.original_plugins

    def clear_executed_tasks_list(self):
        self.execution_list[:] = []

    def assert_task_ran(self, task):
        self.assertIn(task, self.execution_list)

    def create_task_class(self, produces, depends_on, raises, fail=False):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        self._created_task_count += 1
        exec_list = self.execution_list

        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on
            NAME = 'a' * self._created_task_count

            def execute(self):
                for event in raises:
                    self.raise_event(event)
                exec_list.append(self.__class__)
                if fail:
                    raise Exception("This task fails")
        return TestTask

    def test_continue_job_no_start(self):
        """
        Tests continuing a job from a job state which is only at the beginning.
        """
        task1 = self.create_task_class(('a',), (), ('a',))
        job_state = JobState(task1.task_name())

        continue_task_from_state(job_state)

        self.assert_task_ran(task1)

    def test_continue_job_started(self):
        """
        Tests continuing a job from a job state which has only just started
        (no tasks complete yet).
        """
        task1 = self.create_task_class(('a',), (), ('a',))
        job_state = JobState(task1.task_name())

        continue_task_from_state(job_state)

        self.assert_task_ran(task1)

    def test_continue_job_some_finished(self):
        """
        Tests continuing a job from a job state where a task has finished.
        """
        task1 = self.create_task_class(('a',), (), ('a',))
        task2 = self.create_task_class((), ('a',), ())
        job_state = JobState(task1.task_name())
        task1_instance = task1()
        task1_instance.execute()
        job_state.add_processed_task(task1_instance)
        job_state.save_state()

        self.clear_executed_tasks_list()
        continue_task_from_state(job_state)

        # Only one task ran
        self.assertEqual(len(self.execution_list), 1)
        # It was the one that was not completed before the continue
        self.assert_task_ran(task2)

    def test_continue_job_finished(self):
        """
        Tests continuing a job from a job state where the job was finished.
        """
        task1 = self.create_task_class(('a',), (), ('a',))
        job_state = JobState(task1.task_name())
        task1_instance = task1()
        task1_instance.execute()
        job_state.add_processed_task(task1_instance)
        job_state.save_state()

        self.clear_executed_tasks_list()
        continue_task_from_state(job_state)

        # No tasks were ran from the continue
        self.assertEqual(len(self.execution_list), 0)
