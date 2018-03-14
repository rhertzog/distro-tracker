# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements the management command which invokes the dispatch functionality.
"""
import io
import sys

from django.core.management.base import BaseCommand

from distro_tracker.core.utils.email_messages import message_from_bytes
from distro_tracker.mail.processor import MailProcessor


class Command(BaseCommand):
    """
    A Django management command used to invoke the dispatch functionality.

    The received message is expected as input on stdin.
    """
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        # Get the binary buffer behind the text one
        try:
            self.input_file = self.input_file.detach()
        except io.UnsupportedOperation:
            pass
        msg = message_from_bytes(self.input_file.read())
        handler = MailProcessor(msg)
        handler.process()
