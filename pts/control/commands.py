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
Defines and implements all control commands.
"""
from __future__ import unicode_literals

from collections import OrderedDict

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import six

from pts.core.models import (
    Subscription, EmailUser, Package, BinaryPackage, Keyword)
from pts.control.models import CommandConfirmation

from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_or_none

import re
import sys
import inspect

from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN


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
        return self.compile_reply()

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
            match = re.match(pattern, line)
            if match:
                return match

    def compile_reply(self):
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

    @property
    def sent_mails(self):
        return self._sent_mails

    def _send_mail(self, subject, message, recipient_list):
        send_mail(
            subject=subject,
            message=message,
            from_email=PTS_CONTROL_EMAIL,
            recipient_list=recipient_list
        )
        self._sent_mails.extend(recipient_list)


class SendConfirmationCommandMixin(object):
    """
    A mixin which allows ``Command`` subclasses which use it to send
    confirmation emails
    """
    def _send_confirmation_mail(self, user_email, template, context):
        command_confirmation = CommandConfirmation.objects.create_for_command(
            command=self.get_command_text()
        )
        context.update({
            'command_confirmation': command_confirmation,
        })
        message = render_to_string(template, context)
        subject = 'CONFIRM ' + command_confirmation.confirmation_key

        self._send_mail(
            subject=subject,
            message=message,
            recipient_list=[user_email]
        )


class SubscribeCommand(Command, SendConfirmationCommandMixin):
    META = {
        'description': """subscribe <srcpackage> [<email>]
  Subscribes <email> to all messages regarding <srcpackage>. If
  <email> is not given, it subscribes the From address. If the
  <srcpackage> is not a valid source package, you'll get a warning.
  If it's a valid binary package, the mapping will automatically be
  done for you.""",
        'name': 'subscribe',
        'position': 1,
    }

    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, package, email):
        Command.__init__(self)
        self.package = package
        self.user_email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.package, self.user_email)

    def handle(self):
        if EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                   self.package):
            self.reply('{email} is already subscribed to {package}'.format(
                email=self.user_email,
                package=self.package))
            return
        else:
            Subscription.objects.create_for(
                email=self.user_email,
                package_name=self.package,
                active=False)

        if not Package.objects.exists_with_name(self.package):
            if BinaryPackage.objects.exists_with_name(self.package):
                binary_package = BinaryPackage.objects.get_by_name(self.package)
                self.warn('{package} is not a source package.'.format(
                    package=self.package))
                self.reply('{package} is the source package '
                           'for the {binary} binary package'.format(
                               package=binary_package.source_package.name,
                               binary=binary_package.name))
                self.package = binary_package.source_package.name
            else:
                self.reply(
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))
                return

        self._send_confirmation_mail(
            user_email=self.user_email,
            template='control/email-subscription-confirmation.txt',
            context={'package': self.package})
        self.reply('A confirmation mail has been sent to ' + self.user_email)


class UnsubscribeCommand(Command, SendConfirmationCommandMixin):
    META = {
        'description': """unsubscribe <srcpackage> [<email>]
  Unsubscribes <email> from <srcpackage>. Like the subscribe command,
  it will use the From address if <email> is not given.""",
        'name': 'unsubscribe',
        'position': 2,
    }

    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, package, email):
        Command.__init__(self)
        self.package = package
        self.user_email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.package, self.user_email)

    def handle(self):
        if not Package.objects.exists_with_name(self.package):
            if BinaryPackage.objects.exists_with_name(self.package):
                binary_package = BinaryPackage.objects.get_by_name(self.package)
                self.warn('{package} is not a source package.'.format(
                    package=self.package))
                self.reply('{package} is the source package '
                           'for the {binary} binary package'.format(
                               package=binary_package.source_package.name,
                               binary=binary_package.name))
                self.package = binary_package.source_package.name
            else:
                self.reply(
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))
                return
        if not EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                       self.package):
            self.reply(
                "{email} is not subscribed, you can't unsubscribe.".format(
                    email=self.user_email)
            )
            return

        self._send_confirmation_mail(
            user_email=self.user_email,
            template='control/email-unsubscribe-confirmation.txt',
            context={'package': self.package})
        self.reply('A confirmation mail has been sent to ' + self.user_email)


class ConfirmCommand(Command):
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
        Command.__init__(self)
        self.confirmation_key = confirmation_key

    def get_command_text(self):
        return Command.get_command_text(self, self.confirmation_key)

    def handle(self):
        command_confirmation = get_or_none(
            CommandConfirmation,
            confirmation_key=self.confirmation_key)
        if not command_confirmation:
            self.reply('Confirmation failed')
            return

        args = command_confirmation.command.split()
        command_confirmation.delete()
        if args[0].lower() == 'subscribe':
            return self._subscribe(package=args[1], user_email=args[2])
        elif args[0].lower() == 'unsubscribe':
            return self._unsubscribe(package=args[1], user_email=args[2])
        elif args[0].lower() == 'unsubscribeall':
            return self._unsubscribeall(user_email=args[1])

    def _subscribe(self, package, user_email):
        subscription = Subscription.objects.create_for(
            package_name=package,
            email=user_email,
            active=True)
        if subscription:
            self.reply(user_email + ' has been subscribed to ' + package)
        else:
            self.reply('Error subscribing ' + user_email + ' to ' + package)

    def _unsubscribe(self, package, user_email):
        success = Subscription.objects.unsubscribe(package, user_email)
        if success:
            self.reply('{user} has been unsubscribed from {package}'.format(
                user=user_email,
                package=package))
        else:
            self.reply('Error unsubscribing')

    def _unsubscribeall(self, user_email):
        user = get_or_none(EmailUser, email=user_email)
        if user is None:
            return
        packages = [
            subscription.package.name
            for subscription in user.subscription_set.all()
        ]
        user.subscription_set.all().delete()
        self.reply('All your subscriptions have been terminated:')
        self.list_reply(
            '{email} has been unsubscribed from {package}@{fqdn}'.format(
                email=user_email,
                package=package,
                fqdn=PTS_FQDN)
            for package in sorted(packages))


class WhichCommand(Command):
    META = {
        'description': """which [<email>]
  Tells you which packages <email> is subscribed to.""",
        'name': 'which',
        'position': 4,
    }

    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, email):
        Command.__init__(self)
        self.user_email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.user_email)

    def handle(self):
        user_subscriptions = Subscription.objects.get_for_email(
            self.user_email)
        if not user_subscriptions:
            self.reply('No subscriptions found')
            return
        self.list_reply(sub.package for sub in user_subscriptions)


class HelpCommand(Command):
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
        self.reply(render_to_string('control/help.txt', {
            'descriptions': [
                command.META.get('description', '')
                for command in UNIQUE_COMMANDS
            ]
        }))


class QuitCommand(Command):
    META = {
        'description': '''quit
  Stops processing commands''',
        'name': 'quit',
        'aliases': ['thanks'],
        'position': 6
    }

    REGEX_LIST = (
        r'$',
        r'^thanks$',
    )

    def handle(self):
        self.reply('Stopping processing here.')


class ViewDefaultKeywordsCommand(Command):
    """
    Implementation of the keyword command which handles displaying a list
    of the user's default keywords.
    """
    META = {
        'position': 10,
        'name': 'view-default-keywords',
        'aliases': ['keyword', 'tag', 'keywords', 'tags'],
        'description': '''keyword [<email>]
  Tells you the keywords you are accepting by default for packages
  with no specific keywords set.

  Each mail sent through the Package Tracking System is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, email):
        Command.__init__(self)
        self.email = email

    def handle(self):
        email_user, _ = EmailUser.objects.get_or_create(email=self.email)
        self.reply(
            "Here's the default list of accepted keywords for {email}:".format(
                email=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in email_user.default_keywords.all()))


class ViewPackageKeywordsCommand(Command):
    """
    Implementation of the keyword command version which handles listing
    all keywords associated to a package for a particular user.
    """
    META = {
        'position': 11,
        'name': 'view-package-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'description': '''keyword <srcpackage> [<email>]
  Tells you the keywords you are accepting for the given package.

  Each mail sent through the Package Tracking System is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, package, email):
        Command.__init__(self)
        self.package = package
        self.email = email

    def _get_subscription(self, email, package_name):
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            self.reply('User is not subscribed to any package')
            return

        package = get_or_none(Package, name=package_name)
        if not package:
            self.reply('Package {package} does not exist'.format(
                package=package_name))
            return

        subscription = get_or_none(Subscription,
                                   package=package,
                                   email_user=email_user)
        if not subscription:
            self.reply(
                'The user is not subscribed to the package {package}'.format(
                    package=package_name)
            )

        return subscription

    def handle(self):
        subscription = self._get_subscription(self.email, self.package)
        if not subscription:
            return

        self.reply(
            "Here's the list of accepted keywords associated to package")
        self.reply('{package} for {user}'.format(package=self.package,
                                                 user=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in subscription.keywords.all()))


class SetDefaultKeywordsCommand(Command):
    """
    Implementation of the keyword command which handles modifying a user's
    list of default keywords.
    """
    META = {
        'position': 12,
        'name': 'set-default-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'description': '''keyword [<email>] {+|-|=} <list of keywords>
  Accept (+) or refuse (-) mails associated to the given keyword(s).
  Define the list (=) of accepted keywords.
  These keywords are applied for subscriptions where no specific
  keyword set is given.'''
    }
    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+@\S+))?\s+(?P<operation>[-+=])\s+(?P<keywords>\S+(?:\s+\S+)*)$',
    )

    def __init__(self, email, operation, keywords):
        Command.__init__(self)
        self.email = email
        self.operation = operation
        self.keywords = keywords

        self.OPERATIONS = {
            '+': self._add_keywords,
            '-': self._remove_keywords,
            '=': self._set_keywords,
        }

    def _keyword_name_to_object(self, keyword_name):
        """
        Takes a keyword name and returns a keyword object with the given name
        if it exists.
        """
        keyword = get_or_none(Keyword, name=keyword_name)
        if not keyword:
            self.warn('{keyword} is not a valid keyword'.format(
                keyword=keyword_name))
        return keyword

    def handle(self):
        keywords = re.split('[,\s]+', self.keywords)

        email_user, _ = EmailUser.objects.get_or_create(email=self.email)
        self.OPERATIONS[self.operation](keywords, email_user.default_keywords)

        self.reply(
            "Here's the new default list of accepted keywords for "
            "{user} :".format(user=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in email_user.default_keywords.all()
        ))

    def _add_keywords(self, keywords, manager):
        """
        Adds the keywords given in the iterable ``keywords`` to the ``manager``
        """
        for keyword_name in keywords:
            keyword = self._keyword_name_to_object(keyword_name)
            if keyword:
                manager.add(keyword)

    def _remove_keywords(self, keywords, manager):
        """
        Removes the keywords given in the iterable ``keywords`` from the
        ``manager``.
        """
        for keyword_name in keywords:
            keyword = self._keyword_name_to_object(keyword_name)
            if keyword:
                manager.remove(keyword)

    def _set_keywords(self, keywords, manager):
        """
        Sets the keywords given in the iterable ``keywords`` to the ``manager``
        so that they are the only keywords it contains.
        """
        manager.clear()
        self._add_keywords(keywords, manager)


class SetPackageKeywordsCommand(Command):
    """
    Implementation of the keyword command version which modifies subscription
    specific keywords.
    """
    META = {
        'name': 'set-package-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'description': (
            '''keyword <srcpackage> [<email>] {+|-|=} <list of keywords>
  Accept (+) or refuse (-) mails associated to the given keyword(s) for the
  given package..
  Define the list (=) of accepted keywords.
  These keywords take precendence to default keywords.''')
    }
    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?\s+(?P<operation>[-+=])\s+(?P<keywords>\S+(?:\s+\S+)*)$',
    )

    def _keyword_name_to_object(self, keyword_name):
        """
        Takes a keyword name and returns a keyword object with the given name
        if it exists.
        """
        keyword = get_or_none(Keyword, name=keyword_name)
        if not keyword:
            self.warn('{keyword} is not a valid keyword'.format(
                keyword=keyword_name))
        return keyword

    def __init__(self, package, email, operation, keywords):
        Command.__init__(self)
        self.package = package
        self.email = email
        self.operation = operation
        self.keywords = keywords
        self.OPERATIONS = {
            '+': self._add_keywords,
            '-': self._remove_keywords,
            '=': self._set_keywords,
        }

    def _add_keywords(self, keywords, manager):
        """
        Adds the keywords given in the iterable ``keywords`` to the ``manager``
        """
        for keyword_name in keywords:
            keyword = self._keyword_name_to_object(keyword_name)
            if keyword:
                manager.add(keyword)

    def _remove_keywords(self, keywords, manager):
        """
        Removes the keywords given in the iterable ``keywords`` from the
        ``manager``.
        """
        for keyword_name in keywords:
            keyword = self._keyword_name_to_object(keyword_name)
            if keyword:
                manager.remove(keyword)

    def _set_keywords(self, keywords, manager):
        """
        Sets the keywords given in the iterable ``keywords`` to the ``manager``
        so that they are the only keywords it contains.
        """
        manager.clear()
        self._add_keywords(keywords, manager)

    def _get_subscription(self, email, package_name):
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            self.reply('User is not subscribed to any package')
            return

        package = get_or_none(Package, name=package_name)
        if not package:
            self.reply('Package {package} does not exist'.format(
                package=package_name))
            return

        subscription = get_or_none(Subscription,
                                   package=package,
                                   email_user=email_user)
        if not subscription:
            self.reply(
                'The user is not subscribed to the package {package}'.format(
                    package=package_name)
            )

        return subscription

    def handle(self):
        """
        Actual implementation of the keyword command version which handles
        subscription specific keywords.
        """
        keywords = re.split('[,\s]+', self.keywords)

        subscription = self._get_subscription(self.email, self.package)
        if not subscription:
            return

        self.OPERATIONS[self.operation](keywords, subscription.keywords)
        self.reply(
            "Here's the new list of accepted keywords associated to package")
        self.reply('{package} for {user} :'.format(package=self.package,
                                                   user=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in subscription.keywords.all()))


class UnsubscribeallCommand(Command, SendConfirmationCommandMixin):
    META = {
        'description': '''unsubscribeall [<email>]
  Cancel all subscriptions of <email>. Like the subscribe command,
  it will use the From address if <email> is not given.''',
        'name': 'unsubscribeall',
        'position': 8,
    }

    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, email):
        Command.__init__(self)
        self.email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.email)

    def handle(self):
        user = get_or_none(EmailUser, email=self.email)
        if not user or user.subscription_set.count() == 0:
            self.reply('User {email} is not subscribed to any packages'.format(
                email=self.email))
            return

        self._send_confirmation_mail(
            user_email=self.email,
            template='control/email-unsubscribeall-confirmation.txt',
            context={})
        self.reply('A confirmation mail has been sent to {email}'.format(
            email=self.email))


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

"""
Export only the relevant Command classes, the factory and list of commands.
"""
__all__ = (tuple(
    klass.__name__
    for klass in UNIQUE_COMMANDS) + ('CommandFactory', 'UNIQUE_COMMANDS'))
