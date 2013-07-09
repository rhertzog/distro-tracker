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
from pts.core.utils.email_messages import (
    name_and_address_from_string as parse_address,
    names_and_addresses_from_string as parse_addresses
)


def extract_vcs_information(stanza):
    """
    Extracts the VCS information from a package's Sources entry.
    """
    vcs = {}
    for key, value in stanza.items():
        key = key.lower()
        if key == 'vcs-browser':
            vcs['browser'] = value
        elif key.startswith('vcs-'):
            vcs['type'] = key[4:]
            vcs['url'] = value
    return vcs


def extract_information_from_sources_entry(stanza):
    """
    Extracts information from a Sources file entry and returns it in the form
    of a dictionary.
    The input parameter should be a case-insensitive dictionary (or contain
    lower-case keys only) containing the entry's key-value pairs.
    """
    binaries = [
        binary.strip()
        for binary in stanza['binary'].split(',')
    ]
    entry = {
        'version': stanza['version'],
        'homepage': stanza.get('homepage', ''),
        'priority': stanza.get('priority', ''),
        'section': stanza.get('section', ''),
        'architectures': stanza['architecture'].split(),
        'binary_packages': binaries,
        'maintainer': parse_address(stanza['maintainer']),
        'uploaders': parse_addresses(stanza.get('uploaders', '')),
        'standards_version': stanza.get('standards-version', ''),
        'vcs': extract_vcs_information(stanza),
    }

    return entry
