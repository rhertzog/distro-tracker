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

from django.template.loader import render_to_string

from pts.control.tests.common import EmailControlTest
from pts.control.commands import UNIQUE_COMMANDS


class HelpCommandTest(EmailControlTest):
    """
    Tests for the help command.
    """
    def setUp(self):
        EmailControlTest.setUp(self)

    def assert_correct_help_commands(self):
        """
        Helper method checks if all the commands and their descriptions are in
        the response.
        """
        out = render_to_string('control/help.txt', {
            'descriptions': [
                cmd.META.get('description', '') for cmd in UNIQUE_COMMANDS
            ]
        })
        self.assert_in_response(out)

    def test_help_command(self):
        """
        Tests that the help command returns all the available commands and
        their descriptions.
        """
        self.set_input_lines(['help'])

        self.control_process()

        self.assert_correct_help_commands()
