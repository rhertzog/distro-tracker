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
Implements the classes necessary to place the links to extracted source
files in the :class:`distro_tracker.core.panels.VersionedLinks` panel.
"""
from distro_tracker.core.models import ExtractedSourceFile
from distro_tracker.core.panels import VersionedLinks
from distro_tracker.core.templatetags.distro_tracker_extras import octicon


class SourceFilesLinkProvider(VersionedLinks.LinkProvider):
    """
    Provides the links to extracted source files which are placed in the
    :class:`distro_tracker.core.panels.VersionedLinks` panel.
    """
    icons = [
        octicon('tasklist', 'changelog'),
        octicon('law', 'copyright'),
        octicon('tools', 'rules'),
        octicon('package', 'control'),
    ]

    _file_names = [
        'changelog',
        'copyright',
        'rules',
        'control',
    ]

    def get_link_for_icon(self, package, index):
        file_name = self._file_names[index]
        try:
            extracted = package.extracted_source_files.get(name=file_name)
        except ExtractedSourceFile.DoesNotExist:
            return

        return extracted.extracted_file.url
