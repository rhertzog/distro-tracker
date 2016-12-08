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
from __future__ import unicode_literals
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.utils.http import get_resource_content
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import Repository
from distro_tracker.core.models import News


class GenerateNewsFromRepositoryUpdates(BaseTask):
    DEPENDS_ON_EVENTS = (
        'new-source-package-version',
        'new-source-package-version-in-repository',
        'lost-source-package-version-in-repository',
        # Run after all source files have been retrieved
        'source-files-extracted',
    )

    def generate_accepted_news_content(self, package, version):
        """
        Generates the content for a news item created when a package version is
        first created.

        :type package: :class:`SourcePackageName
            <distro_tracker.core.models.SourcePackageName>`
        :type version: :class:`string`
        """
        package_version = package.source_package_versions.get(version=version)
        entry = package_version.repository_entries.all()[0]

        # Add dsc file
        content = get_resource_content(entry.dsc_file_url)
        if content:
            content = content.decode('utf-8')
        else:
            content = ''

        # Add changelog entries since last update...
        changelog_content = package_version.get_changelog_entry()
        if changelog_content:
            content = content + '\n<span id="changes">Changes:</span>\n'
            content = content + changelog_content

        return content

    def _process_package_event(self, package, event, repository,
                               new_source_version):
        version = event.arguments['version']
        title, content = None, None
        # Don't process event if the repository is hidden
        if repository.get_flags()['hidden']:
            return
        if event.name == 'new-source-package-version-in-repository':
            if new_source_version:
                title = "{pkg} {ver} has been added to {repo}"
                content = self.generate_accepted_news_content(
                    package, version)
            else:
                title = "{pkg} {ver} migrated to {repo}"
        elif event.name == 'lost-source-package-version-in-repository':
            # Check if the repository still has some version of the
            # source package. If not, a news item needs to be added
            if self._package_removed_processed:
                # Create only one package removed item per
                # repository, package pair
                return
            self._package_removed_processed = True
            if not repository.has_source_package_name(package.name):
                title = "{pkg} has been removed from {repo}"

        if title is not None:
            News.objects.create(
                package=package,
                title=title.format(
                    pkg=package.name,
                    repo=event.arguments['repository'],
                    ver=version
                ),
                _db_content=content
            )

    def _process_package_events(self, package, events, new_source_versions):
        # Group all the events for this package by repository
        repository_events = {}
        for event in events:
            if event.name == 'new-source-package-version':
                continue
            repository = event.arguments['repository']
            repository_events.setdefault(repository, [])
            repository_events[repository].append(event)

        # Process each event for each repository.
        for repository_name, events in repository_events.items():
            self._package_removed_processed = False
            repository = Repository.objects.get(name=repository_name)
            for event in events:
                # First time seeing this version?
                new_source_version = \
                    event.arguments['version'] in \
                    new_source_versions[package.name]
                self._process_package_event(package, event, repository,
                                            new_source_version)

    def execute(self):
        package_changes = {}
        new_source_versions = {}
        for event in self.get_all_events():
            if event.name == 'source-files-extracted':
                continue

            package_name = event.arguments['name']
            version = event.arguments['version']
            package_changes.setdefault(package_name, [])
            package_changes[package_name].append(event)

            new_source_versions.setdefault(package_name, [])
            if event.name == 'new-source-package-version':
                new_source_versions[package_name].append(version)

        # Retrieve all relevant packages from the db
        packages = SourcePackageName.objects.filter(
            name__in=package_changes.keys())

        for package in packages:
            events = package_changes[package.name]
            self._process_package_events(package, events, new_source_versions)
