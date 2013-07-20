# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

"""An app which enables the PTS to access vendor-specific functionality.

Vendors can define their own specific set of rules for mail dispatch and the
Web interface or provide additional data which the PTS can plug in to
appropriate functions.

Each rule should be implemented as a callable which takes a defined set of
arguments with a predefined name. The supported callables are listed in the
:py:mod:`pts.vendor.skeleton.rules` module of the :py:mod:`pts.vendor.skeleton`
package which can serve as a starting point for the implementation of the
vendor-specific functions.

.. note::
   You should copy this package to a new directory and give it a descriptive
   name.

.. note::
   Make sure the package is a valid Django app.

"""

from pts.vendor.common import get_callable, call
