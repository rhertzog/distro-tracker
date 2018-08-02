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
import logging
from datetime import timedelta
from unittest import mock

from django.test.utils import override_settings

from distro_tracker.core.models import TaskData
from distro_tracker.core.tasks.base import (
    BaseTask,
    build_all_tasks,
    import_all_tasks,
    run_all_tasks,
    run_task,
)
from distro_tracker.core.tasks.schedulers import Scheduler, IntervalScheduler
from distro_tracker.core.utils import now
from distro_tracker.core.utils.misc import get_data_checksum
from distro_tracker.test import TestCase


class TestTask(BaseTask):
    pass


class Test2Task(BaseTask):
    NAME = 'Test2'


class BaseTaskTests(TestCase):

    def setUp(self):
        self.task = TestTask()
        self.sample_data = {'foo': 'bar'}
        self.sample_data_checksum = get_data_checksum(self.sample_data)

    def init_task_data(self, **kwargs):
        kwargs['task_name'] = self.task.task_name()
        task_data = TaskData(**kwargs)
        task_data.save()
        return task_data

    def check_field_in_task_data(self, field, value):
        task_data = TaskData.objects.get(task_name=self.task.task_name())
        if isinstance(value, dict):
            self.assertDictEqual(getattr(task_data, field), value)
        else:
            self.assertEqual(getattr(task_data, field), value)

    def setup_execute_for_failure(self, exception=RuntimeError):
        """Ensure task.execute_foo() raises an exception"""
        self.task.execute_foo = mock.MagicMock()
        self.task.execute_foo.side_effect = exception

    def test_task_is_registered(self):
        """A task class is automatically registered when created"""
        self.assertIn(TestTask, BaseTask.plugins)

    # task.initialize()
    def test_task_init_runs_initialize_with_args_and_kwargs(self):
        with mock.patch.object(TestTask, 'initialize') as initialize:
            TestTask('abc', keyword='keyword')
            initialize.assert_called_with('abc', keyword='keyword')

    def test_task_initialize_with_force_update(self):
        self.task.initialize(force_update=True)
        self.assertEqual(self.task.force_update, True)

    def test_task_initialize_with_fake_update(self):
        self.task.initialize(fake_update=True)
        self.assertEqual(self.task.fake_update, True)

    def test_task_initialize_store_kwargs_in_parameters(self):
        parameters = {'key1': 'abc', 'key2': 'abc'}
        self.task.initialize(**parameters)
        self.assertDictEqual(self.task.parameters, parameters)

    # task.task_name()
    def test_task_has_a_default_name(self):
        self.assertEqual(TestTask.task_name(), 'TestTask')
        self.assertEqual(self.task.task_name(), 'TestTask')

    def test_task_can_override_name(self):
        self.assertEqual(Test2Task.task_name(), 'Test2')
        self.assertEqual(Test2Task().task_name(), 'Test2')

    # task.data
    def test_task_has_data_attribute(self):
        self.assertIsInstance(self.task.data, dict)

    def test_task_data_comes_from_database(self):
        """Accessing task.data loads the data from the TaskData model"""
        self.init_task_data(data=self.sample_data)

        self.assertDictEqual(self.task.data, self.sample_data)

    # task.task_data
    def test_task_has_task_data_attribute(self):
        self.assertIsInstance(self.task.task_data, TaskData)
        self.assertEqual(self.task.task_data.task_name,
                         self.task.task_name())

    # task.save_data()
    def test_task_save_data(self):
        """task.save_data() stores the data in the TaskData model"""
        self.task.data.update(self.sample_data)
        self.task.save_data()
        self.check_field_in_task_data('data', self.sample_data)

    def test_task_save_data_uses_versioned_update(self):
        task_data = self.init_task_data()
        self.assertEqual(task_data.version, 0)
        self.task.data.update(self.sample_data)

        self.task.save_data()

        task_data.refresh_from_db()
        self.assertEqual(task_data.version, 1)

    def test_task_save_data_on_outdated_data(self):
        task_data = self.init_task_data()
        self.task.data.update(self.sample_data)  # fetch the data from db
        task_data.version = 123  # ensure the task has an outdated version
        task_data.save()

        with self.assertRaises(BaseTask.ConcurrentDataUpdate):
            self.task.save_data()

    # task.log(...)
    @mock.patch('distro_tracker.core.tasks.base.logger')
    def test_task_log(self, logger):
        self.task.log('Foobar')
        logger.log.assert_called_with(logging.INFO, 'TestTask Foobar')

    @mock.patch('distro_tracker.core.tasks.base.logger')
    def test_task_log_with_level(self, logger):
        self.task.log('Foobar', level=logging.WARNING)
        logger.log.assert_called_with(logging.WARNING, 'TestTask Foobar')

    @mock.patch('distro_tracker.core.tasks.base.logger')
    def test_task_log_with_args(self, logger):
        self.task.log('%s', 'Foobar')
        logger.log.assert_called_with(logging.INFO, 'TestTask %s', 'Foobar')

    @mock.patch('distro_tracker.core.tasks.base.logger')
    def test_task_log_with_kwargs(self, logger):
        self.task.log('%(foo)s', foo='Foobar')
        logger.log.assert_called_with(logging.INFO, 'TestTask %(foo)s',
                                      foo='Foobar')

    # BaseTask.get_task_class_by_name()
    def test_get_task_class_by_name(self):
        self.assertEqual(BaseTask.get_task_class_by_name('TestTask'),
                         TestTask)

    def test_get_task_class_by_name_non_existing(self):
        self.assertIsNone(BaseTask.get_task_class_by_name('NonExisting'))

    # task.update_*
    def test_update_field(self):
        value = now()

        self.task.update_field('last_attempted_run', value)

        self.check_field_in_task_data('last_attempted_run', value)

    def test_update_field_does_not_modify_other_fields(self):
        value = now()
        # Initialize task with default values
        task_data = self.init_task_data()
        self.task.refresh_data()
        # Modify underlying data in database
        task_data.data = self.sample_data
        task_data.last_completed_run = value
        task_data.save()

        self.task.update_field('last_attempted_run', value)

        # Ensure the modified fields have not been overwritten with outdated
        # data from the task
        task_data.refresh_from_db()
        self.assertEqual(task_data.last_completed_run, value)
        self.assertDictEqual(task_data.data, self.sample_data)

    def test_update_field_is_able_to_reset_to_null(self):
        self.init_task_data(run_lock=now())
        self.task.update_field('run_lock', None)
        self.check_field_in_task_data('run_lock', None)

    def test_update_last_attempted_run(self):
        value = now()
        with mock.patch.object(self.task, 'update_field') as update_field:
            self.task.update_last_attempted_run(value)
            update_field.assert_called_with('last_attempted_run', value)

    def test_update_last_completed_run(self):
        value = now()
        with mock.patch.object(self.task, 'update_field') as update_field:
            self.task.update_last_completed_run(value)
            update_field.assert_called_with('last_completed_run', value)

    def test_update_task_is_pending(self):
        with mock.patch.object(self.task, 'update_field') as update_field:
            self.task.update_task_is_pending(True)
            update_field.assert_called_with('task_is_pending', True)

    # task.<field>() to retrieve values
    def test_task_is_pending(self):
        self.init_task_data(task_is_pending=True)
        self.assertTrue(self.task.task_is_pending)

    def test_last_attempted_run(self):
        value = now()
        self.init_task_data(last_attempted_run=value)
        self.assertEqual(self.task.last_attempted_run, value)

    def test_last_completed_run(self):
        value = now()
        self.init_task_data(last_completed_run=value)
        self.assertEqual(self.task.last_completed_run, value)

    # task.schedule()
    def test_task_has_a_scheduler(self):
        self.assertTrue(issubclass(self.task.Scheduler, Scheduler))
        self.assertTrue(isinstance(self.task.scheduler, Scheduler))

    def test_task_schedule_checks_with_scheduler(self):
        with mock.patch.object(self.task.scheduler, 'needs_to_run') as mocked:
            self.task.schedule()
            mocked.assert_called_with()

    def test_task_schedule_updates_task_is_pending(self):
        # default scheduler always returns True, no mocking needed
        self.assertFalse(self.task.task_is_pending)

        result = self.task.schedule()

        self.assertTrue(result)
        self.assertTrue(self.task.task_is_pending)

    def test_task_schedule_when_scheduler_says_no(self):
        with mock.patch.object(self.task.scheduler, 'needs_to_run') as mocked:
            mocked.return_value = False

            result = self.task.schedule()

            self.assertFalse(result)
            self.assertFalse(self.task.task_is_pending)

    def test_task_schedule_when_already_pending(self):
        self.init_task_data(task_is_pending=True)
        with mock.patch.object(self.task.scheduler, 'needs_to_run') as mocked:
            result = self.task.schedule()

            self.assertTrue(result)
            mocked.assert_not_called()

    # task.execute()
    def test_task_execute_calls_execute_sub_methods(self):
        self.task.execute_init = mock.MagicMock()
        self.task.execute_main = mock.MagicMock()
        self.task.execute()
        self.task.execute_init.assert_called_with()
        self.task.execute_main.assert_called_with()

    def test_task_execute_updates_timestamps(self):
        self.assertIsNone(self.task.last_attempted_run)
        self.assertIsNone(self.task.last_completed_run)

        self.task.execute()

        self.assertIsNotNone(self.task.last_attempted_run)
        self.assertIsNotNone(self.task.last_completed_run)
        self.assertEqual(self.task.last_attempted_run,
                         self.task.last_completed_run)

    def test_task_execute_field_updated_when_task_failed(self):
        self.init_task_data(task_is_pending=True)
        self.setup_execute_for_failure()

        try:
            self.task.execute()
        except RuntimeError:
            pass

        # Only the last_attempted_run field has been updated
        self.assertIsNotNone(self.task.last_attempted_run)
        self.assertIsNone(self.task.last_completed_run)
        self.assertTrue(self.task.task_is_pending)

    def test_task_execute_clears_task_is_pending(self):
        """When task.execute() finishes, it clears the task_is_pending flag."""
        self.init_task_data(task_is_pending=True)
        self.task.execute()
        self.assertFalse(self.task.task_is_pending)

    def test_task_execute_takes_the_lock(self):
        """Ensure the lock is taken to avoid concurrent runs"""
        with mock.patch.object(self.task.task_data, 'get_run_lock') as lock:
            lock.return_value = True
            self.task.execute()
            lock.assert_called_once_with()

    def test_task_execute_raises_exception_when_lock_fails(self):
        """Ensure failure with LockError when the lock fails"""
        lock_until = now() + timedelta(600)
        self.init_task_data(run_lock=lock_until)
        with self.assertRaises(BaseTask.LockError):
            self.task.execute()

    def test_task_execute_releases_lock_on_success(self):
        """Ensure task.execute() releases the lock (success case)"""
        self.task.execute()

        self.check_field_in_task_data('run_lock', None)

    def test_task_execute_releases_lock_on_failure(self):
        """Ensure task.execute() releases the lock (failure case)"""
        self.setup_execute_for_failure()

        try:
            self.task.execute()
        except RuntimeError:
            pass

        self.check_field_in_task_data('run_lock', None)

    def test_task_execute_does_not_catch_exceptions(self):
        """Ensure task.execute() does not catch exceptions"""
        self.setup_execute_for_failure()

        with self.assertRaises(RuntimeError):
            self.task.execute()


class SchedulerTests(TestCase):

    def setUp(self):
        self.task = TestTask()
        self.scheduler = Scheduler(self.task)

    def test_scheduler_needs_to_run(self):
        self.assertTrue(self.scheduler.needs_to_run())


class TestIntervalScheduler(IntervalScheduler):
    interval = 600


class IntervalSchedulerTests(TestCase):

    def setUp(self):
        self.task = TestTask()
        self.scheduler = TestIntervalScheduler(self.task)

    def build_class(self, interval):
        class MyClass(IntervalScheduler):
            pass
        MyClass.interval = interval
        return MyClass

    def test_get_interval_with_integer(self):
        cls = self.build_class(600)
        self.scheduler = cls(self.task)

        self.assertEqual(self.scheduler.get_interval(), 600)

    def test_get_interval_with_integer_as_string(self):
        cls = self.build_class('600')
        self.scheduler = cls(self.task)

        self.assertEqual(self.scheduler.get_interval(), 600)

    def test_get_interval_with_non_integer(self):
        cls = self.build_class('auie6')
        self.scheduler = cls(self.task)

        with self.assertRaises(ValueError):
            self.scheduler.get_interval()

    @mock.patch('distro_tracker.core.tasks.schedulers.now')
    def test_needs_to_run_interval_elapsed(self, mocked_now):
        last_try = now()
        self.task.update_last_attempted_run(last_try)
        # Current time for the scheduler is after the interval
        next_try = last_try + timedelta(seconds=1000)
        mocked_now.return_value = next_try

        self.assertTrue(self.scheduler.needs_to_run())

    @mock.patch('distro_tracker.core.tasks.schedulers.now')
    def test_needs_to_run_interval_not_elapsed(self, mocked_now):
        last_try = now()
        self.task.update_last_attempted_run(last_try)
        # Current time for the scheduler is after the interval
        next_try = last_try + timedelta(seconds=100)
        mocked_now.return_value = next_try

        self.assertFalse(self.scheduler.needs_to_run())


class TestRunTask(BaseTask):
    NAME = 'test_run_task'
    executed = []

    def execute_task(self):
        self.executed.append('yes')


class TaskUtilsTests(TestCase):

    def tearDown(self):
        TestRunTask.executed.clear()

    @override_settings(INSTALLED_APPS=['distro_tracker.html',
                                       'distro_tracker.stdver_warnings'])
    @mock.patch('distro_tracker.core.tasks.base.importlib')
    def test_import_all_tasks(self, mock_importlib):
        # called with one existing module and a non-existing one
        mock_importlib.import_module.side_effect = [ImportError, True]

        import_all_tasks()

        mock_importlib.import_module.assert_any_call(
            'distro_tracker.html.tracker_tasks')
        mock_importlib.import_module.assert_called_with(
            'distro_tracker.stdver_warnings.tracker_tasks')

    def test_run_task(self):
        result = run_task('test_run_task')
        self.assertIn('yes', TestRunTask.executed)
        self.assertTrue(result)

    def test_run_task_with_class(self):
        result = run_task(TestRunTask)
        self.assertIn('yes', TestRunTask.executed)
        self.assertTrue(result)

    def test_run_task_with_task_instance(self):
        result = run_task(TestRunTask())
        self.assertIn('yes', TestRunTask.executed)
        self.assertTrue(result)

    def test_run_task_with_unknown_object(self):
        with self.assertRaises(ValueError):
            run_task({})

    def test_run_task_raises_exception_when_not_existing(self):
        with self.assertRaises(ValueError):
            run_task('unknown')

    def test_run_task_returns_false_when_execution_fails(self):
        with mock.patch.object(TestRunTask, 'execute') as mock_execute:
            mock_execute.side_effect = RuntimeError
            result = run_task(TestRunTask)
            self.assertFalse(result)

    def test_build_all_tasks_returns_a_dict_of_all_tasks(self):
        result = build_all_tasks()

        self.assertIsInstance(result, dict)
        for name, obj in result.items():
            self.assertIsInstance(obj, BaseTask)
            self.assertEqual(name, obj.task_name())

    def test_build_all_tasks_filters_out_base_task(self):
        result = build_all_tasks()

        self.assertNotIn('BaseTask', result)

    @mock.patch('distro_tracker.core.tasks.base.BaseTask')
    def test_build_all_tasks_includes_tasks_from_BaseTask_plugins(
            self, mock_basetask):
        mock_basetask.plugins = [TestTask]
        result = build_all_tasks()
        self.assertListEqual(['TestTask'], list(result.keys()))

    @mock.patch('distro_tracker.core.tasks.base.BaseTask')
    def test_build_all_tasks_fails_when_two_tasks_have_the_same_name(
            self, mock_basetask):
        mock_basetask.plugins = [TestTask, TestTask]
        with self.assertRaises(ValueError):
            build_all_tasks()

    def setup_mock_build_all_tasks(self):
        patcher = mock.patch('distro_tracker.core.tasks.base.build_all_tasks')
        patcher_run = mock.patch('distro_tracker.core.tasks.base.run_task')
        self.mock_build_tasks = patcher.start()
        self.mock_run_task = patcher_run.start()
        self.mock_run_task.side_effect = lambda task: task.execute()

        self.update_repositories_task = mock.Mock(spec=BaseTask,
                                                  task_is_pending=True)
        self.update_repositories_task.schedule.return_value = True
        self.task1 = mock.Mock(spec=BaseTask, task_is_pending=False)
        self.task1.schedule.return_value = False
        self.task2 = mock.Mock(spec=BaseTask, task_is_pending=True)
        self.task2.schedule.return_value = True

        self.mock_build_tasks.return_value = {
            'Task2': self.task2,
            'Task1': self.task1,
            'UpdateRepositoriesTask': self.update_repositories_task,
        }

        self.addCleanup(patcher.stop)
        self.addCleanup(patcher_run.stop)
        return self.mock_build_tasks

    def test_run_all_tasks_builds_all_tasks(self):
        self.setup_mock_build_all_tasks()

        run_all_tasks()

        self.mock_build_tasks.assert_called_with()

    def test_run_all_tasks_runs_update_repositories_first(self):
        self.setup_mock_build_all_tasks()
        self.update_repositories_task.execute.side_effect = RuntimeError

        try:
            run_all_tasks()
        except RuntimeError:
            self.update_repositories_task.execute.assert_called_once_with()
            self.task1.execute.assert_not_called()
            self.task2.execute.assert_not_called()
        else:
            self.fail("UpdateRepositoriesTask has not been called")

    def test_run_all_tasks_schedules_and_respects_result(self):
        self.setup_mock_build_all_tasks()

        run_all_tasks()

        # All tasks have been scheduled
        self.update_repositories_task.schedule.assert_called_once_with()
        self.task1.schedule.assert_called_once_with()
        self.task2.schedule.assert_called_once_with()
        # Only task1 (whose task_is_pending is False) has not been executed
        self.update_repositories_task.execute.assert_called_once_with()
        self.task1.execute.assert_not_called()
        self.task2.execute.assert_called_once_with()

    def test_run_all_tasks_does_not_always_run_update_repositories(self):
        self.setup_mock_build_all_tasks()
        self.update_repositories_task.task_is_pending = False
        self.update_repositories_task.schedule.return_value = False

        run_all_tasks()

        self.update_repositories_task.execute.assert_not_called()
