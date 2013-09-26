# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals


class PluginRegistry(type):
    """
    A metaclass which any class that wants to behave as a registry can use.

    When classes derived from classes which use this metaclass are
    instantiated, they are added to the list :attr:`plugins`.
    The concrete classes using this metaclass are free to decide how to use
    this list.

    This metaclass also adds an :meth:`unregister_plugin` classmethod to all concrete
    classes which removes the class from the list of plugins.
    """
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'plugins'):
            cls.plugins = []
        else:
            cls.plugins.append(cls)

        cls.unregister_plugin = classmethod(
            lambda cls: cls.plugins.remove(cls)
        )
