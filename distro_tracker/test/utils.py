# -*- coding: utf-8 -*-

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.


import contextlib
import shutil
import tempfile


@contextlib.contextmanager
def make_temp_directory(suffix=''):
    """
    Helper context manager which creates a temporary directory on enter and
    cleans it up on exit.
    """
    temp_dir_name = tempfile.mkdtemp(suffix=suffix)
    try:
        yield temp_dir_name
    finally:
        shutil.rmtree(temp_dir_name)


def set_mock_response(mock_requests, text="", headers=None, status_code=200):
    """
    Helper method which sets a mock response to the given mock requests
    module.

    It takes care to correctly set the return value of all useful requests
    module functions.

    :param mock_requests: A mock requests module.
    :param text: The text of the response.
    :param headers: The headers of the response.
    :param status_code: The status code of the response.
    """
    if headers is None:
        headers = {}
    mock_response = mock_requests.models.Response()
    mock_response.headers = headers
    mock_response.status_code = status_code
    mock_response.ok = status_code < 400
    mock_response.text = text
    mock_response.content = text.encode('utf-8')
    mock_response.iter_lines.return_value = text.splitlines()
    mock_requests.get.return_value = mock_response
