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
PTS tasks for the :mod:`pts.stdver_warnings` app.
"""

from __future__ import unicode_literals
from pts.core.tasks import BaseTask
from pts.core.utils import get_or_none
from pts.core.models import SourcePackageName
from pts.core.models import ActionItem, ActionItemType


class UpdateStandardsVersionWarnings(BaseTask):
    """
    The task updates warnings for packages which have an outdated
    Standards-Version.
    """
    DEPENDS_ON_EVENTS = (
        'new-source-package-version',
    )

    ACTION_ITEM_TYPE = 'debian-std-ver-outdated'
    FULL_DESCRIPTION_TEMPLATE = 'stdver_warnings/standards-version-action-item.html'
    ITEM_DESCRIPTION = "Standards version of the package is outdated."

    def __init__(self, force_update=False, *args, **kwargs):
        super(UpdateStandardsVersionWarnings, self).__init__(*args, **kwargs)
        self.force_update = force_update
        self.action_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE,
            full_description_template=self.FULL_DESCRIPTION_TEMPLATE)

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']

    def get_packages_from_events(self):
        """
        :returns: A list of :class:`pts.core.models.SourcePackageName`
            instances which are found from all raised events.
        """
        package_pks = [
            event.arguments['pk']
            for event in self.get_all_events()
        ]
        qs = SourcePackageName.objects.filter(source_package_versions__pk__in=package_pks)
        qs.prefetch_related('action_items')

        return qs

    def get_policy_version(self):
        """
        :returns: The latest version of the ``debian-policy`` package.
        """
        debian_policy = get_or_none(SourcePackageName, name='debian-policy')
        if not debian_policy:
            return
        policy_version = debian_policy.main_version.version
        # Minor patch level should be disregarded for the comparison
        policy_version, _ = policy_version.rsplit('.', 1)

        return policy_version

    def create_action_item(self, package, policy_version):
        """
        Creates a :class:`pts.core.models.ActionItem` instance if the
        Standards-Version of the given package is outdated when compared to the
        given policy version.
        """
        if not package.main_version:
            return
        # Get the old action item entry
        action_item = package.get_action_item_for_type(self.ACTION_ITEM_TYPE)
        standards_version = package.main_version.standards_version
        if standards_version.startswith(policy_version):
            # The std-ver of the package is up to date.
            # Remove any possibly existing action item.
            if action_item is not None:
                action_item.delete()
            return

        major_policy_version_number, _ = policy_version.split('.', 1)
        severely_outdated = not standards_version.startswith(
            major_policy_version_number)

        if action_item is None:
            action_item = ActionItem(
                package=package,
                item_type=self.action_type)

        # Remove the minor patch level from the package's Std-Ver, if it has it
        if standards_version.count('.') == 3:
            standards_version, _ = standards_version.rsplit('.', 1)

        action_item.short_description = self.ITEM_DESCRIPTION
        action_item.extra_data = {
            'lastsv': policy_version,
            'standards_version': standards_version,
            'severely_outdated': severely_outdated,
        }
        action_item.save()

    def execute(self):
        # Get the current policy version
        policy_version = self.get_policy_version()
        if policy_version is None:
            # Nothing to do if there is no ``debian-policy``
            return

        if self.is_initial_task():
            # If the task is directly ran, update all packages
            packages = SourcePackageName.objects.all()
            packages.fetch_related('action_items')
        else:
            # If the task is ran as part of a job, get the packages from raised
            # events
            packages = self.get_packages_from_events()

        for package in packages:
            self.create_action_item(package, policy_version)
