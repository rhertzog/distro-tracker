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
A management command which is used to process an email message which could
potentially be turned into a news item.
"""

from django.core.management.base import BaseCommand
from django.utils import six

from pts.mail.mail_news import process

import sys
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        logger.info("Processing a received message")
        # Make sure to read binary data.
        if six.PY3:
            self.input_file = self.input_file.detach()
        input_data = self.input_file.read()

        process(input_data)

        logger.info('Completed processing a received message')
