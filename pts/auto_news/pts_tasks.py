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
The PTS-specific tasks for :mod:`pts.auto_news` app.
"""
from __future__ import unicode_literals
from pts.core.tasks import BaseTask
from pts.core.utils.http import get_resource_content
from pts.core.models import SourcePackageName
from pts.core.models import Repository
from pts.core.models import News


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

        :type package: :class:`SourcePackageName <pts.core.models.SourcePackageName>`
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
            content = content + '\nChanges:\n' + changelog_content

        return content

    def execute(self):
        package_changes = {}
        new_source_versions = {}
        for event in self.get_all_events():
            if event.name == 'source-files-extracted':
                continue

            package_name, version = event.arguments['name'], event.arguments['version']
            package_changes.setdefault(package_name, [])
            package_changes[package_name].append(event)

            new_source_versions.setdefault(package_name, [])
            if event.name == 'new-source-package-version':
                new_source_versions[package_name].append(version)

        # Retrieve all relevant packages from the db
        packages = SourcePackageName.objects.filter(name__in=package_changes.keys())

        for package in packages:
            package_name = package.name
            events = package_changes[package_name]

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
                package_removed_processed = False
                for event in events:
                    # First time seeing this version?
                    version = event.arguments['version']
                    new_source_version = version in new_source_versions[package_name]
                    title, content = None, None
                    if event.name == 'new-source-package-version-in-repository':
                        if new_source_version:
                            title = "Accepted {pkg} version {ver} to {repo}"
                            content = self.generate_accepted_news_content(
                                package, version)
                        else:
                            title = "{pkg} version {ver} MIGRATED to {repo}"
                    elif event.name == 'lost-source-package-version-in-repository':
                        # Check if the repository still has some version of the
                        # source package. If not, a news item needs to be added
                        if package_removed_processed:
                            # Create only one package removed item per
                            # repository, package pair
                            continue
                        package_removed_processed = True
                        repository = Repository.objects.get(name=repository_name)
                        if not repository.has_source_package_name(package.name):
                            title = "{pkg} REMOVED from {repo}"

                    if title is not None:
                        News.objects.create(
                            package=package,
                            title=title.format(
                                pkg=package_name,
                                repo=event.arguments['repository'],
                                ver=version
                            ),
                            _db_content=content
                        )
