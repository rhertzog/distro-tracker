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

from django.db.models.query import QuerySet
from django.test.utils import override_settings

from distro_tracker.core.models import (
    Repository,
    SourcePackage,
    SourcePackageName,
    SourcePackageRepositoryEntry,
    TaskData,
)
from distro_tracker.core.tasks.base import (
    BaseTask,
    build_all_tasks,
    import_all_tasks,
    run_all_tasks,
    run_task,
)
from distro_tracker.core.tasks.mixins import (
    ProcessItems,
    ProcessModel,
    ProcessSourcePackage,
    ProcessMainRepoEntry,
    ProcessSrcRepoEntry,
    ProcessSrcRepoEntryInDefaultRepository,
)
from distro_tracker.core.tasks.schedulers import Scheduler, IntervalScheduler
from distro_tracker.core.utils import now
from distro_tracker.core.utils.misc import get_data_checksum
from distro_tracker.test import TestCase


def get_test_task_class(name, mixins=None, attributes=None):
    if not attributes:
        attributes = {}
    cls = BaseTask.get_task_class_by_name(attributes.get('NAME', name))
    if not cls:
        bases = (BaseTask,)
        if mixins:
            bases += mixins
        cls = type(name, bases, attributes)
    return cls


class BaseTaskTests(TestCase):

    def setUp(self):
        self.cls = get_test_task_class('TestTask')
        self.task = self.cls()
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
        self.assertIn(self.cls, BaseTask.plugins)

    # task.initialize()
    def test_task_init_runs_initialize_with_args_and_kwargs(self):
        with mock.patch.object(self.cls, 'initialize') as initialize:
            self.cls('abc', keyword='keyword')
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
        self.assertEqual(self.cls.task_name(), 'TestTask')
        self.assertEqual(self.task.task_name(), 'TestTask')

    def test_task_can_override_name(self):
        cls = get_test_task_class('Test2Task', attributes={'NAME': 'Test2'})
        self.assertEqual(cls.task_name(), 'Test2')
        self.assertEqual(cls().task_name(), 'Test2')

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

    def test_task_save_data_forwards_kwargs(self):
        task_data = self.init_task_data()
        self.task.data.update(self.sample_data)

        self.task.save_data(data_checksum='fakechecksum')

        task_data.refresh_from_db()
        self.assertEqual(task_data.version, 1)
        self.assertEqual(task_data.data_checksum, 'fakechecksum')

    # task.data_is_modified
    def test_data_is_modified_defaults_to_false(self):
        self.assertIs(self.task.data_is_modified, False)

    def test_data_is_modified_is_none_after_data_access(self):
        self.task.data
        self.assertIsNone(self.task.data_is_modified)

    def test_data_is_modified_is_still_true_after_data_access(self):
        self.task.data_is_modified = True
        self.task.data
        self.assertIs(self.task.data_is_modified, True)

    def test_data_is_modified_is_reset_after_save_data(self):
        self.task.refresh_data()
        self.task.data_is_modified = True
        self.task.save_data()
        self.assertIs(self.task.data_is_modified, False)

    def test_data_mark_modified(self):
        self.assertIs(self.task.data_is_modified, False)
        self.task.data_mark_modified()
        self.assertIs(self.task.data_is_modified, True)

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
                         self.cls)

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

    # task.handle_event()
    def test_task_register_and_handle_event(self):
        args = ['a']
        kwargs = {'foo': 'bar'}
        event_handler = mock.MagicMock()

        self.task.register_event_handler('event-name', event_handler)
        event_handler.assert_not_called()

        self.task.handle_event('event-name', *args, **kwargs)
        event_handler.assert_called_with(*args, **kwargs)

    def test_task_handle_unknown_event_without_handler(self):
        self.task.handle_event('event-name')

    def test_task_register_and_handle_event_multiple_handlers(self):
        event_handler1 = mock.MagicMock()
        event_handler2 = mock.MagicMock()
        self.task.register_event_handler('event-name', event_handler1)
        self.task.register_event_handler('event-name', event_handler2)

        self.task.handle_event('event-name')

        event_handler1.assert_called_once_with()
        event_handler2.assert_called_once_with()

    def test_task_register_same_handler_multiple_times(self):
        event_handler = mock.MagicMock()
        self.task.register_event_handler('event-name', event_handler)
        self.task.register_event_handler('event-name', event_handler)

        self.task.handle_event('event-name')

        self.assertEqual(event_handler.call_count, 1)

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

    def test_task_execute_does_not_call_save_data_if_not_modified(self):
        self.task.refresh_data()
        self.task.data_is_modified = False
        with mock.patch.object(self.task, 'save_data') as mock_save_data:
            self.task.execute()
            mock_save_data.assert_not_called()

    def test_task_execute_does_call_save_data_if_modified(self):
        self.task.refresh_data()
        self.task.data_is_modified = True
        with mock.patch.object(self.task, 'save_data') as mock_save_data:
            self.task.execute()
            mock_save_data.assert_called_once_with()

    def test_task_execute_does_call_save_data_if_needed(self):
        self.task.data['foo'] = 'bar'
        self.task.save_data()
        self.task.data['foo2'] = 'bar2'  # Data has been modified
        self.assertIsNone(self.task.data_is_modified)

        with mock.patch.object(self.task, 'save_data') as mock_save_data:
            self.task.execute()
            mock_save_data.assert_called_once_with(data_checksum=mock.ANY)

    def test_task_execute_does_not_call_save_data_if_not_needed(self):
        self.task.data['foo'] = 'bar'
        self.task.save_data()
        self.task.data['foo']  # Data has not been modified
        self.assertIsNone(self.task.data_is_modified)

        with mock.patch.object(self.task, 'save_data') as mock_save_data:
            self.task.execute()
            mock_save_data.assert_not_called()

    def test_task_execute_calls_handle_event(self):
        with mock.patch.object(self.task, 'handle_event') as mocked:
            self.task.execute()
            self.assertListEqual(
                mocked.mock_calls,
                [mock.call('execute-started'), mock.call('execute-finished')]
            )

    def test_task_execute_calls_handle_event_on_failure(self):
        self.setup_execute_for_failure()

        with mock.patch.object(self.task, 'handle_event') as mocked:
            try:
                self.task.execute()
            except Exception:
                pass
            self.assertListEqual(
                mocked.mock_calls,
                [mock.call('execute-started'), mock.call('execute-failed')]
            )


class SchedulerTests(TestCase):

    def setUp(self):
        self.cls = get_test_task_class('TestTask')
        self.task = self.cls()
        self.scheduler = Scheduler(self.task)

    def test_scheduler_needs_to_run(self):
        self.assertTrue(self.scheduler.needs_to_run())


class TestIntervalScheduler(IntervalScheduler):
    interval = 600


class IntervalSchedulerTests(TestCase):

    def setUp(self):
        self.cls = get_test_task_class('TestTask')
        self.task = self.cls()
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

    @mock.patch('distro_tracker.core.tasks.base.BaseTask.plugins',
                new_callable=mock.PropertyMock)
    def test_build_all_tasks_includes_tasks_from_BaseTask_plugins(
            self, mock_plugins):
        cls = get_test_task_class('TestTask')
        mock_plugins.return_value = [cls]
        result = build_all_tasks()
        self.assertListEqual(['TestTask'], list(result.keys()))

    @mock.patch('distro_tracker.core.tasks.base.BaseTask.plugins',
                new_callable=mock.PropertyMock)
    def test_build_all_tasks_fails_when_two_tasks_have_the_same_name(
            self, mock_plugins):
        cls = get_test_task_class('TestTask')
        mock_plugins.return_value = [cls, cls]
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


class ProcessItemsTests(TestCase):
    def setUp(self):
        self.cls = get_test_task_class('TestProcessItems', (ProcessItems,))
        self.task = self.cls()

    def patch_item_describe(self):
        def item_describe(item):
            return getattr(item, 'description', {})
        patcher = mock.patch.object(self.task, 'item_describe')
        self.mock_item_describe = patcher.start()
        self.mock_item_describe.side_effect = item_describe
        self.addCleanup(patcher.stop)
        return self.mock_item_describe

    def get_item(self, key):
        item = mock.MagicMock()
        item.__str__.return_value = key
        return item

    def test_item_to_key(self):
        item = self.get_item('key')

        self.assertEqual(self.task.item_to_key(item), 'key')

    def test_item_describe(self):
        '''item_describe() returns a dict describing the item'''
        item = self.get_item('key')

        self.assertIsInstance(self.task.item_describe(item), dict)

    def test_item_mark_processed_adds_key_in_processed_dict(self):
        item = self.get_item('key')

        self.task.item_mark_processed(item)

        self.assertIn('key', self.task.data['processed'])

    def test_item_mark_processed_stores_description_in_processed_dict(self):
        item = self.get_item('key')
        item.description = {'foo': 'bar'}
        self.patch_item_describe()

        self.task.item_mark_processed(item)

        self.assertDictEqual(item.description,
                             self.task.data['processed']['key'])

    def test_item_mark_processed_accepts_positional_arguments(self):
        args = [
            self.get_item('key1'),
            self.get_item('key2')
        ]

        self.task.item_mark_processed(*args)

        self.assertIn('key1', self.task.data['processed'])
        self.assertIn('key2', self.task.data['processed'])

    def test_item_mark_processed_sets_modified_flag(self):
        with mock.patch.object(self.task, 'data_mark_modified') as mocked:
            self.task.item_mark_processed(self.get_item('foo'))
            mocked.assert_called_once_with()

    def test_item_needs_processing(self):
        """An unknown item needs to be processed."""
        item = self.get_item('key')
        self.assertEqual(self.task.item_needs_processing(item), True)

    def test_item_needs_processing_with_already_processed_item(self):
        """An item already processed doesn't need processing."""
        item = self.get_item('key')
        self.task.item_mark_processed(item)

        self.assertEqual(self.task.item_needs_processing(item), False)

    def test_items_all(self):
        """items_all() is meant to be overriden the class using the mixin."""
        with self.assertRaises(NotImplementedError):
            self.task.items_all()

    def patch_items_all(self, keys=None, items=None):
        if keys is None:
            keys = ['key %d' % i for i in range(10)]
        if items is None:
            items = [self.get_item(key) for key in keys]

        patcher = mock.patch.object(self.task, 'items_all')
        self.mock_items_all = patcher.start()
        self.mock_items_all.return_value = items
        self.addCleanup(patcher.stop)

        return items

    def mark_some_processed_return_unprocessed(self, items):
        not_processed = []
        for i, item in enumerate(items):
            if i % 2 == 0:
                self.task.item_mark_processed(item)
            else:
                not_processed.append(item)
        return not_processed

    def test_items_to_process(self):
        """
        items_to_process() is the subset of items_all() that needs to
        be processed
        """
        items = self.patch_items_all()
        not_processed = self.mark_some_processed_return_unprocessed(items)

        result = self.task.items_to_process()

        self.assertSetEqual(set(result), set(not_processed))

    def test_items_to_process_with_force_update(self):
        """
        items_to_process() is the same as items_all() when force_udpate=True
        """
        self.task.force_update = True
        items = self.patch_items_all()
        self.mark_some_processed_return_unprocessed(items)

        result = self.task.items_to_process()

        self.assertSetEqual(set(result), set(items))

    def test_items_all_keys(self):
        """items_all_keys() returns a set of item_to_key() on items_all()"""
        items = self.patch_items_all()
        keys = [self.task.item_to_key(item) for item in items]

        result = self.task.items_all_keys()

        self.assertIsInstance(result, set)
        self.assertSetEqual(result, set(keys))

    def setup_item_to_cleanup(self, description=None):
        items = self.patch_items_all()
        unused_item = self.get_item('unused')
        if description:
            unused_item.description = description
        self.task.item_mark_processed(unused_item)
        self.task.item_mark_processed(*items[0:2])
        return unused_item

    def test_items_to_cleanup(self):
        """items_to_cleanup() iterates over items that disappeared"""
        self.patch_item_describe()
        description = {'foo': 'bar'}
        self.setup_item_to_cleanup(description)

        count = 0
        for key, data in self.task.items_to_cleanup():
            self.assertEqual(key, 'unused')
            self.assertDictEqual(data, description)
            count += 1
        self.assertEqual(count, 1)

    def test_items_cleanup_processed_list(self):
        """drops keys not associated to any object from the processed list"""
        unused_item = self.setup_item_to_cleanup()

        # Check the removal from the processed list through return value of
        # task.item_needs_processing()
        self.assertFalse(self.task.item_needs_processing(unused_item))
        self.task.items_cleanup_processed_list()
        self.assertTrue(self.task.item_needs_processing(unused_item))

    def test_items_cleanup_processed_list_does_mark_data_modified(self):
        '''when items are cleaned up, data is modified'''
        self.setup_item_to_cleanup()

        with mock.patch.object(self.task, 'data_mark_modified') as mocked:
            self.task.items_cleanup_processed_list()
            mocked.assert_called_once_with()

    def test_items_cleanup_processed_list_does_not_mark_data_modified(self):
        '''nothing to cleanup, no data modified'''
        self.patch_items_all()
        with mock.patch.object(self.task, 'data_mark_modified') as mocked:
            self.task.items_cleanup_processed_list()
            mocked.assert_not_called()

    def test_execute_does_cleanup_processed_list(self):
        unused_item = self.setup_item_to_cleanup()

        # Check the removal from the processed list through return value of
        # task.item_needs_processing()
        self.assertFalse(self.task.item_needs_processing(unused_item))
        self.task.execute()
        self.assertTrue(self.task.item_needs_processing(unused_item))


class ProcessModelTests(TestCase):
    def setUp(self):
        self.cls = get_test_task_class('TestProcessModel',
                                       (ProcessModel,),
                                       {'model': SourcePackageName})
        self.task = self.cls()

    def test_items_all_returns_queryset_of_the_model(self):
        queryset = self.task.items_all()
        self.assertIsInstance(queryset, QuerySet)
        self.assertEqual(queryset.model, self.cls.model)

    def test_items_all_allows_queryset_customizaton(self):
        '''items_extend_queryset() is called by items_all() at the end'''
        with mock.patch.object(self.task, 'items_extend_queryset') as mocked:
            mocked.return_value = mock.sentinel.extended_queryset
            queryset = self.task.items_all()
            mocked.assert_called_once_with(mock.ANY)
        self.assertIs(queryset, mock.sentinel.extended_queryset)

    def test_items_extend_queryset(self):
        '''default items_extend_queryset() just forwards the queryset'''
        queryset = mock.sentinel.queryset
        self.assertEqual(self.task.items_extend_queryset(queryset),
                         queryset)

    def test_item_to_key(self):
        '''item_to_key() uses the primary key'''
        srcpkgname = SourcePackageName.objects.create(name='dummy')
        self.assertEqual(self.task.item_to_key(srcpkgname), srcpkgname.pk)

    def test_items_all_keys(self):
        '''items_all_keys() uses an optimized query'''
        # Better implementation does not call item_to_key() in a loop
        srcpkgname = SourcePackageName.objects.create(name='dummy')
        with mock.patch.object(self.task, 'item_to_key') as mock_item_to_key:
            result = self.task.items_all_keys()
            mock_item_to_key.assert_not_called()

        expected = set([self.task.item_to_key(srcpkgname)])
        self.assertSetEqual(result, expected)

    def test_item_describe(self):
        srcpkgname = SourcePackageName.objects.create(name='dummy')
        self.task.fields_to_save = ('name', 'get_absolute_url')
        with mock.patch.object(srcpkgname, 'get_absolute_url') as mocked:
            mocked.return_value = mock.sentinel.url
            data = self.task.item_describe(srcpkgname)
            mocked.assert_called_once_with()
        self.assertEqual(data['name'], srcpkgname.name)
        self.assertIs(data['get_absolute_url'], mock.sentinel.url)


class ProcessSourcePackageTests(TestCase):
    def setUp(self):
        self.cls = get_test_task_class('TestProcessSourcePackage',
                                       (ProcessSourcePackage,))
        self.task = self.cls()
        self.pkg1_1 = self.create_source_package(name='pkg1', version='1')
        self.pkg1_2 = self.create_source_package(name='pkg1', version='2')
        self.pkg2_1 = self.create_source_package(name='pkg2', version='1')
        self.all_packages = [self.pkg1_1, self.pkg1_2, self.pkg2_1]

    def test_items_all_returns_source_packages(self):
        """Returned items are SourcePackage among those we created"""
        for item in self.task.items_all():
            self.assertIsInstance(item, SourcePackage)
            self.assertIn(item, self.all_packages)

    def test_item_describe_has_the_name_and_version_fields(self):
        data = self.task.item_describe(self.pkg1_1)
        self.assertEqual(data['name'], 'pkg1')
        self.assertEqual(data['version'], '1')


class ProcessSrcRepoEntryTests(TestCase):
    def setUp(self):
        self.cls = get_test_task_class('TestProcessSrcRepoEntry',
                                       (ProcessSrcRepoEntry,))
        self.task = self.cls()
        self.pkg1_1 = self.create_source_package(name='pkg1', version='1',
                                                 repository='default')
        self.pkg1_2 = self.create_source_package(name='pkg1', version='2',
                                                 repository='other')
        self.pkg2_1 = self.create_source_package(name='pkg2', version='1',
                                                 repository='default')
        self.all_packages = [self.pkg1_1, self.pkg1_2, self.pkg2_1]

    def test_items_all_returns_source_package_repository_entries(self):
        """
        Returned items are SourcePackageRepositoryEntry among those we created.
        """
        for item in self.task.items_all():
            self.assertIsInstance(item, SourcePackageRepositoryEntry)
            self.assertIn(item.source_package, self.all_packages)

    def test_item_describe_has_the_desired_fields(self):
        repo_entry = self.pkg1_1.repository_entries.first()
        data = self.task.item_describe(repo_entry)
        self.assertEqual(data['name'], repo_entry.source_package.name)
        self.assertEqual(data['version'], repo_entry.source_package.version)
        self.assertEqual(data['repository'], repo_entry.repository.shorthand)


class ProcessSrcRepoEntryInDefaultRepositoryTests(TestCase):
    def setUp(self):
        self.cls = get_test_task_class(
            'TestProcessSrcRepoEntryInDefaultRepository',
            (ProcessSrcRepoEntryInDefaultRepository,))
        self.task = self.cls()
        self.pkg_default = self.create_source_package(name='pkg-default',
                                                      repository='default')
        self.pkg_other = self.create_source_package(name='pkg-other',
                                                    repository='other')
        self.pkg_both = self.create_source_package(
            name='pkg-both', repositories=['default', 'other'])

    def test_items_all_contains_only_entries_from_default_repository(self):
        for item in self.task.items_all():
            self.assertNotEqual(item.source_package, self.pkg_other)
            self.assertEqual(item.repository.shorthand, 'default')


class ProcessMainRepoEntryTests(TestCase):

    def setUp(self):
        def execute_main(self):
            for item in self.items_to_process():
                self.item_mark_processed(item)

        self.cls = get_test_task_class('TestProcessMainRepoEntry',
                                       (ProcessMainRepoEntry,),
                                       {'execute_main': execute_main})
        self.task = self.cls()

    def get_item(self):
        for item in self.task.items_all():
            break
        return item

    def test_items_all_returns_entry_from_default_repository(self):
        self.create_source_package(name='pkg-default', version='1',
                                   repositories=['default', 'other'])
        self.create_source_package(name='pkg-default', version='2',
                                   repository='other2')

        for entry in self.task.items_all():
            self.assertEqual(entry.repository.shorthand, 'default')
            self.assertEqual(entry.source_package.name, 'pkg-default')
            self.assertEqual(entry.source_package.version, '1')
        self.assertEqual(len(self.task.items_all()), 1)

    def test_items_all_returns_max_version_from_non_default_repositories(self):
        for version in ('2', '3', '1'):
            self.create_source_package(name='pkg', version=version,
                                       repository='repo%s' % version)

        for entry in self.task.items_all():
            self.assertEqual(entry.repository.shorthand, 'repo3')
            self.assertEqual(entry.source_package.name, 'pkg')
            self.assertEqual(entry.source_package.version, '3')
        self.assertEqual(len(self.task.items_all()), 1)

    def test_items_all_returns_max_version_from_default_repository(self):
        for version in ('1', '3', '2'):
            self.create_source_package(name='pkg-default', version=version,
                                       repository='default')

        for entry in self.task.items_all():
            self.assertEqual(entry.repository.shorthand, 'default')
            self.assertEqual(entry.source_package.name, 'pkg-default')
            self.assertEqual(entry.source_package.version, '3')
        self.assertEqual(len(self.task.items_all()), 1)

    def test_items_all_uses_repository_position_to_disambiguate(self):
        self.create_source_package(name='pkg', version='1',
                                   repositories=['repo1', 'repo3', 'repo2'])
        for i in range(1, 4):
            repo = Repository.objects.get(shorthand='repo%d' % i)
            repo.position = i
            repo.save()
        for entry in self.task.items_all():
            self.assertEqual(entry.repository.shorthand, 'repo3')
        self.assertEqual(len(self.task.items_all()), 1)

    def test_item_to_key_uses_database_id(self):
        self.create_source_package(repository='default')
        item = self.get_item()

        self.assertEqual(self.task.item_to_key(item), item.id)

    def test_item_describe(self):
        self.create_source_package(repository='default')
        item = self.get_item()

        self.assertDictEqual(
            self.task.item_describe(item),
            {
                'name': item.source_package.name,
                'version': item.source_package.version,
                'repository': item.repository.shorthand
            }
        )

    def test_items_to_process_returns_a_former_main_entry(self):
        # Version 1 is the main entry
        self.create_source_package(name='pkg', version='1', repository='other')
        self.task.execute()
        # Now version 2 is the main entry
        pkg_2 = self.create_source_package(name='pkg', version='2',
                                           repository='default')
        self.task.execute()
        # We drop v2, v1 should again be the main version
        pkg_2.delete()

        for entry in self.task.items_to_process():
            self.assertEqual(entry.source_package.version, '1')
        self.assertEqual(len(list(self.task.items_to_process())), 1)

    def test_items_all_caches_results(self):
        with self.assertNumQueries(2):
            self.task.items_all()  # 2 queries here
            self.task.items_all()  # none here

    def test_clear_main_entries_cache(self):
        with self.assertNumQueries(2):
            self.task.items_all()  # 2 queries here
        self.task.clear_main_entries_cache()
        with self.assertNumQueries(2):
            self.task.items_all()  # and 2 again here

    def test_clear_main_entries_cached_called_during_execute(self):
        with mock.patch.object(self.cls, 'clear_main_entries_cache') as mocked:
            self.task = self.cls()
            self.task.execute()
            self.assertEqual(mocked.call_count, 2)
