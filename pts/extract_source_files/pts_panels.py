# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements the classes necessary to place the links to extracted source
files in the :class:`pts.core.panels.VersionedLinks` panel.
"""
from __future__ import unicode_literals
from pts.core.panels import VersionedLinks
from pts.core.models import ExtractedSourceFile
from django.utils.safestring import mark_safe


class SourceFilesLinkProvider(VersionedLinks.LinkProvider):
    """
    Provides the links to extracted source files which are placed in the
    :class:`pts.core.panels.VersionedLinks` panel.
    """
    icons = [
        mark_safe('<i class="icon-plus-sign" title="changelog"></i>'),
        mark_safe('<i class="icon-pencil" title="copyright"></i>'),
        mark_safe('<i class="icon-cog" title="rules"></i>'),
        mark_safe('<i class="icon-info-sign" title="control"></i>'),
    ]

    _file_names =[
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
