# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from pts import vendor
from pts.core.models import PseudoPackageName, PackageName
from pts.core.models import Repository
from pts.core.models import SourcePackageRepositoryEntry
from pts.core.models import ContributorEmail
from pts.core.models import SourcePackageMaintainer
from pts.core.models import SourcePackageUploader
from pts.core.models import SourcePackage
from pts.core.models import PackageExtractedInfo
from pts.core.models import BinaryPackageName
from pts.core.tasks import BaseTask
from pts.core.tasks import clear_all_events_on_exception
from pts.core.models import SourcePackageName, Architecture
from django.utils.six import reraise
from django import db
from django.db import transaction
from django.db import models
from django.conf import settings

from debian import deb822
import os
import apt
import sys
import shutil
import apt_pkg
import requests


class InvalidRepositoryException(Exception):
    pass


def update_pseudo_package_list():
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
    A function which accesses a Release file for the given repository and
    returns a dict representing the parsed information.
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


class AptCache(object):

    class AcquireProgress(apt.progress.base.AcquireProgress):
        def __init__(self, *args, **kwargs):
            super(AptCache.AcquireProgress, self).__init__(*args, **kwargs)
            self.fetched = []
            self.hit = []

        def done(self, item):
            self.fetched.append(os.path.split(item.owner.destfile)[1])

        def ims_hit(self, item):
            self.hit.append(os.path.split(item.owner.destfile)[1])

        def pulse(self, owner):
            return True

    def __init__(self):
        # The root cache directory is a subdirectory in the PTS_CACHE_DIRECTORY
        self.cache_root_dir = os.path.join(
            settings.PTS_CACHE_DIRECTORY,
            'apt-cache'
        )
        # Create the cache directory if it didn't already exist
        self._create_cache_directory()

        self.sources_list_path = os.path.join(
            self.cache_root_dir,
            'sources.list')
        self.conf_file_path = os.path.join(self.cache_root_dir, 'apt.conf')

        self.sources = []
        self.packages = []

    def _create_cache_directory(self):
        if not os.path.exists(self.cache_root_dir):
            os.makedirs(self.cache_root_dir)

    def clear_cache(self):
        shutil.rmtree(self.cache_root_dir)
        self._create_cache_directory()

    def update_sources_list(self):
        with open(self.sources_list_path, 'w') as sources_list:
            for repository in Repository.objects.all():
                sources_list.write(repository.sources_list_entry + '\n')

    def update_apt_conf(self):
        with open(self.conf_file_path, 'w') as conf_file:
            conf_file.write('APT::Architectures { ')
            for architecture in Architecture.objects.all():
                conf_file.write('"{arch}"; '.format(arch=architecture))
            conf_file.write('};\n')

    def _configure_apt(self):
        apt_pkg.init_config()
        apt_pkg.init_system()
        apt_pkg.read_config_file(apt_pkg.config, self.conf_file_path)
        apt_pkg.config.set('Dir::Etc', self.cache_root_dir)

    def _index_file_full_path(self, file_name):
        return os.path.join(
            self.cache_root_dir,
            'var/lib/apt/lists',
            file_name
        )

    def _match_index_file_to_repository(self, sources_file):
        sources_list = apt_pkg.SourceList()
        sources_list.read_main_list()
        component_url = None
        for entry in sources_list.list:
            for index_file in entry.index_files:
                if sources_file in index_file.describe:
                    split_description = index_file.describe.split()
                    component_url = split_description[0] + split_description[1]
                    break
        for repository in Repository.objects.all():
            if component_url in repository.component_urls:
                return repository

    def update_repositories(self, force_download=False):
        if force_download:
            self.clear_cache()

        self.update_sources_list()
        self.update_apt_conf()

        self._configure_apt()

        cache = apt.cache.Cache(rootdir=self.cache_root_dir)
        progress = AptCache.AcquireProgress()
        cache.update(progress)

        updated_sources = []
        updated_packages = []
        for fetched_file in progress.fetched:
            if fetched_file.endswith('Sources'):
                dest = updated_sources
            elif fetched_file.endswith('Packages'):
                dest = updated_packages
            else:
                continue
            repository = self._match_index_file_to_repository(fetched_file)
            dest.append((
                repository, self._index_file_full_path(fetched_file)
            ))

        return updated_sources, updated_packages


class PackageUpdateTask(BaseTask):
    """
    A subclass of the BaseTask providing some methods specific to tasks dealing
    with package updates.
    """
    def __init__(self, force_update=False, *args, **kwargs):
        super(PackageUpdateTask, self).__init__(*args, **kwargs)
        self.force_update = force_update

    def set_parameters(self, parameters):
        if 'force_update' in parameters:
            self.force_update = parameters['force_update']


from pts.core.utils.packages import extract_information_from_sources_entry
class UpdateRepositoriesTask(PackageUpdateTask):

    PRODUCES_EVENTS = (
        'new-source-package',
        'new-source-package-version',
        'new-source-package-in-repository',
        'new-source-package-version-in-repository',

        'new-binary-package',

        # The source package does not have a new version, but something has
        # changed.
        'updated-source-package-in-repository',

        # Source package no longer found in any repository
        'lost-source-package',
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

    def _update_sources_file(self, repository, sources_file):
        for stanza in deb822.Sources.iter_paragraphs(file(sources_file)):
            db.reset_queries()
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
                })

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
                maintainer = SourcePackageMaintainer.objects.create(
                    contributor_email=maintainer_email,
                    name=entry['maintainer'].get('name', ''))
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
                    uploaders.append(SourcePackageUploader.objects.get_or_create(
                        contributor_email=contributor_email,
                        source_package=src_pkg,
                        defaults={
                            'name': name,
                        })[0])

                entry['uploaders'] = uploaders

            # Update the source package information based on the newly
            # extracted data.
            src_pkg.update(**entry)
            src_pkg.save()
            # Add it to the repository
            kwargs = {
                key: value
                for key, value in entry.items()
                if key in ('priority', 'section')
            }
            if not repository.has_source_package(src_pkg):
                # Does it have any version of the package?
                if not repository.has_source_package_name(src_pkg.name):
                    self.raise_event('new-source-package-in-repository', {
                        'name': src_pkg.name,
                        'repository': repository.name,
                    })

                event = 'new-source-package-version-in-repository'
                entry = repository.add_source_package(src_pkg, **kwargs)
            else:
                event = 'updated-source-package-in-repository'
                entry = repository.update_source_package(src_pkg, **kwargs)
            self.raise_event(event, {
                'name': src_pkg.name,
                'version': src_pkg.version,
                'repository': repository.name,
            })

            self._add_processed_repository_entry(entry)

    def _remove_query_set_if_count_zero(self, qs, count_field, event_generator=None):
        """
        Removes elements from the given query set if their count of the given
        count_field is 0.
        If provided, uses the event_generator callback to generate an event
        for each of the removed instances.
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
        repository_entries_qs.delete()

        self._clear_processed_repository_entries()

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
                for sources_file in sources_files:
                    self._update_sources_file(repository, sources_file)
                # When all the files for the repository are handled, update
                # which packages are still found in it.
                self._update_repository_entries(repository)
            # When all repositories are handled, update which packages are
            # still found in at least one repository.
            self._remove_obsolete_packages()


class UpdatePackageGeneralInformation(PackageUpdateTask):
    DEPENDS_ON_EVENTS = (
        'updated-source-package-in-repository',
        'new-source-package-version-in-repository',
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
        with transaction.commit_on_success():
            for event in self.get_all_events():
                package_name = event.arguments['name']
                package = SourcePackageName.objects.get(name=package_name)
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
    DEPENDS_ON_EVENTS = (
        'new-source-package-version-in-repository',
        'lost-version-of-source-package',
        'updated-source-package-in-repository',
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
                'dsc_file_url': entry.dsc_file_url,
            })
        versions = {
            'version_list': version_list,
            'default_pool_url': package_name.main_entry.directory_url,
        }

        return versions

    @clear_all_events_on_exception
    def execute(self):
        with transaction.commit_on_success():
            for event in self.get_all_events():
                package_name = event.arguments['name']
                package = SourcePackageName.objects.get(name=package_name)

                versions, _ = PackageExtractedInfo.objects.get_or_create(
                    key='versions',
                    package=package)
                versions.value = self._extract_versions_for_package(package)
                versions.save()


class UpdateSourceToBinariesInformation(PackageUpdateTask):
    DEPENDS_ON_EVENTS = (
        'new-source-package-version-in-repository',
        'updated-source-package-in-repository',
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
        return [
            {
                'name': pkg.name,
            }
            for pkg in package.main_version.binary_packages.all()
        ]

    @clear_all_events_on_exception
    def execute(self):
        with transaction.commit_on_success():
            for event in self.get_all_events():
                package_name = event.arguments['name']
                package = SourcePackageName.objects.get(name=package_name)

                binaries, _ = PackageExtractedInfo.objects.get_or_create(
                    key='binaries',
                    package=package)
                binaries.value = self._get_all_binaries(package)
                binaries.save()
