# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals

from django.utils import six

import re
from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL


class MetaCommand(type):
    """
    Meta class for PTS Commands.

    Transforms the ``REGEX_LIST`` given in the Command to include all aliases
    of the command so when implementing a Command subclass, it is not necessary
    to include a separate regex for each command or a long one listing every
    option.
    """
    def __init__(cls, name, bases, dct):
        if not getattr(cls, 'META', None):
            return
        joined_aliases = '|'.join(
            alias
            for alias in [cls.META['name']] + cls.META.get('aliases', [])
        )
        cls.REGEX_LIST = tuple(
            '^(?:' + joined_aliases + ')' + regex
            for regex in cls.REGEX_LIST
        )


class Command(six.with_metaclass(MetaCommand)):
    """
    Base class for commands. Instances of this class can be used for NOP
    commands.
    """
    __metaclass__ = MetaCommand

    """
    Meta information about the command, such as:
     - Description
     - Name
     - List of aliases
     - Preferred position in the help output
    """
    META = {}
    """
    A list of regular expressions which, when matched to a string, identify
    a command. Additionally, any named group in the regular expression should
    exactly match the name of the parameter in the constructor of the command.
    If unnamed groups are used, their order must be the same as the order of
    parameters in the constructor of the command.
    This is very similar to how Django handles linking views and URLs.

    It is only necessary to list the part of the command's syntax to
    capture the parameters, while the name and all aliases given in the META
    dict are automatically assumed when matching a string to the command.
    """
    REGEX_LIST = ()

    def __init__(self, *args):
        self._sent_mails = []
        self.out = []

    def __call__(self):
        """
        The base class delegates execution to the appropriate handle method
        and handles the reply.
        """
        self.handle()
        return self.render_reply()

    def handle(self):
        """
        Performs the necessary steps to execute the command.
        """
        pass

    def is_valid(self):
        return True

    def get_command_text(self, *args):
        """
        Returns a string representation of the command.
        """
        return ' '.join((self.META.get('name', '#'), ) + args)

    @classmethod
    def match_line(cls, line):
        """
        Class method to check whether the given line matches the command.
        """
        for pattern in cls.REGEX_LIST:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                return match

    def render_reply(self):
        """
        Returns a string representing the command's reply.
        """
        return '\n'.join(self.out)

    def reply(self, message):
        """
        Adds a message to the command's reply.
        """
        self.out.append(message)

    def warn(self, message):
        """
        Adds a warning to the command's reply.
        """
        self.out.append('Warning: ' + message)

    def error(self, message):
        """
        Adds an error message to the command's reply.
        """
        self.out.append("Error: " + message)

    def list_reply(self, items, bullet='*'):
        """
        Includes a list of items in the reply. Each item is converted to a
        string before being output.
        """
        for item in items:
            self.reply(bullet + ' ' + str(item))
