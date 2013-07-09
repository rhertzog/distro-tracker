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
from pts.core.models import PseudoPackage, Package
from pts.core.models import Repository
from pts.core.models import BinaryPackage
from pts.core.models import SourcePackage, Architecture
from django.utils.six import reraise
from django.conf import settings

from debian import deb822
import os
import apt
import sys
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

    if not implemented:
        return

    # Faster lookups than if this were a list
    pseudo_packages = set(pseudo_packages)
    for existing_package in PseudoPackage.objects.all():
        if existing_package.name not in pseudo_packages:
            # Existing packages which are no longer considered pseudo packages are
            # demoted to a subscription-only package.
            existing_package.package_type = Package.SUBSCRIPTION_ONLY_PACKAGE_TYPE
            existing_package.save()
        else:
            # If an existing package remained a pseudo package there will be no
            # action required so it is removed from the set.
            pseudo_packages.remove(existing_package.name)

    # The left over packages in the set are the ones that do not exist.
    for package_name in pseudo_packages:
        PseudoPackage.objects.create(name=package_name)


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
        self.cache_root_dir = settings.PTS_APT_CACHE_DIRECTORY
        self.sources_list_path = os.path.join(
            self.cache_root_dir,
            'sources.list')
        self.conf_file_path = os.path.join(self.cache_root_dir, 'apt.conf')

        self.sources = []
        self.packages = []

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

    def update_repositories(self):
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
