# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Implements core data retrieval from various external resources."""
from __future__ import unicode_literals
from pts import vendor
from pts.core.models import PseudoPackageName, PackageName
from pts.core.models import Repository
from pts.core.models import SourcePackageRepositoryEntry
from pts.core.models import ContributorEmail
from pts.core.models import ContributorName
from pts.core.models import SourcePackage
from pts.core.models import News
from pts.core.models import PackageExtractedInfo
from pts.core.models import BinaryPackageName
from pts.core.models import ExtractedSourceFile
from pts.core.utils import get_or_none
from pts.core.utils.http import get_resource_content
from pts.core.utils.packages import AptCache
from pts.core.tasks import BaseTask
from pts.core.tasks import clear_all_events_on_exception
from pts.core.models import SourcePackageName, Architecture
from django.utils.six import reraise
from django import db
from django.db import transaction
from django.db import models
from django.conf import settings
from django.core.files import File

from debian import deb822
import os
import sys
import requests


class InvalidRepositoryException(Exception):
    pass


def update_pseudo_package_list():
    """
    Retrieves the list of all allowed pseudo packages and updates the stored
    list if necessary.

    Uses a vendor-provided function
    :func:`get_pseudo_package_list <pts.vendor.skeleton.rules.get_pseudo_package_list>`
    to get the list of currently available pseudo packages.
    """
    try:
        pseudo_packages, implemented = vendor.call('get_pseudo_package_list')
    except:
        # Error accessing pseudo package resource: do not update the list
        return

    if not implemented or pseudo_packages is None:
        return

    # Faster lookups than if this were a list
    pseudo_packages = set(pseudo_packages)
    for existing_package in PseudoPackageName.objects.all():
        if existing_package.name not in pseudo_packages:
            # Existing packages which are no longer considered pseudo packages are
            # demoted to a subscription-only package.
            existing_package.package_type = PackageName.SUBSCRIPTION_ONLY_PACKAGE_TYPE
            existing_package.save()
        else:
            # If an existing package remained a pseudo package there will be no
            # action required so it is removed from the set.
            pseudo_packages.remove(existing_package.name)

    # The left over packages in the set are the ones that do not exist.
    for package_name in pseudo_packages:
        PseudoPackageName.objects.create(name=package_name)


def retrieve_repository_info(sources_list_entry):
    """
    A function which accesses a ``Release`` file for the given repository and
    returns a dict representing the parsed information.

    :rtype: dict
    """
    entry_split = sources_list_entry.split(None, 3)
    if len(entry_split) < 3:
        raise InvalidRepositoryException("Invalid sources.list entry")

    repository_type, url, distribution = entry_split[:3]

    # Access the Release file
    try:
        response = requests.get(Repository.release_file_url(url, distribution))
    except requests.exceptions.RequestException as original:
        reraise(
            InvalidRepositoryException,
            InvalidRepositoryException(
                "Could not connect to {url}\n{original}".format(
                    url=url,
                    original=original)
            ),
            sys.exc_info()[2]
        )
    if response.status_code != 200:
        raise InvalidRepositoryException(
            "No Release file found at the URL: {url}\n"
            "Response status code {status_code}".format(
                url=url, status_code=response.status_code))

    # Parse the retrieved information
    release = deb822.Release(response.text)
    if not release:
        raise InvalidRepositoryException(
            "No data could be extracted from the Release file at {url}".format(
                url=url))
    REQUIRED_KEYS = (
        'architectures',
        'components',
    )
    # A mapping of optional keys to their default values, if any
    OPTIONAL_KEYS = {
        'suite': distribution,
        'codename': None,
    }
    # Make sure all necessary keys were found in the file
    for key in REQUIRED_KEYS:
        if key not in release:
            raise InvalidRepositoryException(
                "Property {key} not found in the Release file at {url}".format(
                    key=key,
                    url=url))
    # Finally build the return dictionary with the information about the
    # repository.
    repository_information = {
        'uri': url,
        'architectures': release['architectures'].split(),
        'components': release['components'].split(),
        'binary': repository_type == 'deb',
        'source': repository_type == 'deb-src',
    }
    # Add in optional info
    for key, default in OPTIONAL_KEYS.items():
        repository_information[key] = release.get(key, default)

    return repository_information


class PackageUpdateTask(BaseTask):
    """
    A subclass of the :class:`BaseTask <pts.core.tasks.BaseTask>` providing
    some methods specific to tasks dealing with package updates.
    """
    def __init__(self, force_update=False, *args, **kwargs):
        super(PackageUpdateTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']


from pts.core.utils.packages import extract_information_from_sources_entry
class UpdateRepositoriesTask(PackageUpdateTask):
    """
    Performs an update of repository information.

    New (source and binary) packages are created if necessary and old ones are
    deleted. An event is emitted for each situation, allowing other tasks to
    perform updates based on updated package information.
    """
    PRODUCES_EVENTS = (
        'new-source-package',
        'new-source-package-version',
        'new-source-package-in-repository',
        'new-source-package-version-in-repository',

        'new-binary-package',

        # Source package no longer found in any repository
        'lost-source-package',
        # Source package version no longer found in the given repository
        'lost-source-package-version-in-repository',
        # A particular version of a source package no longer found in any repo
        'lost-version-of-source-package',
        # Binary package name no longer used by any source package
        'lost-binary-package',
    )

    def __init__(self, *args, **kwargs):
        super(UpdateRepositoriesTask, self).__init__(*args, **kwargs)
        self._all_packages = []
        self._all_repository_entries = []

    def _clear_processed_repository_entries(self):
        self._all_repository_entries = []

    def _add_processed_repository_entry(self, repository_entry):
        self._all_repository_entries.append(repository_entry.id)

    def _extract_information_from_sources_entry(self, src_pkg, stanza):
        entry = extract_information_from_sources_entry(stanza)

        # Convert the parsed data into corresponding model instances
        if 'architectures' in entry:
            # Map the list of architecture names to their objects
            # Discards any unknown architectures.
            entry['architectures'] = Architecture.objects.filter(
                name__in=entry['architectures'])

        if 'binary_packages' in entry:
            # Map the list of binary package names to list of existing
            # binary package names.
            binary_package_names = entry['binary_packages']
            existing_binaries_qs = BinaryPackageName.objects.filter(
                name__in=binary_package_names)
            existing_binaries_names = []
            binaries = []
            for binary in existing_binaries_qs:
                binaries.append(binary)
                existing_binaries_names.append(binary.name)
            for binary_name in binary_package_names:
                if binary_name not in existing_binaries_names:
                    binaries.append(BinaryPackageName.objects.create(
                        name=binary_name))
                    self.raise_event('new-binary-package', {
                        'name': binary_name,
                    })
            entry['binary_packages'] = binaries

        if 'maintainer' in entry:
            maintainer_email, _ = ContributorEmail.objects.get_or_create(
                email=entry['maintainer']['email'])
            maintainer = ContributorName.objects.get_or_create(
                contributor_email=maintainer_email,
                name=entry['maintainer'].get('name', ''))[0]
            entry['maintainer'] = maintainer

        if 'uploaders' in entry:
            uploader_emails = [
                uploader['email']
                for uploader in entry['uploaders']
            ]
            uploader_names = [
                uploader.get('name', '')
                for uploader in entry['uploaders']
            ]
            existing_contributor_emails_qs = ContributorEmail.objects.filter(
                email__in=uploader_emails)
            existing_contributor_emails = {
                contributor.email: contributor
                for contributor in existing_contributor_emails_qs
            }
            uploaders = []
            for email, name in zip(uploader_emails, uploader_names):
                if email not in existing_contributor_emails:
                    contributor_email = ContributorEmail.objects.create(
                        email=email)
                else:
                    contributor_email = existing_contributor_emails[email]
                uploaders.append(ContributorName.objects.get_or_create(
                    contributor_email=contributor_email,
                    name=name)[0]
                )

            entry['uploaders'] = uploaders

        return entry

    def _update_sources_file(self, repository, sources_file):
        for stanza in deb822.Sources.iter_paragraphs(file(sources_file)):
            allow, implemented = vendor.call('allow_package', stanza)
            if allow is not None and implemented and not allow:
                # The vendor-provided function indicates that the package
                # should not be included
                continue

            src_pkg_name, created = SourcePackageName.objects.get_or_create(
                name=stanza['package']
            )
            if created:
                self.raise_event('new-source-package', {
                    'name': src_pkg_name.name
                })

            src_pkg, created_new_version = SourcePackage.objects.get_or_create(
                source_package_name=src_pkg_name,
                version=stanza['version']
            )
            if created_new_version:
                self.raise_event('new-source-package-version', {
                    'name': src_pkg.name,
                    'version': src_pkg.version,
                    'pk': src_pkg.pk,
                })
                # Since it's a new version, extract package data from Sources
                entry = self._extract_information_from_sources_entry(
                    src_pkg, stanza)
                # Update the source package information based on the newly
                # extracted data.
                src_pkg.update(**entry)
                src_pkg.save()

            if not repository.has_source_package(src_pkg):
                # Does it have any version of the package?
                if not repository.has_source_package_name(src_pkg.name):
                    self.raise_event('new-source-package-in-repository', {
                        'name': src_pkg.name,
                        'repository': repository.name,
                    })

                # Add it to the repository
                kwargs = {
                    'priority': stanza.get('priority', ''),
                    'section': stanza.get('section', ''),
                }
                entry = repository.add_source_package(src_pkg, **kwargs)
                self.raise_event('new-source-package-version-in-repository', {
                    'name': src_pkg.name,
                    'version': src_pkg.version,
                    'repository': repository.name,
                })
            else:
                # We get the entry to mark that the package version is still in
                # the repository.
                entry = SourcePackageRepositoryEntry.objects.get(
                    repository=repository,
                    source_package=src_pkg
                )

            self._add_processed_repository_entry(entry)

    def _remove_query_set_if_count_zero(self, qs, count_field, event_generator=None):
        """
        Removes elements from the given query set if their count of the given
        ``count_field`` is ``0``.

        :param qs: Instances which should be deleted in case their count of the
            field ``count_field`` is 0.
        :type qs: :class:`QuerySet <django.db.models.query.QuerySet>`

        :param count_field: Each instance in ``qs`` that has a 0 count for the
            field with this name is deleted.
        :type count_field: string

        :param event_generator: A ``callable`` which returns a
            ``(name, arguments)`` pair describing the event which should be
            raised based on the model instance given to it as an argument.
        :type event_generator: ``callable``
        """
        qs = qs.annotate(count=models.Count(count_field))
        qs = qs.filter(count=0)
        if event_generator:
            for item in qs:
                self.raise_event(*event_generator(item))
        qs.delete()

    def _remove_obsolete_packages(self):
        # Clean up package versions which no longer exist in any repository.
        self._remove_query_set_if_count_zero(
            SourcePackage.objects.all(),
            'repository',
            lambda source_package: (
                'lost-version-of-source-package', {
                    'name': source_package.name,
                    'version': source_package.version,
                }
            )
        )
        # Clean up names which no longer exist.
        self._remove_query_set_if_count_zero(
            SourcePackageName.objects.all(),
            'source_package_versions',
            lambda package: (
                'lost-source-package', {
                    'name': package.name,
                }
            )
        )
        # Clean up binary package names which are no longer used by any source
        # package.
        self._remove_query_set_if_count_zero(
            BinaryPackageName.objects.all(),
            'sourcepackage',
            lambda binary_package_name: (
                'lost-binary-package', {
                    'name': binary_package_name.name,
                }
            )
        )

    def _update_repository_entries(self, repository):
        """
        Removes all repository entries which are no longer found in the given
        repository after the last update.
        """
        # Clean up repository versions which no longer exist.
        repository_entries_qs = (
            SourcePackageRepositoryEntry.objects.filter(
                repository=repository))
        # Out of all entries in this repository, only those found in
        # the last update need to stay, so exclude them from the delete
        repository_entries_qs = repository_entries_qs.exclude(
            id__in=self._all_repository_entries)
        # Emit events for all packages that were removed from the repository
        for entry in repository_entries_qs:
            source_package = entry.source_package
            self.raise_event('lost-source-package-version-in-repository', {
                'name': source_package.name,
                'version': source_package.version,
                'repository': entry.repository.name,
            })
        repository_entries_qs.delete()

        self._clear_processed_repository_entries()

    def _mark_sources_file_not_processed(self, repository, sources_file_name):
        """
        The ``Sources`` file with the given name, belonging to the given
        repository was not updated, so this method marks all package versions
        found in it as still existing to avoid deleting them.
        """
        # Extract all package versions from the sources file
        with open(sources_file_name, 'r') as sources_file:
            packages = {
                stanza['package']: stanza['version']
                for stanza in deb822.Sources.iter_paragraphs(sources_file)
            }

        # Only issue one DB query to retrieve the entries for packages with
        # the given names
        repository_entries = SourcePackageRepositoryEntry.objects.filter(
            repository=repository)
        repository_entries = repository_entries.filter(
            source_package__source_package_name__name__in=packages.keys())
        repository_entries = repository_entries.select_related()
        # For each of those entries, make sure to keep only the ones
        # corresponding to the version found in the sources file
        for entry in repository_entries:
            if entry.source_package.version == packages[entry.source_package.name]:
                self._add_processed_repository_entry(entry)

    @clear_all_events_on_exception
    def execute(self):
        apt_cache = AptCache()
        updated_sources, updated_packages = (
            apt_cache.update_repositories(self.force_update)
        )

        # Group all files by repository to which they belong
        repository_files = {}
        for repository, sources_file in updated_sources:
            repository_files.setdefault(repository, [])
            repository_files[repository].append(sources_file)

        with transaction.commit_on_success():
            for repository, sources_files in repository_files.items():
                # First update package information based on updated files
                for sources_file in sources_files:
                    self._update_sources_file(repository, sources_file)

                # Mark package versions found in un-updated files as still existing
                all_sources = apt_cache.get_sources_files_for_repository(repository)
                for sources_file in all_sources:
                    if sources_file not in sources_files:
                        self._mark_sources_file_not_processed(
                            repository, sources_file)

                # When all the files for the repository are handled, update
                # which packages are still found in it.
                self._update_repository_entries(repository)

            # When all repositories are handled, update which packages are
            # still found in at least one repository.
            self._remove_obsolete_packages()


class UpdatePackageGeneralInformation(PackageUpdateTask):
    """
    Updates the general information regarding packages.
    """
    DEPENDS_ON_EVENTS = (
        'new-source-package-version-in-repository',
        'lost-source-package-version-in-repository',
    )

    def __init__(self, *args, **kwargs):
        super(UpdatePackageGeneralInformation, self).__init__(*args, **kwargs)
        self.packages = set()

    def process_event(self, event):
        self.packages.add(event.arguments['name'])

    def _get_info_from_entry(self, entry):
        general_information = {
            'name': entry.source_package.name,
            'priority': entry.priority,
            'section': entry.section,
            'version': entry.source_package.version,
            'maintainer': entry.source_package.maintainer.to_dict(),
            'uploaders': [
                uploader.to_dict()
                for uploader in entry.source_package.uploaders.all()
            ],
            'architectures': map(str, entry.source_package.architectures.all()),
            'standards_version': entry.source_package.standards_version,
            'vcs': entry.source_package.vcs,
        }

        return general_information

    @clear_all_events_on_exception
    def execute(self):
        package_names = set(
            event.arguments['name']
            for event in self.get_all_events()
        )
        with transaction.commit_on_success():
            qs = SourcePackageName.objects.filter(name__in=package_names)
            for package in qs:
                entry = package.main_entry
                if entry is None:
                    continue

                general, _ = PackageExtractedInfo.objects.get_or_create(
                    key='general',
                    package=package
                )
                general.value = self._get_info_from_entry(entry)
                general.save()


class UpdateVersionInformation(PackageUpdateTask):
    """
    Updates extracted version information about packages.
    """
    DEPENDS_ON_EVENTS = (
        'new-source-package-version-in-repository',
        'lost-source-package-version-in-repository',
    )

    def __init__(self, *args, **kwargs):
        super(UpdateVersionInformation, self).__init__(*args, **kwargs)
        self.packages = set()

    def process_event(self, event):
        self.packages.add(event.arguments['name'])

    def _extract_versions_for_package(self, package_name):
        """
        Returns a list where each element is a dictionary with the following
        keys: repository_name, repository_shorthand, package_version.
        """
        version_list = []
        for repository in package_name.repositories:
            entry = repository.get_source_package_entry(package_name)
            version_list.append({
                'repository_name': entry.repository.name,
                'repository_shorthand': entry.repository.shorthand,
                'version': entry.source_package.version,
            })
        versions = {
            'version_list': version_list,
            'default_pool_url': package_name.main_entry.directory_url,
        }

        return versions

    @clear_all_events_on_exception
    def execute(self):
        package_names = set(
            event.arguments['name']
            for event in self.get_all_events()
        )
        with transaction.commit_on_success():
            qs = SourcePackageName.objects.filter(name__in=package_names)
            for package in qs:
                versions, _ = PackageExtractedInfo.objects.get_or_create(
                    key='versions',
                    package=package)
                versions.value = self._extract_versions_for_package(package)
                versions.save()


class UpdateSourceToBinariesInformation(PackageUpdateTask):
    """
    Updates extracted source-binary mapping for packages.
    These are the binary packages which appear in the binary panel on each
    source package's Web page.
    """
    DEPENDS_ON_EVENTS = (
        'new-source-package-version-in-repository',
        'lost-source-package-version-in-repository',
    )

    def __init__(self, *args, **kwargs):
        super(UpdateSourceToBinariesInformation, self).__init__(*args, **kwargs)
        self.packages = set()

    def process_event(self, event):
        self.packages.add(event.arguments['name'])

    def _get_all_binaries(self, package):
        """
        Returns a list representing binary packages linked to the given
        source package.
        """
        repository_name = package.main_entry.repository.name
        return [
            {
                'name': pkg.name,
                'repository_name': repository_name,
            }
            for pkg in package.main_version.binary_packages.all()
        ]

    @clear_all_events_on_exception
    def execute(self):
        package_names = set(
            event.arguments['name']
            for event in self.get_all_events()
        )
        with transaction.commit_on_success():
            if self.is_initial_task():
                qs = SourcePackageName.objects.all()[:1]
            else:
                qs = SourcePackageName.objects.filter(name__in=package_names)
            for package in qs:
                binaries, _ = PackageExtractedInfo.objects.get_or_create(
                    key='binaries',
                    package=package)
                binaries.value = self._get_all_binaries(package)
                binaries.save()


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
                event_names = [event.name for event in events]
                repository_has_new_version = (
                    'new-source-package-version-in-repository' in event_names)
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
                        if not repository_has_new_version:
                            # If there was no new version added to the repository instead of
                            # this one, add a removed event.
                            title = "{pkg} version {ver} REMOVED from {repo}"

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
