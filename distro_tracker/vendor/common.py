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
A module which defines functions to allow other parts of Distro Tracker to hook
into the vendor-specific functionality.
"""
from django.conf import settings


class InvalidPluginException(Exception):
    pass


class PluginProcessingError(Exception):
    pass


def get_callable(name):
    """
    Returns a callable object from the vendor-provided module based on the
    string name given as the parameter.
    If no callable object with the given name is found in the vendor module
    an exception is raised.

    :param name: The name of the callable which should be returned
    :type name: string
    """
    import importlib
    if (not hasattr(settings, 'DISTRO_TRACKER_VENDOR_RULES') or
            not settings.DISTRO_TRACKER_VENDOR_RULES):
        raise InvalidPluginException("No vendor specific module set.")

    vendor_module = importlib.import_module(settings.DISTRO_TRACKER_VENDOR_RULES)

    function = getattr(vendor_module, name, None)
    if not function:
        raise InvalidPluginException("{name} not found in {module}".format(
            name=name, module=settings.DISTRO_TRACKER_VENDOR_RULES))
    if not callable(function):
        raise InvalidPluginException("{name} is not callable.".format(
            name=name))

    return function


def call(name, *args, **kwargs):
    """
    Function which executes the vendor-specific function with the given name by
    passing it the given arguments.

    It returns a tuple ``(result, implemented)`` where the values represent:

    - result -- the corresponding function's return value. If the function was
      not found, ``None`` is given.
    - implemented -- a Boolean indicating whether the package implements the
      given function. This way clients can differentiate between functions with
      no return value and non-implemented functions.

    :param name: The name of the vendor-specific function that should be
        called.
    """
    try:
        func = get_callable(name)
    except (ImportError, InvalidPluginException):
        return None, False

    return func(*args, **kwargs), True
