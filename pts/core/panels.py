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
from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import memoize
from django.conf import settings


class BasePanel(object):
    """
    A base class representing panels which are displayed on a package page.

    To include a panel on the package page, the users must subclass this class
    and include the path to the new class in the project settings in order to
    have it displayed on the page.
    """
    def __init__(self, package):
        self.package = package

    @property
    def context(self):
        """
        Should return a dictionary representing context variables necessary for
        the panel.
        When the panels template is rendered, it will have access to the values
        in this dictionary.
        """
        return {}

    @property
    def title(self):
        """
        The title of the panel.
        """
        return ''

    @property
    def template_name(self):
        """
        If the panel has a corresponding template which is used to render its
        HTML output, this property should contain the name of this template.
        """
        return None

    @property
    def html_output(self):
        """
        If the panel does not want to use a template, it can return rendered
        HTML in this property. The HTML needs to be marked safe or else it will
        be escaped in the final output.
        """
        return None


def get_panel_by_name(panel_path):
    import importlib
    if '.' not in panel_path:
        raise ImproperlyConfigured(panel_path + ' is not a valid path to a class')
    module_name, panel_class_name = panel_path.rsplit('.', 1)

    try:
        module = importlib.import_module(module_name)
    except ImportError:
        raise ImproperlyConfigured('Given module ' + panel_path + ' not found.')

    panel_class = getattr(module, panel_class_name, None)
    if panel_class is None:
        raise ImproperlyConfigured(
            panel_path + ' class not found in the given module.')

    if not issubclass(panel_class, BasePanel):
        raise ImproperlyConfigured(panel_path + ' is not derived from BasePanel')

    return panel_class
get_panel_by_name = memoize(get_panel_by_name, {}, 1)


def get_panels_for_package(package):
    """
    Returns a dict containing an instance of each panel for a package.

    The keys of the dict are the panel positions and the values are lists of
    panel instances which are to go in the given position.
    """
    registered_panels = settings.PTS_PACKAGE_PAGE_PANELS
    panels = {
        position: [
            get_panel_by_name(panel_name)(package)
            for panel_name in panel_list
        ]
        for position, panel_list in registered_panels.items()
    }

    return panels
