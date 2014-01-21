# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Tests for the :mod:`distro_tracker.extract_source_files` app.
"""

from __future__ import unicode_literals
from django.test import TestCase
from django.core.files.base import ContentFile
from distro_tracker.core.models import SourcePackage, SourcePackageName
from distro_tracker.core.models import ExtractedSourceFile
from distro_tracker.core.tasks import JobState, Event, Job
from distro_tracker.core.tests.common import make_temp_directory
from distro_tracker.core.tests.common import temporary_media_dir
from distro_tracker.extract_source_files.tracker_tasks import ExtractSourcePackageFiles
from django.utils.six.moves import mock

import os


class ExtractSourcePackageFilesTest(TestCase):
    """
    Tests for the task :class:`distro_tracker.extract_source_files.ExtractSourcePackageFiles`.
    """
    def setUp(self):
        self.job_state = mock.create_autospec(JobState)
        self.job_state.events_for_task.return_value = []
        self.job_state.processed_tasks = []
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

    def run_task(self, initial_task=False):
        """
        Initiates the task run.

        :param initial_task: An optional flag which if ``True`` means that the
            task should be ran as if it were directly passed to the
            :func:`distro_tracker.core.tasks.run_task` function.
        :type initial_task: Boolean
        """
        if initial_task:
            self.job_state.events_for_task.return_value = []
        else:
            # If it is not the initial task, add a dummy task to make it look
            # like that.
            self.job_state.processed_tasks = ['sometask']

        self.task.execute()

    @mock.patch('distro_tracker.extract_source_files.tracker_tasks.AptCache.retrieve_source')
    @temporary_media_dir
    def test_create_extracted_files(self, mock_cache):
        """
        Tests that the task creates an
        :class:`distro_tracker.core.models.ExtractedSourceFile` instance.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')
        self.add_mock_event('new-source-package-version', {
            'pk': package.pk,
        })

        with make_temp_directory('dtracker-pkg-dir') as pkg_directory:
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

            self.run_task()

            # Check that the file was created.
            self.assertEqual(1, ExtractedSourceFile.objects.count())
            # Check that it has the correct name
            extracted_file = ExtractedSourceFile.objects.all()[0]
            self.assertEqual('changelog', extracted_file.name)

    @mock.patch('distro_tracker.extract_source_files.tracker_tasks.AptCache.retrieve_source')
    @temporary_media_dir
    def test_create_extracted_files_only_wanted_files(self, mock_cache):
        """
        Tests that the task creates an
        :class:`distro_tracker.core.models.ExtractedSourceFile` instance.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')
        self.add_mock_event('new-source-package-version', {
            'pk': package.pk,
        })

        with make_temp_directory('dtracker-pkg-dir') as pkg_directory:
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

            self.run_task()

            # Check that only the wanted files are created!
            self.assertEqual(len(wanted_files), ExtractedSourceFile.objects.count())
            extracted_names = [
                extracted_file.name
                for extracted_file in ExtractedSourceFile.objects.all()
            ]
            for wanted_file in wanted_files:
                self.assertIn(wanted_file, extracted_names)

    @mock.patch('distro_tracker.extract_source_files.tracker_tasks.AptCache.retrieve_source')
    @temporary_media_dir
    def test_task_is_initial_no_existing_files(self, mock_cache):
        """
        Tests the task when it is run as the initial task, but there are no
        extracted files for existing packages.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')

        with make_temp_directory('dtracker-pkg-dir') as pkg_directory:
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

            self.run_task(initial_task=True)

            # Check that all the wanted files are created!
            self.assertEqual(len(wanted_files), ExtractedSourceFile.objects.count())
            extracted_names = [
                extracted_file.name
                for extracted_file in ExtractedSourceFile.objects.all()
            ]
            for wanted_file in wanted_files:
                self.assertIn(wanted_file, extracted_names)


    @mock.patch('distro_tracker.extract_source_files.tracker_tasks.AptCache.retrieve_source')
    @temporary_media_dir
    def test_task_is_initial_existing_files(self, mock_cache):
        """
        Tests the task when it is run as the initial task, but some files for
        the package have already been previously extracted.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')

        with make_temp_directory('dtracker-pkg-dir') as pkg_directory:
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

            # Make a previously extracted file.
            original_content = 'Original content'
            ExtractedSourceFile.objects.create(
                source_package=package,
                name='changelog',
                extracted_file=ContentFile(original_content, name='changelog'))

            self.run_task(initial_task=True)

            # Check that all the wanted files exist.
            self.assertEqual(len(wanted_files), ExtractedSourceFile.objects.count())
            # Check that the existing file was not changed.
            extracted_file = ExtractedSourceFile.objects.get(
                name='changelog',
                source_package=package)
            extracted_file.extracted_file.open()
            content = extracted_file.extracted_file.read()
            extracted_file.extracted_file.close()
            self.assertEqual(original_content, content)

    @mock.patch('distro_tracker.extract_source_files.tracker_tasks.AptCache.retrieve_source')
    @temporary_media_dir
    def test_task_is_initial_existing_file_remove(self, mock_cache):
        """
        Tests the task when it is run as the initial task, but some of the
        already extracted source files should no longer be extracted.
        """
        name = SourcePackageName.objects.create(name='dummy-package')
        package = SourcePackage.objects.create(
            source_package_name=name, version='1.0.0')

        with make_temp_directory('dtracker-pkg-dir') as pkg_directory:
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

            # Make a previously extracted file.
            original_content = 'Original content'
            ExtractedSourceFile.objects.create(
                source_package=package,
                name='we-dont-want-this-any-more',
                extracted_file=ContentFile(original_content, name='changelog'))

            self.run_task(initial_task=True)

            # Check that all the wanted files exist.
            self.assertEqual(len(wanted_files), ExtractedSourceFile.objects.count())
            # Check that only the wanted files exist.
            extracted_names = [
                extracted_file.name
                for extracted_file in ExtractedSourceFile.objects.all()
            ]
            for wanted_file in wanted_files:
                self.assertIn(wanted_file, extracted_names)
