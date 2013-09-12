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
from pts.core.models import BinaryPackageRepositoryEntry
from pts.core.models import ContributorEmail
from pts.core.models import ContributorName
from pts.core.models import SourcePackage
from pts.core.models import News
from pts.core.models import PackageExtractedInfo
from pts.core.models import BinaryPackageName
from pts.core.models import BinaryPackage
from pts.core.models import ExtractedSourceFile
from pts.core.models import SourcePackageDeps
from pts.core.utils import get_or_none
from pts.core.utils.http import get_resource_content
from pts.core.utils.packages import extract_information_from_sources_entry
from pts.core.utils.packages import extract_information_from_packages_entry
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
import re
import os
import sys
import requests
import itertools


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

    def _extract_information_from_packages_entry(self, bin_pkg, stanza):
        entry = extract_information_from_packages_entry(stanza)

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

    def get_source_for_binary(self, stanza):
        """
        :param stanza: a ``Packages`` file entry
        :returns: A ``(source_name, source_version)`` pair for the binary
            package described by the entry
        """
        source_name = (
            stanza['source']
            if 'source' in stanza else
            stanza['package'])
        # Extract the source version, if given in the Source field
        match = re.match(r'(.+) \((.+)\)', source_name)
        if match:
            source_name, source_version = match.group(1), match.group(2)
        else:
            source_version = stanza['version']

        return source_name, source_version

    def _update_packages_file(self, repository, packages_file):
        for stanza in deb822.Packages.iter_paragraphs(file(packages_file)):
            bin_pkg_name, created = BinaryPackageName.objects.get_or_create(
                name=stanza['package']
            )
            # Find the matching SourcePackage for the binary package
            source_name, source_version = self.get_source_for_binary(stanza)
            src_pkg, _ = SourcePackage.objects.get_or_create(
                source_package_name=SourcePackageName.objects.get_or_create(
                    name=source_name)[0],
                version=source_version)

            bin_pkg, created_new_version = BinaryPackage.objects.get_or_create(
                binary_package_name=bin_pkg_name,
                version=stanza['version'],
                source_package=src_pkg
            )
            if created_new_version:
                # Since it's a new version, extract package data from Packages
                entry = self._extract_information_from_packages_entry(
                    bin_pkg, stanza)
                # Update the binary package information based on the newly
                # extracted data.
                bin_pkg.update(**entry)
                bin_pkg.save()

            if not repository.has_binary_package(bin_pkg):
                # Add it to the repository
                architecture, _ = Architecture.objects.get_or_create(
                    name=stanza['architecture'])
                kwargs = {
                    'priority': stanza.get('priority', ''),
                    'section': stanza.get('section', ''),
                    'architecture': architecture,
                }
                entry = repository.add_binary_package(bin_pkg, **kwargs)
            else:
                # We get the entry to mark that the package version is still in
                # the repository.
                entry = BinaryPackageRepositoryEntry.objects.get(
                    repository=repository,
                    binary_package=bin_pkg)

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

    def _update_repository_entries(self, all_entries_qs, event_generator=None):
        """
        Removes all repository entries which are no longer found in the
        repository after the last update.
        If the ``event_generator`` argument is provided, an event returned by
        the function is raised for each removed entry.

        :param all_entries_qs: All currently existing entries which should be
            filtered to only contain the ones still found after the update.
        :type all_entries_qs: :class:`QuerySet <django.db.models.query.QuerySet>`
        :event_generator: Takes a repository entry as a parameter and returns a
            two-tuple of ``(event_name, event_arguments)``. An event with the
            return parameters is raised by the function for each removed entry.
        :type event_generator: callable
        """
        # Out of all entries in this repository, only those found in
        # the last update need to stay, so exclude them from the delete
        all_entries_qs = all_entries_qs.exclude(
            id__in=self._all_repository_entries)
        # Emit events for all packages that were removed from the repository
        if event_generator:
            for entry in all_entries_qs:
                self.raise_event(*event_generator(entry))
        all_entries_qs.delete()

        self._clear_processed_repository_entries()

    def extract_package_versions(self, file_name):
        """
        :param file_name: The name of the file from which package versions
            should be extracted.
        :type file_name: string
        :returns: A dict mapping package names to a list of versions found in
            Deb822 formatted file.
        """
        with open(file_name, 'r') as packages_file:
            packages = {}
            for stanza in deb822.Deb822.iter_paragraphs(packages_file):
                package_name, version = stanza['package'], stanza['version']
                packages.setdefault(package_name, [])
                packages[package_name].append(version)

            return packages

    def _mark_file_not_processed(self, repository, file_name, entry_manager):
        """
        The given ``Sources`` or ``Packages`` file has not been changed in the
        last update. This method marks all package versions found in it as
        still existing in order to avoid deleting them.

        :param repository: The repository to which the file is associated
        :type repository: :class:`Repository <pts.core.models.Repository>`
        :param file_name: The name of the file whose packages should be saved
        :param entry_manager: The manager instance which handles the package
            entries.
        :type entry_manager: :class:`Manager <django.db.models.Manager>`
        """
        # Extract all package versions from the file
        packages = self.extract_package_versions(file_name)

        # Only issue one DB query to retrieve the entries for packages with
        # the given names
        repository_entries = entry_manager.filter_by_package_name(packages.keys())
        repository_entries = repository_entries.filter(
            repository=repository)
        repository_entries = repository_entries.select_related()
        # For each of those entries, make sure to keep only the ones
        # corresponding to the version found in the sources file
        for entry in repository_entries:
            if entry.version in packages[entry.source_package.name]:
                self._add_processed_repository_entry(entry)

    def group_files_by_repository(self, cached_files):
        """
        :param cached_files: A list of ``(repository, file_name)`` pairs
        :returns: A dict mapping repositories to all file names found for that
            repository.
        """
        repository_files = {}
        for repository, file_name in cached_files:
            repository_files.setdefault(repository, [])
            repository_files[repository].append(file_name)

        return repository_files

    def update_sources_files(self, updated_sources):
        """
        Performs an update of tracked packages based on the updated Sources
        files.

        :param updated_sources: A list of ``(repository, sources_file_name)``
            pairs giving the Sources files which were updated and should be
            used to update the PTS tracked information too.
        """
        # Group all files by repository to which they belong
        repository_files = self.group_files_by_repository(updated_sources)

        with transaction.commit_on_success():
            for repository, sources_files in repository_files.items():
                # First update package information based on updated files
                for sources_file in sources_files:
                    self._update_sources_file(repository, sources_file)

                # Mark package versions found in un-updated files as still existing
                all_sources = self.apt_cache.get_sources_files_for_repository(repository)
                for sources_file in all_sources:
                    if sources_file not in sources_files:
                        self._mark_file_not_processed(
                            repository,
                            sources_file,
                            SourcePackageRepositoryEntry.objects)

                # When all the files for the repository are handled, update
                # which packages are still found in it.
                self._update_repository_entries(
                    SourcePackageRepositoryEntry.objects.filter(
                        repository=repository),
                    lambda entry: (
                        'lost-source-package-version-in-repository', {
                            'name': entry.source_package.name,
                            'version': entry.source_package.version,
                            'repository': entry.repository.name,
                        })
                )

            # When all repositories are handled, update which packages are
            # still found in at least one repository.
            self._remove_obsolete_packages()

    def update_packages_files(self, updated_packages):
        """
        Performs an update of tracked packages based on the updated Packages
        files.

        :param updated_sources: A list of ``(repository, packages_file_name)``
            pairs giving the Packages files which were updated and should be
            used to update the PTS tracked information too.
        """
        # Group all files by repository to which they belong
        repository_files = self.group_files_by_repository(updated_packages)

        for repository, packages_files in repository_files.items():
            # First update package information based on updated files
            for packages_file in packages_files:
                self._update_packages_file(repository, packages_file)

            # Mark package versions found in un-updated files as still existing
            all_sources = self.apt_cache.get_packages_files_for_repository(repository)
            for packages_file in all_sources:
                if packages_file not in packages_files:
                    self._mark_file_not_processed(
                        repository, packages_file)

            # When all the files for the repository are handled, update
            # which packages are still found in it.
            self._update_repository_entries(
                BinaryPackageRepositoryEntry.objects.filter(
                    repository=repository))

    def _update_dependencies_for_source(self,
                                        stanza,
                                        dependency_types):
        """
        Updates the dependencies for a source package based on the ones found
        in the given ``Packages`` or ``Sources`` stanza.

        :param source_name: The name of the source package for which the
            dependencies are updated.
        :param stanza: The ``Packages`` or ``Sources`` entry
        :param dependency_type: A list of dependency types which should be
            considered (e.g. Build-Depends, Recommends, etc.)
        :param source_to_binary_deps: The dictionary which should be updated
            with the new dependencies. Maps source names to a list of dicts
            each describing a dependency.
        """
        binary_dependencies = []
        for dependency_type in dependency_types:
            # The Deb822 instance is case sensitive when it comes to relations
            dependencies = stanza.relations.get(dependency_type.lower(), ())

            for dependency in itertools.chain(*dependencies):
                binary_name = dependency['name']
                binary_dependencies.append({
                    'dependency_type': dependency_type,
                    'binary': binary_name,
                })

        return binary_dependencies

    def update_dependencies(self):
        """
        Updates source-to-source package dependencies stemming from
        build bependencies and their binary packages' dependencies.
        """
        # Build the dependency mapping
        try:
            default_repository = Repository.objects.get(default=True)
        except Repository.DoesNotExist:
            return

        sources_files = self.apt_cache.get_sources_files_for_repository(
            default_repository)
        packages_files = self.apt_cache.get_packages_files_for_repository(
            default_repository)

        bin_to_src = {}
        source_to_binary_deps = {}

        # First builds a list of binary dependencies of all source packages
        # based on the Sources file.
        source_dependency_types = ('Build-Depends', 'Build-Depends-Indep')
        for sources_file in sources_files:
            for stanza in deb822.Sources.iter_paragraphs(file(sources_file)):
                source_name = stanza['package']

                for binary in itertools.chain(*stanza.relations['binary']):
                    sources_set = bin_to_src.setdefault(binary['name'], set())
                    sources_set.add(source_name)

                dependencies = source_to_binary_deps.setdefault(source_name, [])
                dependencies.extend(self._update_dependencies_for_source(
                    stanza,
                    source_dependency_types))

        # Then a list of binary dependencies based on the Packages file.
        binary_dependency_types = (
            'Depends',
            'Recommends',
            'Suggests',
        )
        for packages_file in packages_files:
            for stanza in deb822.Packages.iter_paragraphs(file(packages_file)):
                binary_name = stanza['package']
                source_name, source_version = self.get_source_for_binary(stanza)

                sources_set = bin_to_src.setdefault(binary_name, set())
                sources_set.add(source_name)

                new_dependencies = self._update_dependencies_for_source(
                    stanza,
                    binary_dependency_types)
                for dependency in new_dependencies:
                    dependency['source_binary'] = binary_name
                dependencies = source_to_binary_deps.setdefault(source_name, [])
                dependencies.extend(new_dependencies)

        # The binary packages are matched with their source packages and each
        # source to source dependency created.
        all_sources = {
            source.name: source
            for source in SourcePackageName.objects.all()
        }
        # Keeps a list of SourcePackageDeps instances which are to be bulk
        # created in the end.
        dependency_instances = []

        for source_name, dependencies in source_to_binary_deps.items():
            if source_name not in all_sources:
                continue

            # All dependencies for the current source package.
            all_dependencies = {}
            for dependency in dependencies:
                binary_name = dependency['binary']
                dependency_type = dependency.pop('dependency_type')
                if binary_name not in bin_to_src:
                    continue

                for source_dependency in bin_to_src[binary_name]:
                    if source_name == source_dependency:
                        continue

                    source_dependencies = all_dependencies.setdefault(source_dependency, {})
                    source_dependencies.setdefault(dependency_type, [])
                    if dependency not in source_dependencies[dependency_type]:
                        source_dependencies[dependency_type].append(dependency)

            # Create the dependency instances for the current source package.
            for dependency_name, details in all_dependencies.items():
                if dependency_name in all_sources:
                    build_dep = any(dependency_type in details for dependency_type in source_dependency_types)
                    binary_dep = any(dependency_type in details for dependency_type in binary_dependency_types)
                    dependency_instances.append(
                        SourcePackageDeps(
                            source=all_sources[source_name],
                            dependency=all_sources[dependency_name],
                            build_dep=build_dep,
                            binary_dep=binary_dep,
                            repository=default_repository,
                            details=details))

        # Create all the model instances in one transaction
        SourcePackageDeps.objects.all().delete()
        SourcePackageDeps.objects.bulk_create(dependency_instances)

    @clear_all_events_on_exception
    def execute(self):
        self.apt_cache = AptCache()
        updated_sources, updated_packages = (
            self.apt_cache.update_repositories(self.force_update)
        )

        self.update_sources_files(updated_sources)
        self.update_packages_files(updated_packages)
        self.update_dependencies()


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
                qs = SourcePackageName.objects.all()
            else:
                qs = SourcePackageName.objects.filter(name__in=package_names)
            for package in qs:
                binaries, _ = PackageExtractedInfo.objects.get_or_create(
                    key='binaries',
                    package=package)
                binaries.value = self._get_all_binaries(package)
                binaries.save()
