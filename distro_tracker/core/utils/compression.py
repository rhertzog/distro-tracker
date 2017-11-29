# Copyright 2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Utilities for handling compression
"""

import os


def guess_compression_method(filepath):
    """Given filepath, tries to determine the compression of the file."""

    filepath = filepath.lower()

    extensions_to_method = {
        ".gz": "gzip",
        ".bz2": "bzip2",
        ".xz": "xz",
    }

    for (ext, method) in extensions_to_method.items():
        if filepath.endswith(ext):
            return method

    return None


def uncompress_content(file_handle, compression="auto"):
    """Receiving a file_handle, guess if it's compressed and then
    *CLOSES* it. Returns a new uncompressed handle.

    :param compression: The compression type. If not `auto`, then
    do not guess the compression and assume it's what referenced.
    :type compression: str

    """

    # A file_handle being provided, let's extract an absolute path.
    if compression == "auto":
        if hasattr(file_handle, 'name'):
            compression = guess_compression_method(file_handle.name)
        else:
            raise ValueError("Can't retrieve a name out of %r" % file_handle)

    if compression == "gzip":
        import gzip
        return gzip.open(filename=file_handle, mode="rb")
    elif compression == "bzip2":
        import bz2
        return bz2.open(filename=file_handle, mode="rb")
    elif compression == "xz":
        import lzma
        return lzma.open(filename=file_handle, mode="rb")
    elif compression is None:
        return file_handle
    else:
        raise NotImplementedError(
            "Unknown compression method: %r" % compression)
