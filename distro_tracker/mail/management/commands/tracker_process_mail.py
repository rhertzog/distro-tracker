# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements the management command to process mails from the mail queue.
"""
from django.core.management.base import BaseCommand

from distro_tracker.mail.processor import MailQueue


class Command(BaseCommand):
    """
    A Django management command used to run a daemon handling the mail queue.
    """
    def handle(self, *args, **kwargs):
        queue = MailQueue()
        queue.process_loop()  # Never returns
