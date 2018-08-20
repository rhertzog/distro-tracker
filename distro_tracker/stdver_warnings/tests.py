# -*- coding: utf-8 -*-

# Copyright 2013-2018 The Distro Tracker Developers
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

from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
)
from distro_tracker.stdver_warnings.tracker_tasks import (
    UpdateStandardsVersionWarnings
)
from distro_tracker.test import TestCase


class StandardsVersionActionItemTests(TestCase):
    """
    Tests for the
    :class:`distro_tracker.stdver_warnings.tracker_tasks.UpdateStandardsVersionWarnings`
    task.
    """
    def setUp(self):
        self.package = self.create_source_package(
            name='dummy-package', version='1.0.0', repository='default')
        self.debian_policy = self.create_source_package(
            name='debian-policy', version='3.9.4.0')
        self.debian_policy.standards_version = '3.9.4.0'
        self.debian_policy.save()
        self.task = UpdateStandardsVersionWarnings()

    def create_action_item(self):
        action_type = self.get_action_type()
        return ActionItem.objects.create(
            package=self.package.source_package_name,
            item_type=action_type,
            short_description="Desc")

    def run_task(self):
        """
        Initiates the task run.
        """
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

    def test_action_item_outdated_policy(self):
        """
        Tests that an action item is created when the package's standards
        version is outdated.
        """
        # Set the std-ver below the policy version
        self.package.standards_version = '3.9.3'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

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
        # Set the std-ver below the policy version
        self.package.standards_version = '2.9.3'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Action item created.
        self.assertEqual(1, ActionItem.objects.count())
        # Contains the correct package standards version in extra data
        item = ActionItem.objects.all()[0]
        self.assertTrue(item.extra_data['severely_outdated'])
        # This is a high severity issue
        self.assertEqual('high', item.get_severity_display())

    def test_action_item_two_entries_same_package_with_outdated_policy(self):
        """
        Tests that the task copes with the presence of the same package
        twice.
        """
        # Package with a severe issue (version 1.0.0)
        self.package.standards_version = '2.9.3'
        self.package.save()
        # Same package with higher version but non-severe issue
        self.package2 = self.create_source_package(
            name='dummy-package', version='0.5', repository='default')
        self.package2.standards_version = '3.9.3'
        self.package2.save()

        self.run_task()

        self.assertEqual(1, ActionItem.objects.count())
        item = ActionItem.objects.all()[0]

        # The data matches the biggest version
        self.assertTrue(item.extra_data['severely_outdated'])

    def test_no_action_item_policy_up_to_date(self):
        """
        Tests that no action item is created when the package's
        Standards-Version is up to date.
        """
        # Set the std-ver to be equal to the policy version.
        self.package.standards_version = '3.9.4'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_policy_outdated_full_version(self):
        """
        Tests that an action item is created when the package's standards
        version is outdated and set by giving all 4 version numbers.
        """
        # Set the std-ver below the policy version
        self.package.standards_version = '3.9.3.1'
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

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
        # Set the std-ver to be equal to the policy version.
        self.package.standards_version = self.debian_policy.version
        self.package.save()
        # Sanity check: no action item
        self.assertEqual(0, ActionItem.objects.count())

        self.run_task()

        # Still no action items.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_removed_with_update(self):
        """
        Tests that an existing action item is removed when there is a new
        package version with a non-outdated Std-Ver.
        """
        self.create_action_item()
        self.package.standards_version = '3.9.3'
        self.package.repository_entries.all().delete()
        self.package.save()

        # Create a new package with a higher Std-Ver
        new_package = self.create_source_package(
            name=self.package.source_package_name.name,
            version='4.0.0', repository='default'
        )
        new_package.standards_version = '3.9.4.0'
        new_package.save()

        self.run_task()

        # The action item has been removed.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_removed_with_removal_from_default_repository(self):
        """
        Tests that an existing action item is removed when the
        package is gone from the default repository.
        """
        self.create_action_item()
        self.package.standards_version = '3.9.3'
        self.package.save()
        self.remove_from_repository(self.package, 'default')
        self.add_to_repository(self.package, 'foobar')

        self.run_task()

        # The action item has been removed.
        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_updated(self):
        """
        Tests that an existing action item is updated when there is a new
        package version which still has an outdated Std-Ver.
        """
        action_type = self.get_action_type()
        ActionItem.objects.create(
            package=self.package.source_package_name,
            item_type=action_type,
            short_description="Desc")
        self.package.repository_entries.all().delete()
        self.package.standards_version = '3.9.2'
        self.package.save()

        # Create a new package with a higher Std-Ver
        new_package = self.create_source_package(
            name=self.package.source_package_name.name,
            version='4.0.0', repository='default'
        )
        new_package.standards_version = '3.9.3.0'
        new_package.save()

        self.run_task()

        # Still only one action item
        self.assertEqual(1,
                         self.package.source_package_name.action_items.count())
        # The standards version in the extra data has been updated
        item = self.package.source_package_name.action_items.all()[0]
        self.assertEqual('3.9.3.0', item.extra_data['standards_version'])

    def test_task_run_with_force_update(self):
        """
        Tests that when the task is run with force_update, the Standards-Version
        of all packages is checked.
        """
        self.package.standards_version = '3.9.3'
        self.package.save()
        # Create another package with an outdated standards version
        outdated = self.create_source_package(name='outdated',
                                              repository='default')
        outdated.standards_version = '3.9.1.0'
        outdated.save()
        # Create a package with an up to date standards version
        uptodate = self.create_source_package(name='uptodate',
                                              repository='default')
        uptodate.standards_version = '3.9.4'
        uptodate.save()

        # Mark as already processed
        for item in self.task.items_to_process():
            self.task.item_mark_processed(item)

        # Sanity check: No action items in the beginning
        self.assertEqual(0, ActionItem.objects.count())

        self.task.initialize(force_update=True)
        self.run_task()

        # An action item is created for the two packages with out dated std-ver.
        self.assertEqual(2, ActionItem.objects.count())
        self.assertEqual(1, outdated.source_package_name.action_items.count())
        self.assertEqual(
            1, self.package.source_package_name.action_items.count())
