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
Defines and implements all Distro Tracker control commands.
"""
from __future__ import unicode_literals

from django.conf import settings

import sys
import inspect

from distro_tracker.core.utils import distro_tracker_render_to_string
from distro_tracker.mail.control.commands.base import Command
from distro_tracker.mail.control.commands.keywords import (  # noqa
    ViewDefaultKeywordsCommand,
    ViewPackageKeywordsCommand,
    SetDefaultKeywordsCommand,
    SetPackageKeywordsCommand,
)
from distro_tracker.mail.control.commands.teams import (  # noqa
    JoinTeam,
    LeaveTeam,
    ListTeamPackages,
    WhichTeams,
)
from distro_tracker.mail.control.commands.misc import (  # noqa
    SubscribeCommand,
    UnsubscribeCommand,
    WhichCommand,
    WhoCommand,
    QuitCommand,
    UnsubscribeallCommand,
)
from distro_tracker.mail.control.commands.confirmation import (  # noqa
    ConfirmCommand
)

MAX_ALLOWED_ERRORS = settings.DISTRO_TRACKER_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS


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
        self.reply(distro_tracker_render_to_string('control/help.txt', {
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
"""
A list of all :py:class:`Command` that are defined.
"""


class CommandFactory(object):
    """
    Creates instances of
    :py:class:`Command <distro_tracker.mail.control.commands.base.Command>`
    classes based on the given context.

    Context is used to fill in parameters when the command has not found
    it in the given command line.
    """
    def __init__(self, context):
        #: A dict which is used to fill in parameters' values when they are not
        #: found in the command line.
        self.context = context

    def get_command_function(self, line):
        """
        Returns a function which executes the functionality of the command
        which corresponds to the given arguments.

        :param line: The line for which a command function should be returned.
        :type line: string

        :returns: A callable which when called executes the functionality of a
            command matching the given line.
        :rtype: :py:class:`Command
            <distro_tracker.mail.control.commands.base.Command>` subclass
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
                command = cmd(**kwargs)
                command.context = dict(self.context.items())
                return command


class CommandProcessor(object):
    """
    A class which performs command processing.
    """
    def __init__(self, factory, confirmed=False):
        """
        :param factory: Used to obtain
            :py:class:`Command
            <distro_tracker.mail.control.commands.base.Command>` instances
            from command text which is processed.
        :type factory: :py:class`CommandFactory` instance
        :param confirmed: Indicates whether the commands being executed have
            already been confirmed or if those which require confirmation will
            be added to the set of commands requiring confirmation.
        :type confirmed: Boolean
        """
        self.factory = factory
        self.confirmed = confirmed
        self.confirmation_set = None

        self.out = []
        self.errors = 0
        self.processed = set()

    def echo_command(self, line):
        """
        Echoes the line to the command processing output. The line is quoted in
        the output.

        :param line: The line to be echoed back to the output.
        """
        self.out.append('> ' + line)

    def output(self, text):
        """
        Include the given line in the command processing output.

        :param line: The line of text to be included in the output.
        """
        self.out.append(text)

    def run_command(self, command):
        """
        Runs the given command.

        :param command: The command to be ran.
        :type command: :py:class:`Command
            <distro_tracker.mail.control.commands.base.Command>`
        """
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
        """
        Processes all the given lines of text which are interpreted as
        commands.

        :param lines: A list of strings each representing a single line which
            is to be regarded as a command.
        """
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
                        'without commands: stopping.'.format(
                            MAX_ALLOWED_ERRORS=MAX_ALLOWED_ERRORS))
                    return
            else:
                self.run_command(command)

            if isinstance(command, QuitCommand):
                return

    def is_success(self):
        """
        Checks whether any command was successfully processed.

        :returns True: when at least one command is successfully executed
        :returns False: when no commands were successfully executed
        :rtype: Boolean
        """
        # Send a response only if there were some commands processed
        if self.processed:
            return True
        else:
            return False

    def get_output(self):
        """
        Returns the resulting output of processing all given commands.

        :rtype: string
        """
        return '\n'.join(self.out)
