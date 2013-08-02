# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Implements the PTS tasks necessary for interesting package source files."""
from __future__ import unicode_literals
from pts.core.tasks import BaseTask
from pts.core.utils.packages import AptCache
from pts.core.models import ExtractedSourceFile
from pts.core.models import SourcePackage
from django.core.files import File

import os
import logging

logger = logging.getLogger('pts.core.tasks')


class ExtractSourcePackageFiles(BaseTask):
    """
    A task which extracts some files from a new source package version.
    The extracted files are:

    - debian/changelog
    - debian/copyright
    - debian/rules
    - debian/control
    - debian/watch
    """
    DEPENDS_ON_EVENTS = (
        'new-source-package-version',
    )

    PRODUCES_EVENTS = (
        'source-files-extracted',
    )

    def extract_files(self, source_package):
        """
        Extract files for just the given source package.

        :type source_package: :class:`SourcePackage <pts.core.models.SourcePackage>`
        """
        cache = AptCache()
        source_directory = cache.retrieve_source(
            source_package.source_package_name.name,
            source_package.version,
            debian_directory_only=True)
        debian_directory = os.path.join(source_directory, 'debian')

        files_to_extract = [
            'changelog',
            'copyright',
            'rules',
            'control',
            'watch',
        ]
        for file_name in files_to_extract:
            file_path = os.path.join(debian_directory, file_name)
            if not os.path.exists(file_path):
                continue
            with open(file_path, 'r') as f:
                extracted_file = File(f)
                ExtractedSourceFile.objects.create(
                    source_package=source_package,
                    extracted_file=extracted_file,
                    name=file_name)

    def execute(self):
        new_version_pks = [
            event.arguments['pk']
            for event in self.get_all_events()
        ]
        source_packages = SourcePackage.objects.filter(pk__in=new_version_pks)
        source_packages = source_packages.select_related()

        for source_package in source_packages:
            try:
                self.extract_files(source_package)
            except:
                logger.exception(
                    'Problem extracting source files for'
                    ' {pkg} version {ver}'.format(
                        pkg=source_package, ver=source_package.version))

        self.raise_event('source-files-extracted')
