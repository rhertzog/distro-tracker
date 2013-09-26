# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Package Tracking System settings

The settings are created dynamically by first importing defaults
values from :py:mod:`pts.project.settings.defaults` and then
values :py:mod:`pts.project.settings.local`. The test suite
is special cased and doesn't use the latter, instead it uses
:py:mod:`pts.project.settings.test`.
"""

import sys
from .defaults import *

if sys.argv[1:2] == ['test']:
    from .test import *
else:
    from .local import *
