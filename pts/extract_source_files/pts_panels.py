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
Implements the classes necessary to place the links to extracted source
files in the :class:`pts.core.panels.VersionedLinks` panel.
"""
from __future__ import unicode_literals
from pts.core.panels import VersionedLinks
from pts.core.models import ExtractedSourceFile


class SourceFilesLinkProvider(VersionedLinks.LinkProvider):
    """
    Provides the links to extracted source files which are placed in the
    :class:`pts.core.panels.VersionedLinks` panel.
    """
    icons = [
        'changelog',
        'copyright',
        'rules',
        'control',
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
