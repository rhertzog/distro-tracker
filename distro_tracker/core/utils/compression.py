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
Utilities for handling compression
"""

import os


def guess_compression_method(filepath):
    """Given filepath, tries to determine the compression of the file."""

    filepath = filepath.lower()

    extensions_to_method = {
        "gz": "gzip",
        "bz2": "bzip2",
        "xz": "xzip",
        "txt": "plain",
    }

    for (ext, method) in extensions_to_method.items():
        if filepath.endswith(ext):
            return method

    return "plain"


def uncompress_content(file_handle, compression_method="auto"):
    """Receiving a file_handle, guess if it's compressed and then
    *CLOSES* it. Returns a new uncompressed handle.

    :param compression: The compression type. If not `auto`, then
    do not guess the compression and assume it's what referenced.
    :type compression: str

    """

    # A file_handle being provided, let's extract an absolute path.
    file_path = os.path.abspath(file_handle.name)
    if compression_method == "auto":
        # Guess the compression method from file_path
        compression_method = guess_compression_method(file_path)
    elif compression_method is None:
        compression_method = "plain"

    _open = None

    def _open(fobj, mode):
        """Proxy open function depending on the compression method"""
        if compression_method == "gzip":
            import gzip
            return gzip.open(filename=fobj, mode=mode)
        elif compression_method == "bzip2":
            import bz2
            return bz2.open(filename=fobj, mode=mode)
        elif compression_method == "xzip":
            import lzma
            return lzma.open(filename=fobj, mode=mode)
        elif compression_method == "plain":
            return fobj
        else:
            raise NotImplementedError(
                (
                    "The compression method %r is not known or not yet "
                    "implemented."
                ) % (compression_method,)
            )

    return _open(file_handle, "rb")
