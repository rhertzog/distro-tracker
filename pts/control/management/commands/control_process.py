from django.core.management.base import BaseCommand

import control

import sys
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    A Django management command used to invoke the processing of control
    messages.

    The received message is expected as input on stdin.
    """
    input_file = sys.stdin

    def handle(self, *args, **kwargs):
        logger.info('Processing a control message')

        input_data = self.input_file.read()
        control.process(input_data)

        logger.info('Completed processing a control message')
