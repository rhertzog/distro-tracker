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
Tests for the :mod:`pts.extract_source_files` app.
"""

from __future__ import unicode_literals
from django.test import TestCase
from pts.core.models import SourcePackage, SourcePackageName
from pts.core.models import ExtractedSourceFile
from pts.core.tasks import JobState, Event, Job
from pts.core.tests.common import make_temp_directory
from pts.extract_source_files.pts_tasks import ExtractSourcePackageFiles
from django.utils.six.moves import mock

import os


class ExtractSourcePackageFilesTest(TestCase):
    """
    Tests for the task :class:`pts.extract_source_files.ExtractSourcePackageFiles`.
    """
    def setUp(self):
        self.job_state = mock.create_autospec(JobState)
        self.job_state.events_for_task.return_value = []
        self.job = mock.create_autospec(Job)
        self.job.job_state = self.job_state
        self.task = ExtractSourcePackageFiles()
        self.task.job = self.job

    def add_mock_event(self, name, arguments):
        """
        Helper method adding mock events which the task will have access to
        when it runs.
        """
        self.job_state.events_for_task.return_value.append(
            Event(name=name, arguments=arguments)
        )

    def run_task(self):
        self.task.execute()

    @mock.patch('pts.extract_source_files.pts_tasks.AptCache.retrieve_source')
    def test_create_extracted_files(self, mock_cache):
        """
        Tests that the task creates an
        :class:`pts.core.models.ExtractedSourceFile` instance.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')
        self.add_mock_event('new-source-package-version', {
            'pk': package.pk,
        })

        with make_temp_directory('-pts-media') as temp_media_dir, make_temp_directory('pts-pkg-dir') as pkg_directory:
            debian_dir = os.path.join(pkg_directory, 'debian')
            os.makedirs(debian_dir)
            changelog_path = os.path.join(debian_dir, 'changelog')
            with open(changelog_path, 'w') as f:
                f.write('Contents')
            # This file should not be included in the extracted files.
            other_file = os.path.join(debian_dir, 'some-file')
            with open(other_file, 'w') as f:
                f.write('Contents')

            mock_cache.return_value = os.path.join(pkg_directory)

            with self.settings(MEDIA_ROOT=temp_media_dir):
                self.run_task()

                # Check that the file was created.
                self.assertEqual(1, ExtractedSourceFile.objects.count())
                # Check that it has the correct name
                extracted_file = ExtractedSourceFile.objects.all()[0]
                self.assertEqual('changelog', extracted_file.name)

    @mock.patch('pts.extract_source_files.pts_tasks.AptCache.retrieve_source')
    def test_create_extracted_files_only_wanted_files(self, mock_cache):
        """
        Tests that the task creates an
        :class:`pts.core.models.ExtractedSourceFile` instance.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')
        self.add_mock_event('new-source-package-version', {
            'pk': package.pk,
        })

        with make_temp_directory('-pts-media') as temp_media_dir, make_temp_directory('pts-pkg-dir') as pkg_directory:
            debian_dir = os.path.join(pkg_directory, 'debian')
            os.makedirs(debian_dir)
            wanted_files = [
                'changelog',
                'copyright',
                'rules',
                'control',
                'watch',
            ]
            all_files = wanted_files + [
                'other-file',
            ]
            for file_name in all_files:
                file_path = os.path.join(debian_dir, file_name)
                with open(file_path, 'w') as f:
                    f.write('Contents')

            mock_cache.return_value = os.path.join(pkg_directory)

            with self.settings(MEDIA_ROOT=temp_media_dir):
                self.run_task()

                # Check that only the wanted files are created!
                self.assertEqual(len(wanted_files), ExtractedSourceFile.objects.count())
                extracted_names = [
                    extracted_file.name
                    for extracted_file in ExtractedSourceFile.objects.all()
                ]
                for wanted_file in wanted_files:
                    self.assertIn(wanted_file, extracted_names)