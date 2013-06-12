from django.core.management.base import BaseCommand

import dispatch

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

        input_data = self.input_file.read()
        dispatch.process(input_data)

        logger.info('Completed processing a received package message')
