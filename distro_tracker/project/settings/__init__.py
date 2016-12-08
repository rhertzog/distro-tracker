# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Distro Tracker settings

The settings are created dynamically by first importing defaults
values from :py:mod:`distro_tracker.project.settings.defaults` and then
values from :py:mod:`distro_tracker.project.settings.local` (or from
:py:mod:`distro_tracker.project.settings.selected` if the latter
has not been created by the administrator). The test suite
is special cased and doesn't use any of those, instead it uses
:py:mod:`distro_tracker.project.settings.test`.
"""

import sys
from .defaults import *          # noqa

if sys.argv[1:2] == ['test']:
    from .test import *          # noqa
else:
    try:
        from .local import *     # noqa
    except ImportError:
        from .selected import *  # noqa

compute_default_settings(globals())  # noqa
