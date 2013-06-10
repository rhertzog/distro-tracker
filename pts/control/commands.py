"""
Defines and implements all control commands.
"""
from __future__ import unicode_literals


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
        pass

    description = """subscribe <srcpackage> [<email>]
  Subscribes <email> to all messages regarding <srcpackage>. If
  <email> is not given, it subscribes the From address. If the
  <srcpackage> is not a valid source package, you'll get a warning.
  If it's a valid binary package, the mapping will automatically be
  done for you."""


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
        cmd = args[0]
        args = args[1:]
        if cmd.startswith('#'):
            return Command()
        if cmd in ALL_COMMANDS:
            # Command exists
            command_function = ALL_COMMANDS[cmd](self.msg, *args)
            if command_function.is_valid():
                # All required parameters passed to the command
                return command_function
