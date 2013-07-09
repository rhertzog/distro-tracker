# -*- coding: utf-8 -*-

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
Tests for the PTS core's tasks framework.
"""
from __future__ import unicode_literals
from django.test import SimpleTestCase
from pts.core.tasks import BaseTask

from pts.core.tasks import run_task
from pts.core.tasks import build_task_event_dependency_graph
from pts.core.tasks import build_full_task_dag


class JobTests(SimpleTestCase):
    def create_task_class(self, produces, depends_on, raises):
        """
        Helper method creates and returns a new BaseTask subclass.
        """
        exec_list = self.execution_list

        class TestTask(BaseTask):
            PRODUCES_EVENTS = produces
            DEPENDS_ON_EVENTS = depends_on

            def execute(self):
                for event in raises:
                    self.raise_event(event)
                exec_list.append(self.__class__)
        return TestTask

    def assert_contains_all(self, items, container):
        """
        Asserts that all of the given items are found in the given container.
        """
        for item in items:
            self.assertIn(item, container)

    def setUp(self):
        #: Tasks which execute add themselves to this list.
        self.execution_list = []
        self.original_plugins = [
            plugin
            for plugin in BaseTask.plugins
        ]
        # Now ignore all original plugins.
        BaseTask.plugins = []

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
        executed after their dependency was satisifed.
        """
        task_index = self.execution_list.index(task)
        for task in dependent_tasks:
            self.assertTrue(self.execution_list.index(task) > task_index)

    def tearDown(self):
        # Remove any extra plugins which may have been created during a test run
        BaseTask.plugins = self.original_plugins

    def test_simple_dependency(self):
        """
        Tests creating a DAG of task dependencies when there is only one event
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        # Is the event dependency built correctly
        events = build_task_event_dependency_graph()
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events['a'][0]), 1)
        self.assertIn(A, events['a'][0])
        self.assertEqual(len(events['a'][1]), 1)
        self.assertIn(B, events['a'][1])

        # Is the DAG built correctly
        g = build_full_task_dag()
        self.assertEqual(len(g.all_nodes), 2)
        self.assertIn(A, g.all_nodes)
        self.assertIn(B, g.all_nodes)
        # B depends on A
        self.assertIn(B, g.dependent_nodes(A))

    def test_multiple_dependency(self):
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

        g = build_full_task_dag()
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

    def test_run_job_simple(self):
        """
        Tests running a job consisting of a simple dependency.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A, B])
        self.assert_task_dependency_preserved(A, [B])

    def test_run_job_no_dependency(self):
        """
        Tests running a job consisting of no dependencies.
        """
        A = self.create_task_class(('a',), (), ('a',))
        B = self.create_task_class(('b',), (), ('b',))

        run_task(B)

        self.assert_executed_tasks_equal([B])

    def test_run_job_no_events_emitted(self):
        """
        Tests running a job consisting of a simple dependency, but the event is
        not emitted during execution.
        """
        A = self.create_task_class(('a',), (), ())
        B = self.create_task_class((), ('a',), ())

        run_task(A)

        self.assert_executed_tasks_equal([A])

    def test_run_job_complex_1(self):
        """
        Tests running a job consisting of complex dependencies.
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

        run_task(T0)

        # Make sure the tasks which didn't have the appropriate events raised
        # during execution were not executed. These are tasks T3 and T4 in this
        # instance.
        self.assert_executed_tasks_equal([T0, T1, T2, T5, T6, T7, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T1, T2, T7])
        ## Even though task T1 does not emit the event D1, it still needs to
        ## execute before task T7.
        self.assert_task_dependency_preserved(T1, [T5, T7])
        self.assert_task_dependency_preserved(T2, [T6])
        self.assert_task_dependency_preserved(T5, [T8])
        self.assert_task_dependency_preserved(T6, [T8])

    def test_run_job_complex_2(self):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        # In this test case, unlike test_run_job_complex_1, T0 emits event B so
        # no tasks depending on event A need to run.
        self.assert_executed_tasks_equal([T0, T3, T4, T8])
        # Check execution order.
        self.assert_task_dependency_preserved(T0, [T3, T4])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_3(self):
        """
        Tests running a job consisting of complex dependencies.
        """
        T0 = self.create_task_class(('A', 'B', 'B1'), (), ('B', 'B1'))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A', 'B1'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T0)

        self.assert_executed_tasks_equal([T0, T3, T4, T7, T8])
        self.assert_task_dependency_preserved(T0, [T3, T4, T7])
        self.assert_task_dependency_preserved(T3, [T8])

    def test_run_job_complex_4(self):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8])

    def test_run_job_complex_5(self):
        """
        Tests running a job consisting of complex dependencies when the initial
        task is not the task which has 0 dependencies in the full tasks DAG.
        """
        T0 = self.create_task_class(('A', 'B'), (), ('B',))
        T1 = self.create_task_class(('D', 'D1'), ('A',), ('D', 'D1'))
        T2 = self.create_task_class(('C',), ('A',), ('C',))
        T3 = self.create_task_class(('E',), ('B',), ('E',))
        T4 = self.create_task_class((), ('B',), ())
        T5 = self.create_task_class(('evt-5',), ('D',), ('evt-5',))
        T6 = self.create_task_class(('evt-6',), ('C'), ('evt-6',))
        T7 = self.create_task_class((), ('D1', 'A'), ())
        T8 = self.create_task_class((), ('evt-5', 'evt-6', 'E'), ())

        run_task(T1)

        self.assert_executed_tasks_equal([T1, T5, T8, T7])

        self.assert_task_dependency_preserved(T1, [T7, T5])
        self.assert_task_dependency_preserved(T5, [T8])


