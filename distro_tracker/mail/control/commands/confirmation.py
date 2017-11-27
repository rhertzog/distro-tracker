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
Implements classes and functions related to commands which require confirmation
and confirming such commands.
"""

from distro_tracker.core.utils import get_or_none
from distro_tracker.mail.models import CommandConfirmation
from distro_tracker.mail.control.commands.base import Command


def needs_confirmation(klass):
    """
    A class decorator to mark that a
    :py:class:`Command <distro_tracker.mail.control.commands.base.Command>`
    subclass requires confirmation before it is executed.

    Classes decorated by this decorator can provide two additional methods:

    - ``pre_confirm`` - for actions which should come before asking for
       confirmation for the command. If this method does not return an
       object which evalutes as a True Boolean, no confirmation is sent.
       It should also make sure to add appropriate status messages to the
       response.
       If the method is not provided, then a default response indicating that
       a confirmation is required is output.

    - ``get_confirmation_message`` - Method which should return a string
       containing an additional message to be included in the confirmation
       email.
    """
    klass.needs_confirmation = True
    klass.is_confirmed = False

    def pre_confirm_default(self):
        self.reply('A confirmation mail has been sent to ' + self.user_email)
        return True

    def decorate_call(func):
        def wrapper(self):
            # When the command is confirmed perform the default action
            if self.is_confirmed:
                return func(self)
            # If the command is not confirmed, first try to run a pre_confirm
            # method if it is provided.
            should_confirm = True
            pre_confirm = getattr(self, 'pre_confirm', None)
            if pre_confirm:
                should_confirm = pre_confirm()

            # Add the command and a custom confirmation message to the set of
            # all commands requiring confirmation.
            if should_confirm:
                self.confirmation_set.add_command(
                    self.user_email,
                    self.get_command_text(),
                    self.get_confirmation_message())

            # After that get the response to the command.
            # The handle method becomes a no-op
            handle = self.handle
            self.handle = lambda: None  # noqa
            out = func(self)
            # handle returned to the normal method.
            self.handle = handle
            # Finally return the response to the command
            return out

        return wrapper

    klass.__call__ = decorate_call(klass.__call__)
    # Add place-holders for the two optional methods if the class itself did
    # not define them.
    if not getattr(klass, 'get_confirmation_message', None):
        klass.get_confirmation_message = lambda self: ''  # noqa
    if not getattr(klass, 'pre_confirm', None):
        klass.pre_confirm = pre_confirm_default

    return klass


class ConfirmCommand(Command):
    """
    The command used to confirm other commands which require confirmation.
    """
    META = {
        'description': """confirm <confirmation-key>
  Confirm a previously requested action, such as subscribing or
  unsubscribing from a package.""",
        'name': 'confirm',
        'position': 3,
    }

    REGEX_LIST = (
        r'\s+(?P<confirmation_key>\S+)$',
    )

    def __init__(self, confirmation_key):
        super(ConfirmCommand, self).__init__()
        self.confirmation_key = confirmation_key

    def get_command_text(self):
        return Command.get_command_text(self, self.confirmation_key)

    def handle(self):
        from distro_tracker.mail.control.commands import CommandFactory, \
            CommandProcessor

        command_confirmation = get_or_none(
            CommandConfirmation,
            confirmation_key=self.confirmation_key)
        if not command_confirmation:
            self.error('Confirmation failed: unknown key.')
            return
        lines = command_confirmation.commands.splitlines()
        processor = CommandProcessor(CommandFactory({}), confirmed=True)

        processor.process(lines)
        if processor.is_success():
            self.reply('Successfully confirmed commands:')
            self.reply(processor.get_output())
        else:
            self.error('No commands confirmed.')
            self.reply(processor.get_output())

        command_confirmation.delete()
