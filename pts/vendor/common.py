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
A module which defines functions to allow other parts of the PTS to hook
into the vendor-specific functionality.
"""
from django.conf import settings


class InvalidPluginException(Exception):
    pass


def get_callable(name):
    """
    Returns a callable object from the vendor-provided module based on the
    string name given as the parameter.
    If no callable object with the given name is found in the vendor module
    an exception is raised.
    """
    import importlib
    vendor_module = importlib.import_module(settings.PTS_VENDOR_RULES)

    function = getattr(vendor_module, name, None)
    if not function:
        raise InvalidPluginException("{name} not found in {module}".format(
            name=name, module=settings.PTS_VENDOR_RULES))
    if not callable(function):
        raise InvalidPluginException("{name} is not callable.".format(
            name=name))

    return function
