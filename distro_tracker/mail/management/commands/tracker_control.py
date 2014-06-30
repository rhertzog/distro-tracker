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
Implements a management command used to invoke the processing of control
messages.
"""
from django.core.management.base import BaseCommand
from django.utils import six

from distro_tracker.mail import control

import sys


class Command(BaseCommand):
    """
    A Django management command used to invoke the processing of control
    messages.

    The received message is expected as input on stdin.
    """
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        if six.PY3:
            self.input_file = self.input_file.detach()
        input_data = self.input_file.read()
        control.process(input_data)
