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
Tests for the :py:mod:`pts.vendor` app.

The test suite automatically includes any tests available in a ``tests``
module of all subpackages.
"""

from __future__ import unicode_literals
from django.test import SimpleTestCase
from django.test.utils import override_settings

from pts.mail.tests.tests_dispatch import DispatchBaseTest
import sys
import inspect
import importlib


def get_subpackages():
    """
    Helper function returns all subpackages of the :py:mod:`pts.vendor` package.
    """
    import pkgutil

    current_module = sys.modules[__name__]
    current_package = sys.modules[current_module.__package__]

    return [
        name
        for _, name, is_pkg in pkgutil.iter_modules(current_package.__path__)
        if is_pkg
    ]


def get_test_cases(tests_module):
    """
    Returns a list of all
    :py:class:`django.test.SimpleTestCase` subclasses from the given module.

    :param tests_module: The module from which
        :py:class:`django.test.SimpleTestCase` should be extracted.
    """
    module_name = tests_module.__name__
    return [
        klass
        for _, klass in inspect.getmembers(tests_module, inspect.isclass)
        if issubclass(klass, SimpleTestCase) and klass.__module__ == module_name
    ]


def suite():
    """
    Loads tests found in all subpackages of the :py:mod:`pts.vendor` package.
    """
    import unittest
    suite = unittest.TestSuite()

    subpackages = get_subpackages()

    # Build a list of all possible tests modules in the subpackages.
    tests_modules = [
        '..' + subpackage + '.tests'
        for subpackage in subpackages
    ]
    # Add this tests module to the list too
    tests_modules.append('..tests')

    # Try importing the tests from all SimpleTestCase classes defined in the
    # found tests modules.
    for tests_module_name in tests_modules:
        try:
            tests_module = importlib.import_module(tests_module_name, __name__)
        except ImportError:
            # The subpackage does not have a tests module.
            continue

        # Following convention, first try using a suite() function in the
        # module.
        if hasattr(tests_module, 'suite') and tests_module.__name__ != __name__:
            suite.addTest(getattr(tests_module, 'suite')())
        else:
            # Just add all SimpleTestCase subclasses.
            for test_case in get_test_cases(tests_module):
                all_tests = unittest.TestLoader().loadTestsFromTestCase(test_case)
                suite.addTest(all_tests)

    return suite


@override_settings(PTS_VENDOR_RULES=None)
class DispatchBaseNoVendorModuleTest(DispatchBaseTest):
    """
    Tests that the base dispatch tests pass even when there is no vendor
    specific module set.
    """
    pass
