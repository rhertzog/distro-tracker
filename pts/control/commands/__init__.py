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
