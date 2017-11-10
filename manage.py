#!/usr/bin/env python3

# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "distro_tracker.project.settings")
    os.environ.setdefault("DJANGO_LIVE_TEST_SERVER_ADDRESS",
                          "localhost:8081-8085")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
