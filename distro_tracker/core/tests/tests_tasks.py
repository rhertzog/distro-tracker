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
from unittest import mock

from distro_tracker.core.models import TaskData
from distro_tracker.core.tasks.base import BaseTask
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

    def test_task_is_registered(self):
        """A task class is automatically registered when created"""
        self.assertIn(TestTask, BaseTask.plugins)

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
        task_data = TaskData(task_name=self.task.task_name(),
                             data=self.sample_data)
        task_data.save()
        self.assertDictEqual(self.task.data, self.sample_data)

    # task.save_data()
    def test_task_save_data(self):
        """task.save_data() stores the data in the TaskData model"""
        self.task.data['foo'] = 'bar'
        self.task.save_data()
        task_data = TaskData.objects.get(task_name=self.task.task_name())
        self.assertEqual(task_data.data['foo'], 'bar')

    def test_task_save_data_uses_versioned_update(self):
        task_data = TaskData.objects.create(task_name=self.task.task_name())
        self.assertEqual(task_data.version, 0)
        self.task.data.update(self.sample_data)

        self.task.save_data()

        task_data.refresh_from_db()
        self.assertEqual(task_data.version, 1)

    def test_task_save_data_on_outdated_data(self):
        task_data = TaskData.objects.create(task_name=self.task.task_name())
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
