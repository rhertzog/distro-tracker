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
This Django app implements a custom User authentication model which lets users
log in using a set of different email addresses.
"""
from django.conf import settings
import importlib


def run_hook(name, *args, **kwargs):
    """
    Since :mod:`django_email_accounts` provides a way for users to execute
    custom functions at certain points, this function is used to run find
    the appropriate one and run it with the given arguments and keyword
    arguments.
    """
    name_to_setting = {
        'post-merge': 'DJANGO_EMAIL_ACCOUNTS_POST_MERGE_HOOK',
        'pre-login': 'DJANGO_EMAIL_ACCOUNTS_PRE_LOGIN_HOOK',
        'post-logout-redirect': 'DJANGO_EMAIL_ACCOUNTS_POST_LOGOUT_REDIRECT',
    }
    if name not in name_to_setting:
        return

    settings_name = name_to_setting[name]
    function_name = getattr(settings, settings_name, None)
    if not function_name:
        return

    module, function_name = function_name.rsplit('.', 1)
    module = importlib.import_module(module)
    function = getattr(module, function_name)

    return function(*args, **kwargs)
