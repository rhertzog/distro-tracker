# -*- coding: utf-8 -*-

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
from django.conf import settings

from pts.control.tests.common import EmailControlTest
from pts.control.tests.common import PTS_CONTROL_EMAIL


class ControlBotBasic(EmailControlTest):
    def test_basic(self):
        """
        Tests if the proper headers are set for the reply message, that the
        output contains original lines prepended with '>'
        """
        input_lines = [
            "#command",
            "   thanks",
        ]
        self.set_input_lines(input_lines)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        for line in input_lines:
            self.assert_command_echo_in_response(line.strip())

    def test_not_plaintext(self):
        """
        Tests that the response to a non-plaintext message is a warning email.
        """
        self.make_multipart()
        self.add_part('application', 'octet-stream', b'asdf')

        self.control_process()

        self.assert_response_sent()
        self.assert_response_equal(render_to_string(
            'control/email-plaintext-warning.txt'))

    def test_multipart_with_plaintext(self):
        """
        Tests that the response to a multipart message which contains a
        text/plain part is correct.
        """
        self.make_multipart(alternative=True)
        input_lines = [
            '#command',
            'thanks',
        ]
        self.set_input_lines(input_lines)
        self.add_part('text', 'html', "#command\nthanks")

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        for line in input_lines:
            self.assert_command_echo_in_response(line.strip())

    def test_response_subject(self):
        """
        Tests that the subject of the response when there is no subject set in
        the request is correct.
        """
        self.set_input_lines(['#command', "thanks"])
        self.set_header('Subject', '')

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()

    def test_empty_no_response(self):
        """
        Tests that there is no response to an empty message.
        """
        self.control_process()

        self.assert_response_not_sent()

    def test_loop_no_response(self):
        """
        Tests that there is no response if the message's X-Loop is set to
        PTS_CONTROL_EMAIL
        """
        self.set_header('X-Loop', PTS_CONTROL_EMAIL)
        self.set_input_lines(['#command', 'thanks'])

        self.control_process()

        self.assert_response_not_sent()

    def test_no_valid_command_no_response(self):
        """
        Tests that there is no response for a message which does not contain
        any valid commands.
        """
        self.set_input_lines(['Some text', 'Some more text'])

        self.control_process()

        self.assert_response_not_sent()

    def test_stop_after_five_garbage_lines(self):
        """
        Tests that processing stops after encountering five garbage lines.
        """
        MAX_ALLOWED_ERRORS = settings.PTS_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS
        self.set_input_lines(
            ['help'] + ['garbage'] * MAX_ALLOWED_ERRORS + ['#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_not_in_response('#command')

    def test_stop_on_thanks_or_quit(self):
        """
        Tests that processing stops after encountering the thanks or quit
        command.
        """
        self.set_input_lines(['thanks', '#command'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('thanks')
        self.assert_in_response("Stopping processing here.")
        self.assert_command_echo_not_in_response('#command')

    def test_blank_line_skip(self):
        """
        Tests that processing skips any blank lines in the message. They are
        not considered garbage.
        """
        self.set_input_lines(['help', ''] + ['   '] * 5 + ['#comment'])

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('help')
        self.assert_command_echo_in_response('#comment')

    def test_utf8_message(self):
        """
        Tests that the bot sends replies to utf-8 encoded messages.
        """
        lines = ['üšßč', '한글ᥡ╥ສए', 'help']
        self.set_input_lines(lines)
        self.message.set_charset('utf-8')

        self.control_process()

        self.assert_response_sent()
        for line in lines:
            self.assert_command_echo_in_response(line)

    def test_subject_command(self):
        """
        Tests that a command given in the subject of the message is executed.
        """
        self.set_header('Subject', 'help')

        self.control_process()

        self.assert_response_sent()
        self.assert_command_echo_in_response('# Message subject')
        self.assert_command_echo_in_response('help')
