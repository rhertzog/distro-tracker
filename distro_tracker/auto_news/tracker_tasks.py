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
The Distro-Tracker-specific tasks for :mod:`distro_tracker.auto_news` app.
"""
from distro_tracker.core.models import News, SourcePackageName
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.mixins import ProcessRepositoryUpdates
from distro_tracker.core.tasks.schedulers import IntervalScheduler
from distro_tracker.core.utils.http import get_resource_content


class GenerateNewsFromRepositoryUpdates(BaseTask, ProcessRepositoryUpdates):

    class Scheduler(IntervalScheduler):
        interval = 3600

    def generate_accepted_news_content(self, srcpkg):
        """
        Generates the content for a news item created when a package version is
        first created.

        :type srcpkg: :class:`~distro_tracker.core.models.SourcePackage`
        """
        entry = srcpkg.repository_entries.all()[0]

        # Add dsc file
        content = get_resource_content(entry.dsc_file_url)
        if content:
            content = content.decode('utf-8')
        else:
            content = ''

        # Add changelog entries since last update...
        changelog_content = srcpkg.get_changelog_entry()
        if changelog_content:
            content += '\n<span id="changes">Changes:</span>\n'
            content += changelog_content

        return content

    def add_accepted_news(self, entry):
        title = "{pkg} {ver} has been added to {repo}".format(
            pkg=entry.source_package.name,
            ver=entry.source_package.version,
            repo=entry.repository.name,
        )
        content = self.generate_accepted_news_content(entry.source_package)
        News.objects.create(
            package=entry.source_package.source_package_name,
            title=title,
            _db_content=content
        )

    def add_migrated_news(self, entry):
        title = "{pkg} {ver} migrated to {repo}".format(
            pkg=entry.source_package.name,
            ver=entry.source_package.version,
            repo=entry.repository.name,
        )
        News.objects.create(
            package=entry.source_package.source_package_name,
            title=title
        )

    def add_removed_news(self, package, repository):
        title = "{pkg} has been removed from {repo}".format(
            pkg=package,
            repo=repository.name,
        )
        pkgname = SourcePackageName.objects.get(name=package)
        pkgname.news_set.create(title=title)

    def execute_main(self):
        for entry in self.items_to_process():
            if entry.repository.get_flags()['hidden']:
                self.item_mark_processed(entry)
                continue
            if self.is_new_source_package(entry.source_package):
                self.add_accepted_news(entry)
            else:
                self.add_migrated_news(entry)
            self.item_mark_processed(entry)

        for package, repository in self.iter_removals_by_repository():
            if repository.get_flags()['hidden']:
                continue
            self.add_removed_news(package, repository)
