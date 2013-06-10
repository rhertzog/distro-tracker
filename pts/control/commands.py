"""
Defines and implements all control commands.
"""
from __future__ import unicode_literals

from django.core.mail import send_mail

from control.models import CommandConfirmation


class Command(object):
    """
    Base class for commands. Instances of this class can be used for NOP
    commands.
    """
    def __init__(self, *args):
        pass

    def __call__(self):
        pass

    def is_valid(self):
        return True


class SubscribeCommand(Command):
    def __init__(self, message, *args):
        self.package = None
        self.user_email = None
        if len(args) < 1:
            # Invalid command
            pass
        elif len(args) < 2:
            # Subscriber email not given
            self.package = args[0]
            self.user_email = message.get('From')
        else:
            # Superfluous arguments are ignored.
            self.package = args[0]
            self.user_email = args[1]

    def is_valid(self):
        return self.package and self.user_email

    def __call__(self):
        command_confirmation = CommandConfirmation.objects.create_for_command(
            command='subscribe ' + self.package + ' ' + self.user_email,
        )
        confirm_text = 'CONFIRM ' + command_confirmation.confirmation_key
        send_mail(
            subject=confirm_text,
            message=confirm_text,
            from_email='Debian Package Tracking System <pts@qa.debian.org>',
            recipient_list=[self.user_email]
        )
        return 'A confirmation mail has been sent to ' + self.user_email

    description = """subscribe <srcpackage> [<email>]
  Subscribes <email> to all messages regarding <srcpackage>. If
  <email> is not given, it subscribes the From address. If the
  <srcpackage> is not a valid source package, you'll get a warning.
  If it's a valid binary package, the mapping will automatically be
  done for you."""


class ConfirmCommand(Command):
    def __init__(self, message, *args):
        self.confirmation_key = None
        if len(args) >= 1:
            self.confirmation_key = args[0]

    def is_valid(self):
        return self.confirmation_key is not None

    def __call__(self):
        command_confirmation = CommandConfirmation.objects.get(
            confirmation_key=self.confirmation_key)

        args = command_confirmation.command.split()
        if args[0].lower() == 'subscribe':
            return self._subscribe(package=args[1], user_email=args[2])

    def _subscribe(self, package, user_email):
        return user_email + ' has been subscribed to ' + package


class HelpCommand(Command):
    """
    Not yet implemented.
    """
    description = 'Shows all available commands'


class QuitCommand(Command):
    description = 'Stops processing commands'


ALL_COMMANDS = {
    'help': HelpCommand,
    'thanks': QuitCommand,
    'quit': QuitCommand,
    'subscribe': SubscribeCommand,
    'confirm': ConfirmCommand,
}


class CommandFactory(object):
    """
    Creates instances of Command classes based on the request message.
    """
    def __init__(self, msg):
        self.msg = msg

    def get_command_function(self, *args):
        """
        Returns a function which executes the functionality of the command
        which corresponds to the given arguments.
        """
        cmd = args[0].lower()
        args = args[1:]
        if cmd.startswith('#'):
            return Command()
        if cmd in ALL_COMMANDS:
            # Command exists
            command_function = ALL_COMMANDS[cmd](self.msg, *args)
            if command_function.is_valid():
                # All required parameters passed to the command
                return command_function
