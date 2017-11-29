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


def get_uncompressed_stream(input_stream, compression="auto"):
    """
    Returns a file-like object (aka stream) providing an uncompressed
    version of the content read on the input stream provided.

    :param input_stream: The file-like object providing compressed data.
    :param compression: The compression type. Specify "auto" to let the function
    guess it out of the associated filename (the input_stream needs to have
    a name attribute, otherwise a ValueError is raised).
    :type compression: str
    """

    if compression == "auto":  # Try to guess compression method if possible
        if hasattr(input_stream, 'name'):
            compression = guess_compression_method(input_stream.name)
        else:
            raise ValueError("Can't retrieve a name out of %r" % input_stream)

    if compression == "gzip":
        import gzip
        return gzip.open(filename=input_stream, mode="rb")
    elif compression == "bzip2":
        import bz2
        return bz2.open(filename=input_stream, mode="rb")
    elif compression == "xz":
        import lzma
        return lzma.open(filename=input_stream, mode="rb")
    elif compression is None:
        return input_stream
    else:
        raise NotImplementedError(
            "Unknown compression method: %r" % compression)
