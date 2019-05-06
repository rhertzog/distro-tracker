# Copyright 2013-2019 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
The Distro-Tracker-specific tasks for :mod:`distro_tracker.debci_status` app.
"""

import json
import os.path

from django.conf import settings
from django.db import transaction

from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
    PackageData,
    SourcePackageName
)

from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.schedulers import IntervalScheduler

from distro_tracker.core.utils.http import HttpCache


class UpdateDebciStatusTask(BaseTask):
    """
    Updates packages' debci status.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ACTION_ITEM_TYPE_NAME = 'debci-failed-tests'
    ITEM_DESCRIPTION = (
        'Debci reports <a href="{debci_url}">failed tests</a> '
        '(<a href="{log_url}">log</a>)'
    )
    ITEM_FULL_DESCRIPTION_TEMPLATE = 'debci_status/debci-action-item.html'

    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.debci_action_item_type = ActionItemType.objects.create_or_update(
            type_name=self.ACTION_ITEM_TYPE_NAME,
            full_description_template=self.ITEM_FULL_DESCRIPTION_TEMPLATE)

    @property
    def base_url(self):
        return getattr(settings, 'DISTRO_TRACKER_DEBCI_URL')

    def get_debci_status(self):
        repo = getattr(settings, 'DISTRO_TRACKER_DEVEL_REPOSITORIES')[0]
        url = self.base_url + '/data/status/' + repo + '/amd64/packages.json'
        cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
        response, updated = cache.update(url, force=self.force_update)
        response.raise_for_status()
        if not updated:
            return
        debci_status = json.loads(response.text)
        return debci_status

    def __get_debci_dir(self, package_name):
        if package_name[:3] == 'lib':
            debci_dir = package_name[:4]
        else:
            debci_dir = package_name[:1]

        return os.path.join(debci_dir, package_name)

    def __get_debci_url_main(self, package_name):
        return os.path.join(self.base_url, 'packages',
                            self.__get_debci_dir(package_name))

    def __get_debci_url_logfile(self, package_name):
        return os.path.join(self.base_url, 'data/packages/unstable/amd64',
                            self.__get_debci_dir(package_name),
                            'latest-autopkgtest/log.gz')

    def update_action_item(self, package, debci_status):
        """
        Updates the :class:`ActionItem` for the given package based on the
        :class:`DebciStatus <distro_tracker.vendor.debian.models.DebciStatus`
        If the package has test failures an :class:`ActionItem` is created.
        """
        debci_action_item = package.get_action_item_for_type(
            self.debci_action_item_type.type_name)
        if debci_status.get('status') in ('pass', 'neutral'):
            if debci_action_item:
                debci_action_item.delete()
            return

        if debci_action_item is None:
            debci_action_item = ActionItem(
                package=package,
                item_type=self.debci_action_item_type,
                severity=ActionItem.SEVERITY_HIGH)

        package_name = debci_status.get('package')

        url = self.__get_debci_url_main(package_name)
        log = self.__get_debci_url_logfile(package_name)

        debci_action_item.short_description = self.ITEM_DESCRIPTION.format(
            debci_url=url,
            log_url=log)

        debci_action_item.extra_data = {
            'duration': debci_status.get('duration_human'),
            'previous_status': debci_status.get('previous_status'),
            'status': debci_status.get('status'),
            'date': debci_status.get('date'),
            'base_url': self.base_url,
            'url': url,
            'log': log,
        }

        debci_action_item.save()

    def execute_main(self):
        all_debci_status = self.get_debci_status()
        if all_debci_status is None:
            return

        with transaction.atomic():
            # Delete obsolete data
            PackageData.objects.filter(key='debci').delete()
            packages = []
            infos = []
            for result in all_debci_status:
                try:
                    package = SourcePackageName.objects.get(
                        name=result['package'])
                    packages.append(package)
                except SourcePackageName.DoesNotExist:
                    continue

                url = self.__get_debci_url_main(result['package'])
                infos.append(
                    PackageData(
                        package=package,
                        key='debci',
                        value={'result': result,
                               'url': url}
                    )
                )

                self.update_action_item(package, result)

            PackageData.objects.bulk_create(infos)
            ActionItem.objects.delete_obsolete_items(
                [self.debci_action_item_type], packages)
