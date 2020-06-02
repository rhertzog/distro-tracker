# Copyright 2013-2020 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
A management command which is used to process an email message which could
potentially be turned into a news item.
"""

import logging
import sys

from django.core.management.base import BaseCommand

from distro_tracker.core.utils import message_from_bytes
from distro_tracker.mail.dispatch import classify_message

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        logger.info("Processing a received message")
        # Make sure to read binary data.
        input_data = self.input_file.detach().read()

        msg = message_from_bytes(input_data)
        pkg, keyword = classify_message(msg)

        logger.info('Completed processing a received message for %s/%s',
                    pkg, keyword)
