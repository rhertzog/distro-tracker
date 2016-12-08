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
Tests for the :mod:`distro_tracker.stdver_warnings` app.
"""

from __future__ import unicode_literals
from distro_tracker.test import TestCase
from django.utils.six.moves import mock
from distro_tracker.stdver_warnings.tracker_tasks \
    import UpdateStandardsVersionWarnings
from distro_tracker.core.tasks import Event, Job, JobState
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import SourcePackage
from distro_tracker.core.models import ActionItem, ActionItemType


class StandardsVersionActionItemTests(TestCase):
    """
    Tests for the
    :class:`distro_tracker.stdver_warnings.tracker_tasks.UpdateStandardsVersionWarnings`
    task.
    """
    def setUp(self):
        self.package_name = \
            SourcePackageName.objects.create(name='dummy-package')
        self.package = SourcePackage.objects.create(
            source_package_name=self.package_name, version='1.0.0')

        self.default_policy_version = '3.9.4.0'
        self.debian_policy_name = SourcePackageName.objects.create(
            name='debian-policy')
        self.debian_policy = SourcePackage.objects.create(
            source_package_name=self.debian_policy_name,
            version=self.default_policy_version)

        self.job_state = mock.create_autospec(JobState)
        self.job_state.events_for_task.return_value = []
        self.job = mock.create_autospec(Job)
        self.job.job_state = self.job_state
        self.task = UpdateStandardsVersionWarnings()
        self.task.job = self.job

    def add_mock_event(self, name, arguments):
        """
        Helper method adding mock events which the news generation task will
        see when it runs.
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
            self.job_state.processed_tasks = []
        else:
            # If it is not the initial task, add a dummy task to make it look
            # like that.
            self.job_state.processed_tasks = ['sometask']

        self.task.execute()

    def set_debian_policy_version(self, policy_version):
        """
        Set the version of the debian-policy package to the given version.
        """
        self.debian_policy.version = policy_version
        self.debian_policy.standards_version = policy_version.rsplit('.', 1)[0]
        self.debian_policy.save()

    def get_action_type(self):
        """
        Returns the :class:`distro_tracker.core.models.ActionItemType` for
        Standards-Version warnings.
        """
        return ActionItemType.objects.get_or_create(
            type_name=UpdateStandardsVersionWarnings.ACTION_ITEM_TYPE)[0]

    def add_mock_new_source_version_event(self, package):
        """
        Helper method adding mock 'new-source-package-version' events where
        the newly created source package should be the one given in the
        ``package`` parameter.
        """
        self.add_mock_event('new-source-package-version', {
            'pk': package.pk,
        })

    def test_action_item_outdated_policy(self):
        """
        Tests that an action item is created when the package's standards
        version is outdated.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        # Set the std-ver below the policy version
        self.package.standards_version = '3.9.3'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())
        self.add_mock_new_source_version_event(self.package)

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Correct type?
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            item.item_type.type_name,
            self.get_action_type().type_name)
        # Contains the correct package standards version in extra data
        self.assertEqual(
            self.package.standards_version,
            item.extra_data['standards_version'])
        self.assertFalse(item.extra_data['severely_outdated'])
        # This is a wishlist severity issue
        self.assertEqual('wishlist', item.get_severity_display())

    def test_action_item_severely_outdated_policy(self):
        """
        Tests that an action item is created when the package's standards
        version is severely outdated (major version number differs from the
        major version number of debian-policy).
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        # Set the std-ver below the policy version
        self.package.standards_version = '2.9.3'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())
        self.add_mock_new_source_version_event(self.package)

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Contains the correct package standards version in extra data
        item = ActionItem.objects.all()[0]
        self.assertTrue(item.extra_data['severely_outdated'])
        # This is a high severity issue
        self.assertEqual('high', item.get_severity_display())

    def test_no_action_item_policy_up_to_date(self):
        """
        Tests that no action item is created when the package's
        Standards-Version is up to date.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        # Set the std-ver to be equal to the policy version.
        self.package.standards_version = '3.9.4'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())
        self.add_mock_new_source_version_event(self.package)

        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_policy_outdated_full_version(self):
        """
        Tests that an action item is created when the package's standards
        version is outdated and set by giving all 4 version numbers.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        # Set the std-ver below the policy version
        self.package.standards_version = '3.9.3.1'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())
        self.add_mock_new_source_version_event(self.package)

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]
        self.assertEqual(
            item.item_type.type_name,
            self.get_action_type().type_name)

    def test_no_action_item_policy_up_to_date_full_version(self):
        """
        Tests that no action item is created when the package's
        Standards-Version is up to date and set by giving all 4 version
        numbers.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        # Set the std-ver to be equal to the policy version.
        self.package.standards_version = policy_version
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())
        self.add_mock_new_source_version_event(self.package)

        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_removed(self):
        """
        Tests that an existing action item is removed when there is a new
        package version with a non-outdated Std-Ver.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        action_type = self.get_action_type()
        ActionItem.objects.create(
            package=self.package_name,
            item_type=action_type,
            short_description="Desc")
        self.package.standards_version = '3.9.3'
        self.package.save()
        # Create a new package with a higher Std-Ver
        new_package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='4.0.0',
            standards_version='3.9.4.0')
        self.add_mock_new_source_version_event(new_package)

        self.run_task()

        # The action item has been removed.
        self.assertEqual(0, self.package_name.action_items.count())

    def test_action_item_updated(self):
        """
        Tests that an existing action item is updated when there is a new
        package version which still has an outdated Std-Ver.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        action_type = self.get_action_type()
        ActionItem.objects.create(
            package=self.package_name,
            item_type=action_type,
            short_description="Desc")
        self.package.standards_version = '3.9.2'
        self.package.save()
        # Create a new package with a higher Std-Ver
        new_package = SourcePackage.objects.create(
            source_package_name=self.package_name,
            version='4.0.0',
            standards_version='3.9.3.0')
        self.add_mock_new_source_version_event(new_package)

        self.run_task()

        # Still only one action item
        self.assertEqual(1, self.package_name.action_items.count())
        # The standards version in the extra data has been updated
        item = self.package_name.action_items.all()[0]
        self.assertEqual('3.9.3', item.extra_data['standards_version'])

    def test_task_directly_called(self):
        """
        Tests that when the task is directly called, the Standards-Version of
        all packages is checked.
        """
        policy_version = '3.9.4.0'
        self.set_debian_policy_version(policy_version)
        self.package.standards_version = '3.9.3'
        self.package.save()
        # Create another package with an outdated standards version
        outdated_package_name = \
            SourcePackageName.objects.create(name='outdated')
        SourcePackage.objects.create(
            source_package_name=outdated_package_name,
            version='4.0.0',
            standards_version='3.9.1.0')
        # Create a package with an up to date standards version
        up_to_date_package_name = \
            SourcePackageName.objects.create(name='uptodate')
        SourcePackage.objects.create(
            source_package_name=up_to_date_package_name,
            version='4.0.0',
            standards_version='3.9.4')
        # No events received by the task in this case.
        # Sanity check: No action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task(initial_task=True)

        # An action item is created for the two packages with out dated std-ver.
        self.assertEqual(2, ActionItem.objects.count())
        self.assertEqual(1, outdated_package_name.action_items.count())
        self.assertEqual(1, self.package_name.action_items.count())
