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
Implements the management command which invokes the dispatch functionality.
"""
from django.core.management.base import BaseCommand
from django.utils import six

from pts.mail import dispatch

import os
import sys
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    A Django management command used to invoke the dispatch functionality.

    The received message is expected as input on stdin.
    """
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        logger.info('Processing a received package message')

        if six.PY3:
            self.input_file = self.input_file.detach()
        input_data = self.input_file.read()
        sent_to = self._get_to_address()

        dispatch.process(input_data, sent_to)

        logger.info('Completed processing a received package message')

    def _get_to_address(self):
        """
        Gets the envelope To address. The To address in the message cannot be
        used to determine to which package the mail was sent.

        This method tries to get the address from environment variables set by
        the MTA. Both Postfix and Exim are supported.
        """
        sent_to = os.environ.get('LOCAL_PART')
        if sent_to:
            # Exim
            sent_to = '{local_part}@{domain}'.format(
                local_part=sent_to,
                domain=os.environ.get('DOMAIN'))
        else:
            # Try Postfix
            sent_to = os.environ.get('ORIGINAL_RECIPIENT')

        return sent_to
