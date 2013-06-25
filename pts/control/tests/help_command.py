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


from pts.core.utils import pts_render_to_string
from pts.control.tests.common import EmailControlTest
from pts.control.commands import UNIQUE_COMMANDS


class HelpCommandTest(EmailControlTest):
    """
    Tests for the help command.
    """
    def get_all_help_command_descriptions(self):
        """
        Helper method returning the description of all commands.
        """
        return (cmd.META.get('description', '') for cmd in UNIQUE_COMMANDS)

    def test_help_command(self):
        """
        Tests that the help command returns all the available commands and
        their descriptions.
        """
        self.set_input_lines(['help'])

        self.control_process()

        self.assert_in_response(pts_render_to_string('control/help.txt', {
            'descriptions': self.get_all_help_command_descriptions()
        }))
