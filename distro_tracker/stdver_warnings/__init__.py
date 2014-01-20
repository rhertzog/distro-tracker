# -*- coding: utf-8 -*-

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
This app implements displaying warnings if a package has an outdated
Standards-Version field, when compared to the current version of the
``debian-policy`` package in the default repository.

The warning is displayed as an entry to the
:class:`distro_tracker.core.panels.ActionNeededPanel`>

This functionality is extracted to a separate app to allow other vendors to
optionally activate it.
"""
