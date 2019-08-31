# Copyright 2013-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements core data retrieval from various external resources."""
import itertools
import logging
import re

from debian import deb822

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

import requests

from distro_tracker import vendor
from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import (
    Architecture,
    BinaryPackage,
    BinaryPackageName,
    BinaryPackageRepositoryEntry,
    ContributorName,
    PackageData,
    PackageName,
    PseudoPackageName,
    Repository,
    SourcePackage,
    SourcePackageDeps,
    SourcePackageName,
    SourcePackageRepositoryEntry,
    Team
)
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.mixins import (
    PackageTagging,
    ProcessMainRepoEntry,
    ProcessSrcRepoEntry,
    ProcessSrcRepoEntryInDefaultRepository,
)
from distro_tracker.core.tasks.schedulers import IntervalScheduler
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils.packages import (
    AptCache,
    extract_information_from_packages_entry,
    extract_information_from_sources_entry
)

logger = logging.getLogger('distro_tracker.tasks')
logger_input = logging.getLogger('distro_tracker.input')


class InvalidRepositoryException(Exception):
    pass


def update_pseudo_package_list():
    """
    Retrieves the list of all allowed pseudo packages and updates the stored
    list if necessary.

    Uses a vendor-provided function
    :func:`get_pseudo_package_list
    <distro_tracker.vendor.skeleton.rules.get_pseudo_package_list>`
    to get the list of currently available pseudo packages.
    """
    try:
        pseudo_packages, implemented = vendor.call('get_pseudo_package_list')
    except RuntimeError:
        # Error accessing pseudo package resource: do not update the list
        return

    if not implemented or pseudo_packages is None:
        return

    # Faster lookups than if this were a list
    pseudo_packages = set(pseudo_packages)
    for existing_package in PseudoPackageName.objects.all():
        if existing_package.name not in pseudo_packages:
            # Existing packages which are no longer considered pseudo packages
            # are demoted -- losing their pseudo package flag.
            existing_package.pseudo = False
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
    tls_verify = settings.DISTRO_TRACKER_CA_BUNDLE or True

    # Access the Release file
    try:
        response = requests.get(Repository.release_file_url(url, distribution),
                                verify=tls_verify,
                                allow_redirects=True)
    except requests.exceptions.RequestException as original:
        raise InvalidRepositoryException(
            "Could not connect to {url}".format(url=url)) from original
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


class TagPackagesWithBugs(BaseTask, PackageTagging):
    """
    Performs an update of 'bugs' tag for packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    TAG_NAME = 'tag:bugs'
    TAG_DISPLAY_NAME = 'bugs'
    TAG_COLOR_TYPE = 'warning'
    TAG_DESCRIPTION = 'The package has bugs'
    TAG_TABLE_TITLE = 'Packages with bugs'

    def packages_to_tag(self):
        return PackageName.objects.filter(bug_stats__stats__isnull=False)


class UpdateRepositoriesTask(BaseTask):
    """
    Performs an update of repository information.

    New (source and binary) packages are created if necessary and old ones are
    deleted. An event is emitted for each situation, allowing other tasks to
    perform updates based on updated package information.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    SOURCE_DEPENDENCY_TYPES = ('Build-Depends', 'Build-Depends-Indep')
    BINARY_DEPENDENCY_TYPES = ('Depends', 'Recommends', 'Suggests')

    def initialize(self, **kwargs):
        super().initialize(**kwargs)
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
                    binary_package_name, _ = PackageName.objects.get_or_create(
                        name=binary_name)
                    binary_package_name.binary = True
                    binary_package_name.save()
                    binary_package_name = BinaryPackageName.objects.get(
                        name=binary_name)
                    binaries.append(binary_package_name)
            entry['binary_packages'] = binaries

        if 'maintainer' in entry:
            try:
                maintainer_email, _ = UserEmail.objects.get_or_create(
                    email=entry['maintainer']['email'])
                maintainer = ContributorName.objects.get_or_create(
                    contributor_email=maintainer_email,
                    name=entry['maintainer'].get('name', ''))[0]
                entry['maintainer'] = maintainer
            except ValidationError:
                email = entry['maintainer']['email']
                logger_input.warning(
                    'Invalid email in maintainer field of %s: %s',
                    src_pkg, email)
                del entry['maintainer']

        if 'uploaders' in entry:
            self._process_uploaders(entry, src_pkg)

        return entry

    def _process_uploaders(self, entry, src_pkg):
        uploader_emails = [
            uploader['email']
            for uploader in entry['uploaders']
        ]
        uploader_names = [
            uploader.get('name', '')
            for uploader in entry['uploaders']
        ]
        existing_contributor_emails_qs = UserEmail.objects.filter(
            email__in=uploader_emails)
        existing_contributor_emails = {
            contributor.email: contributor
            for contributor in existing_contributor_emails_qs
        }
        uploaders = []
        for email, name in zip(uploader_emails, uploader_names):
            if email not in existing_contributor_emails:
                try:
                    contributor_email, _ = UserEmail.objects.get_or_create(
                        email=email)
                    existing_contributor_emails[email] = contributor_email
                except ValidationError:
                    contributor_email = None
                    logger_input.warning(
                        'Bad email in uploaders in %s for %s: %s',
                        src_pkg, name, email)
            else:
                contributor_email = existing_contributor_emails[email]
            if contributor_email:
                uploaders.append(ContributorName.objects.get_or_create(
                    contributor_email=contributor_email,
                    name=name)[0]
                )

        entry['uploaders'] = uploaders

    def _extract_information_from_packages_entry(self, bin_pkg, stanza):
        entry = extract_information_from_packages_entry(stanza)

        return entry

    def _update_sources_file(self, repository, component, sources_file):
        for stanza in deb822.Sources.iter_paragraphs(sources_file):
            allow, implemented = vendor.call('allow_package', stanza)
            if allow is not None and implemented and not allow:
                # The vendor-provided function indicates that the package
                # should not be included
                continue

            src_pkg_name, _ = SourcePackageName.objects.get_or_create(
                name=stanza['package']
            )

            src_pkg, created_new_version = SourcePackage.objects.get_or_create(
                source_package_name=src_pkg_name,
                version=stanza['version']
            )
            if created_new_version or self.force_update:
                # Extract package data from Sources
                entry = self._extract_information_from_sources_entry(
                    src_pkg, stanza)
                # Update the source package information based on the newly
                # extracted data.
                src_pkg.update(**entry)
                src_pkg.save()

            if not repository.has_source_package(src_pkg):
                # Add it to the repository
                entry = repository.add_source_package(
                    src_pkg, component=component)
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
        for stanza in deb822.Packages.iter_paragraphs(packages_file):
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

    def _remove_query_set_if_count_zero(self, qs, count_field):
        """
        Removes elements from the given query set if their count of the given
        ``count_field`` is ``0``.

        :param qs: Instances which should be deleted in case their count of the
            field ``count_field`` is 0.
        :type qs: :class:`QuerySet <django.db.models.query.QuerySet>`

        :param count_field: Each instance in ``qs`` that has a 0 count for the
            field with this name is deleted.
        :type count_field: string
        """
        qs = qs.annotate(count=models.Count(count_field))
        qs = qs.filter(count=0)
        qs.delete()

    def _remove_obsolete_packages(self):
        self.log("Removing obsolete source packages")
        # Clean up package versions which no longer exist in any repository.
        self._remove_query_set_if_count_zero(SourcePackage.objects.all(),
                                             'repository')
        # Clean up names which no longer exist.
        self._remove_query_set_if_count_zero(SourcePackageName.objects.all(),
                                             'source_package_versions')
        # Clean up binary package names which are no longer used by any source
        # package.
        self._remove_query_set_if_count_zero(BinaryPackageName.objects.all(),
                                             'sourcepackage')

    def _update_repository_entries(self, all_entries_qs):
        """
        Removes all repository entries which are no longer found in the
        repository after the last update.
        If the ``event_generator`` argument is provided, an event returned by
        the function is raised for each removed entry.

        :param all_entries_qs: All currently existing entries which should be
            filtered to only contain the ones still found after the update.
        :type all_entries_qs:
            :class:`QuerySet <django.db.models.query.QuerySet>`
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
        :type repository:
            :class:`Repository <distro_tracker.core.models.Repository>`
        :param file_name: The name of the file whose packages should be saved
        :param entry_manager: The manager instance which handles the package
            entries.
        :type entry_manager: :class:`Manager <django.db.models.Manager>`
        """
        # Extract all package versions from the file
        packages = self.extract_package_versions(file_name)

        # Only issue one DB query to retrieve the entries for packages with
        # the given names
        repository_entries = \
            entry_manager.filter_by_package_name(packages.keys())
        repository_entries = repository_entries.filter(
            repository=repository)
        repository_entries = repository_entries.select_related()
        # For each of those entries, make sure to keep only the ones
        # corresponding to the version found in the sources file
        for entry in repository_entries:
            if entry.version in packages[entry.name]:
                self._add_processed_repository_entry(entry)

    def group_files_by_repository(self, cached_files):
        """
        :param cached_files: A list of ``(repository, component, file_name)``
            pairs
        :returns: A Two-Tuple (repository_files, component).
            repository_files is a dict mapping repositories to all
            file names found for that repository. component is a string
            pointing to the component of the repository.
        """
        repository_files = {}

        for repository, component, file_name in cached_files:
            repository_files.setdefault(repository, [])
            repository_files[repository].append((file_name, component))

        return repository_files

    def sources_file_in_sources_files_data(
            self, sources_file, sources_files_data):
        """
        Performs a search for the sources file in the sources_files_data list.

        :param sources_file: The file to search for
        :param sources_files_data: list of (`sources_file`, `component`) to
            search the sources_file.
        :return: True or false depending on whether the sources_file was found
            in the sources_files_data list.
        """
        for sources_f, component in sources_files_data:
            if sources_f == sources_file:
                return True
        return False

    def update_sources_files(self, updated_sources):
        """
        Performs an update of tracked packages based on the updated Sources
        files.

        :param updated_sources: A list of ``(repository, component,
            sources_file_name)`` giving the Sources files which were updated and
            should be used to update the Distro Tracker tracked information too.
        """
        # Group all files by repository to which they belong
        repository_files = self.group_files_by_repository(updated_sources)

        for repository, sources_files_data in repository_files.items():
            self.extend_lock()
            with transaction.atomic():
                self.log("Processing Sources files of %s repository",
                         repository.shorthand)
                # First update package information based on updated files
                for sources_file, component in sources_files_data:
                    with open(sources_file) as sources_fd:
                        self._update_sources_file(
                            repository, component, sources_fd)

                # Mark package versions found in un-updated files as still
                # existing
                all_sources = \
                    self.apt_cache.get_sources_files_for_repository(repository)
                for sources_file in all_sources:
                    if not self.sources_file_in_sources_files_data(
                            sources_file, sources_files_data):
                        self._mark_file_not_processed(
                            repository,
                            sources_file,
                            SourcePackageRepositoryEntry.objects)

                # When all the files for the repository are handled, update
                # which packages are still found in it.
                self._update_repository_entries(
                    SourcePackageRepositoryEntry.objects.filter(
                        repository=repository)
                )

        with transaction.atomic():
            # When all repositories are handled, update which packages are
            # still found in at least one repository.
            self._remove_obsolete_packages()

    def update_packages_files(self, updated_packages):
        """
        Performs an update of tracked packages based on the updated Packages
        files.

        :param updated_packages: A list of ``(repository, packages_file_name)``
            pairs giving the Packages files which were updated and should be
            used to update the Distro Tracker tracked information too.
        """
        # Group all files by repository to which they belong
        repository_files = self.group_files_by_repository(updated_packages)

        for repository, packages_files_data in repository_files.items():
            # This operation is really slow, ensure we have one hour safety
            self.extend_lock(expire_delay=3600, delay=3600)
            with transaction.atomic():
                self.log("Processing Packages files of %s repository",
                         repository.shorthand)
                # First update package information based on updated files
                for packages_file, component in packages_files_data:
                    with open(packages_file) as packages_fd:
                        self._update_packages_file(repository, packages_fd)

                # Mark package versions found in un-updated files as still
                # existing
                all_sources = \
                    self.apt_cache.get_packages_files_for_repository(repository)
                for packages_file in all_sources:
                    if not self.sources_file_in_sources_files_data(
                            packages_file, packages_files_data):
                        self._mark_file_not_processed(
                            repository, packages_file,
                            BinaryPackageRepositoryEntry.objects)

                # When all the files for the repository are handled, update
                # which packages are still found in it.
                self._update_repository_entries(
                    BinaryPackageRepositoryEntry.objects.filter(
                        repository=repository))

    def _update_dependencies_for_source(self, stanza, dependency_types):
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

    def _process_source_to_binary_deps(self, source_to_binary_deps, all_sources,
                                       bin_to_src, default_repository):
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

                    source_dependencies = \
                        all_dependencies.setdefault(source_dependency, {})
                    source_dependencies.setdefault(dependency_type, [])
                    if dependency not in source_dependencies[dependency_type]:
                        source_dependencies[dependency_type].append(dependency)

            # Create the dependency instances for the current source package.
            for dependency_name, details in all_dependencies.items():
                if dependency_name in all_sources:
                    build_dep = any(dependency_type in details
                                    for dependency_type
                                    in self.SOURCE_DEPENDENCY_TYPES)
                    binary_dep = any(dependency_type in details
                                     for dependency_type
                                     in self.BINARY_DEPENDENCY_TYPES)
                    dependency_instances.append(
                        SourcePackageDeps(
                            source=all_sources[source_name],
                            dependency=all_sources[dependency_name],
                            build_dep=build_dep,
                            binary_dep=binary_dep,
                            repository=default_repository,
                            details=details))

        return dependency_instances

    def update_dependencies(self):
        """
        Updates source-to-source package dependencies stemming from
        build bependencies and their binary packages' dependencies.
        """
        self.extend_lock()

        # Build the dependency mapping
        try:
            default_repository = Repository.objects.get(default=True)
        except Repository.DoesNotExist:
            self.log("No default repository, no dependencies created.",
                     level=logging.WARNING)
            return

        self.log("Parsing files to discover dependencies")
        sources_files = self.apt_cache.get_sources_files_for_repository(
            default_repository)
        packages_files = self.apt_cache.get_packages_files_for_repository(
            default_repository)

        bin_to_src = {}
        source_to_binary_deps = {}

        # First builds a list of binary dependencies of all source packages
        # based on the Sources file.
        for sources_file in sources_files:
            with open(sources_file) as sources_fd:
                for stanza in deb822.Sources.iter_paragraphs(sources_fd):
                    source_name = stanza['package']

                    for binary in itertools.chain(*stanza.relations['binary']):
                        sources_set = bin_to_src.setdefault(binary['name'],
                                                            set())
                        sources_set.add(source_name)

                    dependencies = source_to_binary_deps.setdefault(source_name,
                                                                    [])
                    dependencies.extend(self._update_dependencies_for_source(
                        stanza,
                        self.SOURCE_DEPENDENCY_TYPES))

        # Then a list of binary dependencies based on the Packages file.
        for packages_file in packages_files:
            with open(packages_file) as packages_fd:
                for stanza in deb822.Packages.iter_paragraphs(packages_fd):
                    binary_name = stanza['package']
                    source_name, source_version = \
                        self.get_source_for_binary(stanza)

                    sources_set = bin_to_src.setdefault(binary_name, set())
                    sources_set.add(source_name)

                    new_dependencies = self._update_dependencies_for_source(
                        stanza,
                        self.BINARY_DEPENDENCY_TYPES)
                    for dependency in new_dependencies:
                        dependency['source_binary'] = binary_name
                    dependencies = source_to_binary_deps.setdefault(source_name,
                                                                    [])
                    dependencies.extend(new_dependencies)

        # The binary packages are matched with their source packages and each
        # source to source dependency created.
        all_sources = {
            source.name: source
            for source in SourcePackageName.objects.all()
        }

        self.log("Creating in-memory SourcePackageDeps")
        # Keeps a list of SourcePackageDeps instances which are to be bulk
        # created in the end.
        dependency_instances = \
            self._process_source_to_binary_deps(source_to_binary_deps,
                                                all_sources, bin_to_src,
                                                default_repository)

        # Create all the model instances in one transaction
        self.log("Committing SourcePackagesDeps to database")
        SourcePackageDeps.objects.all().delete()
        SourcePackageDeps.objects.bulk_create(dependency_instances)

    def execute_main(self):
        self.log("Updating apt's cache")
        self.apt_cache = AptCache()
        updated_sources, updated_packages = (
            self.apt_cache.update_repositories(self.force_update)
        )

        self.log("Updating data from Sources files")
        self.update_sources_files(updated_sources)
        self.log("Updating data from Packages files")
        self.update_packages_files(updated_packages)
        self.log("Updating dependencies")
        self.update_dependencies()


class UpdatePackageGeneralInformation(BaseTask, ProcessMainRepoEntry):
    """
    Updates the general information regarding packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    def _get_info_from_entry(self, entry):
        srcpkg = entry.source_package
        general_information = {
            'name': srcpkg.name,
            'component': entry.component,
            'version': entry.source_package.version,
            'maintainer': srcpkg.maintainer.to_dict(),
            'uploaders': [
                uploader.to_dict()
                for uploader in srcpkg.uploaders.all()
            ],
            'architectures': list(
                map(str, srcpkg.architectures.order_by('name'))),
            'standards_version': srcpkg.standards_version,
            'vcs': srcpkg.vcs,
        }

        return general_information

    @transaction.atomic
    def execute_main(self):
        for entry in self.items_to_process():
            general, _ = PackageData.objects.get_or_create(
                key='general',
                package=entry.source_package.source_package_name
            )
            general.value = self._get_info_from_entry(entry)
            general.save()
            self.item_mark_processed(entry)


class UpdateVersionInformation(BaseTask, ProcessSrcRepoEntry):
    """
    Updates extracted version information about packages.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    def _extract_versions_for_package(self, package_name):
        """
        Returns a list where each element is a dictionary with the following
        keys: repository_name, repository_shorthand, package_version.
        """
        version_list = []
        for repository in package_name.repositories:
            if repository.get_flags()['hidden']:
                continue
            entry = repository.get_source_package_entry(package_name)
            version_list.append({
                'repository': {
                    'name': entry.repository.name,
                    'shorthand': entry.repository.shorthand,
                    'codename': entry.repository.codename,
                    'suite': entry.repository.suite,
                    'id': entry.repository.id,
                },
                'version': entry.source_package.version,
            })
        default_pool_url = None
        if package_name.main_entry:
            default_pool_url = package_name.main_entry.directory_url
        versions = {
            'version_list': version_list,
            'default_pool_url': default_pool_url,
        }

        return versions

    def process_package(self, package):
        versions, _ = PackageData.objects.get_or_create(key='versions',
                                                        package=package)
        versions.value = self._extract_versions_for_package(package)
        versions.save()

    @transaction.atomic
    def execute_main(self):
        seen = {}
        for entry in self.items_to_process():
            name = entry.source_package.name
            if entry.repository.get_flags()['hidden'] or name in seen:
                self.item_mark_processed(entry)
                continue

            package = entry.source_package.source_package_name
            self.process_package(package)

            seen[name] = True
            self.item_mark_processed(entry)

        for key, data in self.items_to_cleanup():
            if data['name'] in seen:
                continue
            package = get_or_none(SourcePackageName, name=data['name'])
            if not package:
                continue

            self.process_package(package)
            seen[data['name']] = True


class UpdateSourceToBinariesInformation(BaseTask, ProcessMainRepoEntry):
    """
    Updates extracted source-binary mapping for packages.
    These are the binary packages which appear in the binary panel on each
    source package's Web page.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    def _get_all_binaries(self, entry):
        """
        Returns a list representing binary packages linked to the given
        repository entry.
        """
        repository = entry.repository
        return [
            {
                'name': pkg.name,
                'repository': {
                    'name': repository.name,
                    'shorthand': repository.shorthand,
                    'suite': repository.suite,
                    'codename': repository.codename,
                    'id': repository.id,
                },
            }
            for pkg in entry.source_package.binary_packages.all()
        ]

    @transaction.atomic
    def execute_main(self):
        for entry in self.items_to_process():
            package = entry.source_package.source_package_name
            binaries, _ = PackageData.objects.get_or_create(key='binaries',
                                                            package=package)
            binaries.value = self._get_all_binaries(entry)
            binaries.save()

            self.item_mark_processed(entry)


class UpdateTeamPackagesTask(BaseTask, ProcessSrcRepoEntryInDefaultRepository):
    """
    Based on new source packages detected during a repository update, the task
    updates teams to include new packages which are associated with its
    maintainer email.
    """

    class Scheduler(IntervalScheduler):
        interval = 3600 * 4

    def add_package_to_maintainer_teams(self, package, maintainer):
        """
        Adds the given package to all the teams where the given maintainer is
        set as the maintainer email.

        :param package: The package to add to the maintainers teams.
        :type package: :class:`SourcePackageName
            <distro_tracker.core.models.SourcePackageName>`
        :param maintainer: The maintainer to whose teams the package should be
            added.
        :type maintainer:
            :class:`ContributorName <distro_tracker.core.models.UserEmail>`
        """
        teams = Team.objects.filter(maintainer_email__email=maintainer.email)
        for team in teams:
            team.packages.add(package)
        if maintainer.email.endswith("@" + settings.DISTRO_TRACKER_FQDN):
            localpart, _ = maintainer.email.split('@', 1)
            if not localpart.startswith("team+"):
                return
            service, slug = localpart.split('+', 1)
            team = get_or_none(Team, slug=slug)
            if team:
                team.packages.add(package)

    @transaction.atomic
    def execute_main(self):
        for entry in self.items_to_process():
            # Add the package to the maintainer's teams packages
            package = entry.source_package.source_package_name
            maintainer = entry.source_package.maintainer
            self.add_package_to_maintainer_teams(package, maintainer)

            # Add the package to all the uploaders' teams packages
            for uploader in entry.source_package.uploaders.all():
                self.add_package_to_maintainer_teams(package, uploader)

            self.item_mark_processed(entry)
