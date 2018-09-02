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
Implements the Distro Tracker tasks necessary for interesting package source
files.
"""
import logging
import os

from django.core.files import File

from distro_tracker.core.models import ExtractedSourceFile
from distro_tracker.core.tasks import BaseTask
from distro_tracker.core.tasks.mixins import ProcessSourcePackage
from distro_tracker.core.tasks.schedulers import IntervalScheduler
from distro_tracker.core.utils.packages import AptCache

logger = logging.getLogger('distro_tracker.core.tasks')


class ExtractSourcePackageFiles(BaseTask, ProcessSourcePackage):
    """
    A task which extracts some files from a new source package version.
    The extracted files are:

    - debian/changelog
    - debian/copyright
    - debian/rules
    - debian/control
    - debian/watch
    """

    class Scheduler(IntervalScheduler):
        interval = 3600

    ALL_FILES_TO_EXTRACT = (
        'changelog',
        'copyright',
        'rules',
        'control',
        'watch',
    )

    def items_extend_queryset(self, queryset):
        return queryset.prefetch_related('extracted_source_files')

    def extract_files(self, source_package, files_to_extract=None):
        """
        Extract files for just the given source package.

        :type source_package: :class:`SourcePackage
            <distro_tracker.core.models.SourcePackage>`
        :type files_to_extract: An iterable of file names which should be
            extracted
        """
        if not hasattr(self, 'cache'):
            self.cache = AptCache()

        source_directory = self.cache.retrieve_source(
            source_package.source_package_name.name,
            source_package.version,
            debian_directory_only=True)
        debian_directory = os.path.join(source_directory, 'debian')

        if files_to_extract is None:
            files_to_extract = self.ALL_FILES_TO_EXTRACT

        for file_name in files_to_extract:
            file_path = os.path.join(debian_directory, file_name)
            if not os.path.exists(file_path):
                continue
            with open(file_path, 'rb') as f:
                extracted_file = File(f)
                ExtractedSourceFile.objects.create(
                    source_package=source_package,
                    extracted_file=extracted_file,
                    name=file_name)

    def execute_main(self):
        # First remove all source files which are no longer to be included.
        qs = ExtractedSourceFile.objects.exclude(
            name__in=self.ALL_FILES_TO_EXTRACT)
        qs.delete()

        # Process pending items
        for srcpkg in self.items_to_process():
            # Save what has been processed when it takes long enough that we
            # had to extend the lock
            if self.extend_lock():
                self.save_data()

            extracted_files = [
                extracted_file.name
                for extracted_file in srcpkg.extracted_source_files.all()
            ]
            files_to_extract = [
                file_name
                for file_name in self.ALL_FILES_TO_EXTRACT
                if file_name not in extracted_files
            ]
            if files_to_extract:
                try:
                    self.extract_files(srcpkg, files_to_extract)
                    self.item_mark_processed(srcpkg)
                except Exception:
                    logger.exception(
                        'Problem extracting source files for'
                        ' {pkg} version {ver}'.format(
                            pkg=srcpkg, ver=srcpkg.version))
            else:
                self.item_mark_processed(srcpkg)

        # TODO: remove extracted files associated to vanished source packages
