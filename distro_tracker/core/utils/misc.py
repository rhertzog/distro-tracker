# Copyright 2017 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Miscellaneous utilities that don't require their own python module.
"""

import hashlib
import json


def get_data_checksum(data):
    """Checksums a dict, without its prospective 'checksum' key/value."""

    if 'checksum' in data:
        to_hash = dict(data)
        to_hash.pop('checksum', None)
    else:
        to_hash = data

    json_dump = json.dumps(to_hash, sort_keys=True)
    return hashlib.md5(json_dump.encode('utf-8', 'ignore')).hexdigest()


def call_methods_with_prefix(obj, prefix, *args, **kwargs):
    """
    Identify all the object's methods that start with the given prefix and calls
    them in the alphabetical order while passing the remaining arguments as
    positional and keywords arguments.

    :param object obj: The object instance to inspect
    :param str prefix: The prefix used to identify the methods to call
    """
    attributes = sorted(filter(lambda x: x.startswith(prefix), dir(obj)))
    for name in attributes:
        method = getattr(obj, name)
        if callable(method):
            method(*args, **kwargs)
