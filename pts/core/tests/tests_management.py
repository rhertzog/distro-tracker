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
Tests for the PTS core management commands.
"""
from __future__ import unicode_literals
from django.test import SimpleTestCase
from django.utils.six.moves import mock
from django.core.management import call_command


class RunTaskManagementCommandTest(SimpleTestCase):
    """
    Test for the :mod:`pts.core.management.commands.pts_run_task` management
    command.
    """
    def run_command(self, tasks, **kwargs):
        call_command('pts_run_task', *tasks, **kwargs)

    @mock.patch('pts.core.management.commands.pts_run_task.run_task')
    def test_runs_all(self, mock_run_task):
        """
        Tests that the management command calls the
        :func:`run_task <pts.core.tasks.run_task>` function for each given task
        name.
        """
        self.run_command(['TaskName1', 'TaskName2'])

        # The run task was called only for the given commands
        self.assertEqual(2, mock_run_task.call_count)
        mock_run_task.assert_any_call('TaskName1', None)
        mock_run_task.assert_any_call('TaskName2', None)

    @mock.patch('pts.core.management.commands.pts_run_task.run_task')
    def test_passes_force_flag(self, mock_run_task):
        """
        Tests that the management command passes the force flag to the task
        invocations when it is given.
        """
        self.run_command(['TaskName1'], force=True)

        mock_run_task.assert_called_with('TaskName1', {
            'force_update': True,
        })
