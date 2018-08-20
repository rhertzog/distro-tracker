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
Distro Tracker tasks for the :mod:`distro_tracker.stdver_warnings` app.
"""

from debian.debian_support import version_compare
from django.db import transaction
from django.db.models import Prefetch

from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
    SourcePackageName
)
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.mixins import (
    ProcessSrcRepoEntryInDefaultRepository
)
from distro_tracker.core.tasks.schedulers import IntervalScheduler
from distro_tracker.core.utils import get_or_none


class UpdateStandardsVersionWarnings(BaseTask,
                                     ProcessSrcRepoEntryInDefaultRepository):
    """
    The task updates warnings for packages which have an outdated
    Standards-Version.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE = 'debian-std-ver-outdated'
    FULL_DESCRIPTION_TEMPLATE = \
        'stdver_warnings/standards-version-action-item.html'
    ITEM_DESCRIPTION = "Standards version of the package is outdated."

    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.action_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE,
            full_description_template=self.FULL_DESCRIPTION_TEMPLATE)

    def items_extend_queryset(self, queryset):
        queryset = super().items_extend_queryset(queryset)
        base_qs = ActionItem.objects.filter(item_type=self.action_type)
        return queryset.prefetch_related(
            Prefetch('source_package__source_package_name__action_items',
                     queryset=base_qs, to_attr='stdver_action_items')
        )

    def get_policy_version(self):
        """
        :returns: The latest version of the ``debian-policy`` package.
        """
        debian_policy = get_or_none(SourcePackageName, name='debian-policy')
        if not debian_policy:
            return
        policy_version = debian_policy.main_version.version
        # Minor patch level should be disregarded for the comparison
        if policy_version.count('.') == 3:
            policy_version, _ = policy_version.rsplit('.', 1)

        return policy_version

    def check_if_full_update_is_required(self, policy_version):
        last_policy_version = self.data.get('policy_version')
        if last_policy_version != policy_version:
            # Force a full update when a new policy version is released
            self.force_update = True
            self.data['policy_version'] = policy_version
            self.data_mark_modified()

    @transaction.atomic
    def execute_main(self):
        # Get the current policy version
        policy_version = self.get_policy_version()
        if policy_version is None:
            # Nothing to do if there is no ``debian-policy``
            return

        self.check_if_full_update_is_required(policy_version)

        seen_packages = {}
        for entry in self.items_to_process():
            try:
                package = entry.source_package.source_package_name
                standards_version = entry.source_package.standards_version
                try:
                    if package.name in seen_packages:
                        seen_version = seen_packages[package.name]
                        version = entry.source_package.version
                        if version_compare(version, seen_version) < 0:
                            # This version is older, skip it
                            continue
                        # If already seen, then the cached action item
                        # is no longer reliable, retrieve it from the db
                        action_item = get_or_none(ActionItem, package=package,
                                                  item_type=self.action_type)
                    else:
                        action_item = package.stdver_action_items[0]
                except IndexError:
                    action_item = None
                seen_packages[package.name] = entry.source_package.version

                if standards_version.startswith(policy_version):
                    # The std-ver of the package is up to date.
                    # Remove any possibly existing action item.
                    if action_item is not None:
                        action_item.delete()
                    continue

                major_policy_version_number, _ = policy_version.split('.', 1)
                severely_outdated = not standards_version.startswith(
                    major_policy_version_number)

                if action_item is None:
                    action_item = ActionItem(
                        package=package,
                        item_type=self.action_type)

                if severely_outdated:
                    action_item.severity = ActionItem.SEVERITY_HIGH
                else:
                    action_item.severity = ActionItem.SEVERITY_WISHLIST

                action_item.short_description = self.ITEM_DESCRIPTION
                action_item.extra_data = {
                    'lastsv': policy_version,
                    'lastsv_dashes': policy_version.replace('.', '-'),
                    'standards_version': standards_version,
                    'standards_version_dashes':
                        standards_version.replace('.', '-'),
                    'severely_outdated': severely_outdated,
                }
                action_item.save()
            finally:
                self.item_mark_processed(entry)

        # Remove action items for packages that disappeared from the default
        # repository
        ActionItem.objects.delete_obsolete_items(
            [self.action_type],
            self.items_all().values_list(
                'source_package__source_package_name__name', flat=True)
        )
