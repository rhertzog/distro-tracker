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
Defines and implements all Package Tracking System control commands.
"""
from __future__ import unicode_literals

from django.conf import settings

import sys
import inspect

from pts.core.utils import pts_render_to_string
from pts.control.commands.base import *
from pts.control.commands.keywords import *
from pts.control.commands.misc import *
from pts.control.commands.confirmation import *

MAX_ALLOWED_ERRORS = settings.PTS_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS


class HelpCommand(Command):
    """
    Displays help for all the other commands -- their description.
    """
    META = {
        'description': '''help
  Shows all available commands''',
        'name': 'help',
        'position': 5,
    }

    REGEX_LIST = (
        r'$',
    )

    def handle(self):
        self.reply(pts_render_to_string('control/help.txt', {
            'descriptions': [
                command.META.get('description', '')
                for command in UNIQUE_COMMANDS
            ],
        }))


UNIQUE_COMMANDS = sorted(
    (klass
     for _, klass in inspect.getmembers(sys.modules[__name__], inspect.isclass)
     if klass != Command and issubclass(klass, Command)),
    key=lambda cmd: cmd.META.get('position', float('inf'))
)


class CommandFactory(object):
    """
    Creates instances of Command classes based on the given context.

    Context is used to fill in parameters when the command has not found
    it in the given command line.
    """
    def __init__(self, context):
        self.context = context

    def get_command_function(self, line):
        """
        Returns a function which executes the functionality of the command
        which corresponds to the given arguments.
        """
        for cmd in UNIQUE_COMMANDS:
            # Command exists
            match = cmd.match_line(line)
            if not match:
                continue
            kwargs = match.groupdict()
            if not kwargs:
                # No named patterns found, pass them in the order they were
                # matched.
                args = match.groups()
                return cmd(*args)
            else:
                # Update the arguments which weren't matched from the given
                # context, if available.
                kwargs.update({
                    key: value
                    for key, value in self.context.items()
                    if key in kwargs and not kwargs[key] and value
                })
                return cmd(**kwargs)


class CommandProcessor(object):
    def __init__(self, factory, confirmed=False):
        self.factory = factory
        self.confirmed = confirmed
        self.confirmation_set = None

        self.out = []
        self.errors = 0
        self.processed = set()

    def echo_command(self, line):
        self.out.append('> ' + line)

    def output(self, text):
        self.out.append(text)

    def run_command(self, command):
        if command.get_command_text() not in self.processed:
            # Only process the command if it was not previously processed.
            if getattr(command, 'needs_confirmation', False):
                command.is_confirmed = self.confirmed
                command.confirmation_set = self.confirmation_set
            # Now run the command
            command_output = command()
            if not command_output:
                command_output = ''
            self.output(command_output)
            self.processed.add(command.get_command_text())

    def process(self, lines):
        if self.errors == MAX_ALLOWED_ERRORS:
            return

        for line in lines:
            line = line.strip()
            self.echo_command(line)

            if not line or line.startswith('#'):
                continue
            command = self.factory.get_command_function(line)

            if not command:
                self.errors += 1
                if self.errors == MAX_ALLOWED_ERRORS:
                    self.output(
                        '{MAX_ALLOWED_ERRORS} lines '
                        'contain errors: stopping.'.format(
                            MAX_ALLOWED_ERRORS=MAX_ALLOWED_ERRORS))
                    return
            else:
                self.run_command(command)

            if isinstance(command, QuitCommand):
                return

    def is_success(self):
        # Send a response only if there were some commands processed
        if self.processed:
            return True
        else:
            return False

    def get_output(self):
        return '\n'.join(self.out)
