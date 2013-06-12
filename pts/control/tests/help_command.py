from __future__ import unicode_literals

from django.template.loader import render_to_string

from control.tests.common import EmailControlTest


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
        out = render_to_string('control/help.txt')
        self.assert_in_response(out)

    def test_help_command(self):
        """
        Tests that the help command returns all the available commands and
        their descriptions.
        """
        self.set_input_lines(['help'])

        self.control_process()

        self.assert_correct_help_commands()
