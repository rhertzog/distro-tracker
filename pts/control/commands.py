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


class Command(object):
    """
    Base class for commands. Instances of this class can be used for NOP
    commands.
    """
    META = {}

    def __init__(self, *args):
        self._sent_mails = []

    def __call__(self):
        pass

    def is_valid(self):
        return True

    def get_command_text(self):
        """
        Returns a string representation of the command.
        """
        return '#'

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


class SubscribeCommand(Command):
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

    def __init__(self, message, *args):
        Command.__init__(self)
        self.package = None
        self.user_email = None
        if len(args) < 1:
            # Invalid command
            pass
        elif len(args) < 2:
            # Subscriber email not given
            self.package = args[0]
            self.user_email = extract_email_address_from_header(
                message.get('From'))
        else:
            # Superfluous arguments are ignored.
            self.package = args[0]
            self.user_email = args[1]

    def is_valid(self):
        return self.package and self.user_email

    def get_command_text(self):
        return 'subscribe {package} {email}'.format(
            package=self.package,
            email=self.user_email).lower()

    def _send_confirmation_mail(self):
        command_confirmation = CommandConfirmation.objects.create_for_command(
            command=self.get_command_text()
        )
        message = render_to_string(
            'control/email-subscription-confirmation.txt', {
                'package': self.package,
                'command_confirmation': command_confirmation,
            }
        )
        subject = 'CONFIRM ' + command_confirmation.confirmation_key

        self._send_mail(
            subject=subject,
            message=message,
            recipient_list=[self.user_email]
        )

    def __call__(self):
        if EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                   self.package):
            return '{email} is already subscribed to {package}'.format(
                email=self.user_email,
                package=self.package)
        else:
            Subscription.objects.create_for(
                email=self.user_email,
                package_name=self.package,
                active=False)

        out = []
        if not Package.objects.exists_with_name(self.package):
            if BinaryPackage.objects.exists_with_name(self.package):
                binary_package = BinaryPackage.objects.get_by_name(self.package)
                out.append('Warning: {package} is not a source package.'.format(
                    package=self.package))
                out.append('{package} is the source package '
                           'for the {binary} binary package'.format(
                               package=binary_package.source_package.name,
                               binary=binary_package.name))
                self.package = binary_package.source_package.name
            else:
                return (
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))

        self._send_confirmation_mail()
        out.append('A confirmation mail has been sent to ' + self.user_email)
        return '\n'.join(out)


class UnsubscribeCommand(Command):
    META = {
        'description': """unsubscribe <srcpackage> [<email>]
  Unsubscribes <email> from <srcpackage>. Like the subscribe command,
  it will use the From address if <email> is not given.""",
        'name': 'unsubscribe',
        'position': 2,
    }

    def __init__(self, message, *args):
        Command.__init__(self)
        self.package = None
        self.user_email = None
        if len(args) < 1:
            # Invalid command
            pass
        elif len(args) < 2:
            # Subscriber email not given
            self.package = args[0]
            self.user_email = extract_email_address_from_header(
                message.get('From'))
        else:
            # Superfluous arguments are ignored.
            self.package = args[0]
            self.user_email = args[1]

    def is_valid(self):
        return self.package and self.user_email

    def get_command_text(self):
        return 'unsubscribe {package} {email}'.format(
            package=self.package,
            email=self.user_email).lower()

    def _send_confirmation_mail(self):
        command_confirmation = CommandConfirmation.objects.create_for_command(
            command=self.get_command_text()
        )
        message = render_to_string(
            'control/email-unsubscribe-confirmation.txt', {
                'package': self.package,
                'command_confirmation': command_confirmation,
            }
        )
        subject = 'CONFIRM ' + command_confirmation.confirmation_key

        self._send_mail(
            subject=subject,
            message=message,
            recipient_list=[self.user_email]
        )

    def __call__(self):
        out = []
        if not Package.objects.exists_with_name(self.package):
            if BinaryPackage.objects.exists_with_name(self.package):
                binary_package = BinaryPackage.objects.get_by_name(self.package)
                out.append('Warning: {package} is not a source package.'.format(
                    package=self.package))
                out.append('{package} is the source package '
                           'for the {binary} binary package'.format(
                               package=binary_package.source_package.name,
                               binary=binary_package.name))
                self.package = binary_package.source_package.name
            else:
                return (
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))
        if not EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                       self.package):
            return (
                "{email} is not subscribed, you can't unsubscribe.".format(
                    email=self.user_email)
            )

        self._send_confirmation_mail()
        out.append('A confirmation mail has been sent to ' + self.user_email)
        return '\n'.join(out)


class ConfirmCommand(Command):
    META = {
        'description': """unsubscribe <srcpackage> [<email>]
  Unsubscribes <email> from <srcpackage>. Like the subscribe command,
  it will use the From address if <email> is not given.""",
        'name': 'confirm',
        'position': 3,
    }

    def __init__(self, message, *args):
        Command.__init__(self)
        self.confirmation_key = None
        if len(args) >= 1:
            self.confirmation_key = args[0]

    def is_valid(self):
        return self.confirmation_key is not None

    def get_command_text(self):
        return 'confirm {key}'.format(key=self.confirmation_key)

    def __call__(self):
        command_confirmation = get_or_none(
            CommandConfirmation,
            confirmation_key=self.confirmation_key)
        if not command_confirmation:
            return 'Confirmation failed'

        args = command_confirmation.command.split()
        command_confirmation.delete()
        if args[0].lower() == 'subscribe':
            return self._subscribe(package=args[1], user_email=args[2])
        elif args[0].lower() == 'unsubscribe':
            return self._unsubscribe(package=args[1], user_email=args[2])

    def _subscribe(self, package, user_email):
        subscription = Subscription.objects.create_for(
            package_name=package,
            email=user_email,
            active=True)
        if subscription:
            return user_email + ' has been subscribed to ' + package
        else:
            return 'Error subscribing ' + user_email + ' to ' + package

    def _unsubscribe(self, package, user_email):
        success = Subscription.objects.unsubscribe(package, user_email)
        if success:
            return '{user} has been unsubscribed from {package}'.format(
                user=user_email,
                package=package)
        else:
            return 'Error unsubscribing'


class WhichCommand(Command):
    META = {
        'description': """which [<email>]
  Tells you which packages <email> is subscribed to.""",
        'name': 'which',
        'position': 4,
    }

    def __init__(self, message, *args):
        Command.__init__(self)
        self.user_email = None
        if len(args) >= 1:
            self.user_email = args[0]
        else:
            self.user_email = extract_email_address_from_header(
                message.get('From'))

    def get_command_text(self):
        return 'which ' + self.user_email.lower()

    def __call__(self):
        user_subscriptions = Subscription.objects.get_for_email(
            self.user_email)
        if not user_subscriptions:
            return 'No subscriptions found'
        return '\n'.join((
            '* {package_name}'.format(package_name=sub.package.name)
            for sub in user_subscriptions
        ))


class HelpCommand(Command):
    """
    Not yet implemented.
    """
    META = {
        'description': '''help
  Shows all available commands''',
        'name': 'help',
        'position': 5,
    }

    def get_command_text(self):
        return 'help'

    def __call__(self):
        return render_to_string('control/help.txt', {
            'descriptions': [
                command.META.get('description', '')
                for command in UNIQUE_COMMANDS
            ]
        })


class QuitCommand(Command):
    META = {
        'description': '''quit
  Stops processing commands''',
        'name': 'quit',
        'aliases': ['thanks'],
        'position': 6
    }

    def get_command_text(self):
        return 'quit'


class KeywordCommand(Command):
    META = {
        'description': '''desc''',
        'name': 'keyword',
        'aliases': ['tag'],
    }

    REGEX_LIST = (
        (re.compile(r'^(\S+@\S+)?$'),
         'subscription_default_keywords_list'),
        (re.compile(r'^(\S+@\S+\s+)?([-+=])\s+(\S+(?:\s+\S+)*)$'),
         'subscription_default_keywords'),
        (re.compile(
            r'^(\S+)(?:\s+(\S+@\S+))?\s+([-+=])\s+(\S+(?:\s+\S+)*)$'),
         'subscription_keywords'),
        (re.compile(r'^(\S+)(?:\s+(\S+@\S+))?$'),
         'subscription_keywords_list'),
    )

    def __init__(self, message, *args):
        Command.__init__(self)
        self.line = ' '.join(args).lower()
        self.match = None
        self.email = extract_email_address_from_header(message.get('From'))
        for regex, name in self.REGEX_LIST:
            match = regex.match(self.line)
            if match:
                self.method = getattr(self, '_' + name)
                self.match = match
                break

        self.OPERATIONS = {
            '+': self._add_keywords,
            '-': self._remove_keywords,
            '=': self._set_keywords,
        }

    def is_valid(self):
        return self.match is not None

    def get_command_text(self):
        return self.line

    def __call__(self):
        # This method only delegates to the implementation of one of the
        # versions of the keyword command.
        if not self.is_valid():
            return 'Invalid command'
        self.out = []
        self.method(self.match)
        return '\n'.join(self.out)

    def _get_subscription(self, email, package_name):
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            self.out.append('User is not subscribed to any package')
            return

        package = get_or_none(Package, name=package_name)
        if not package:
            self.out.append('Package {package} does not exist'.format(
                package=package_name))
            return

        subscription = get_or_none(Subscription,
                                   package=package,
                                   email_user=email_user)
        if not subscription:
            self.out.append(
                'The user is not subscribed to the package {package}'.format(
                    package=package_name)
            )

        return subscription

    def _include_keywords(self, keywords):
        """
        Include the keywords found in the given iterable to the output of the
        command.
        """
        self.out.extend(sorted(
            '* ' + keyword.name
            for keyword in keywords
        ))

    def _subscription_default_keywords_list(self, match):
        """
        Implementation of the keyword command which handles displaying a list
        of the user's default keywords.
        """
        email = match.group(1)

        if not email:
            email = self.email
        email = email.strip()

        email_user, _ = EmailUser.objects.get_or_create(email=email)
        self.out.append(
            "Here's the default list of accepted keywords for {email}:".format(
                email=email))
        self._include_keywords(email_user.default_keywords.all())

    def _subscription_default_keywords(self, match):
        """
        Implementation of the keyword command which handles modifying a user's
        list of default keywords.
        """
        email, operation, keywords = match.groups()
        if not email:
            email = self.email
        email = email.strip()

        keywords = re.split('[,\s]+', keywords)

        email_user, _ = EmailUser.objects.get_or_create(email=email)
        self.OPERATIONS[operation](keywords, email_user.default_keywords)

        self.out.append(
            "Here's the new default list of accepted keywords for "
            "{user} :".format(user=email))
        self._include_keywords(email_user.default_keywords.all())

    def _subscription_keywords_list(self, match):
        """
        Implementation of the keyword command version which handles listing
        all keywords associated to a package for a particular user.
        """
        package_name, email = match.groups()
        if not email:
            email = self.email

        subscription = self._get_subscription(email, package_name)
        if not subscription:
            return

        self.out.append(
            "Here's the list of accepted keywords associated to package")
        self.out.append('{package} for {user}'.format(package=package_name,
                                                      user=email))
        self._include_keywords(subscription.keywords.all())

    def _subscription_keywords(self, match):
        """
        Actual implementation of the keyword command version which handles
        subscription specific keywords.
        """
        package_name, email, operation, keywords = match.groups()
        if not email:
            email = self.email
        keywords = re.split('[,\s]+', keywords)

        subscription = self._get_subscription(email, package_name)
        if not subscription:
            return

        self.OPERATIONS[operation](keywords, subscription.keywords)
        self.out.append(
            "Here's the new list of accepted keywords associated to package")
        self.out.append('{package} for {user} :'.format(package=package_name,
                                                        user=email))
        self._include_keywords(subscription.keywords.all())

    def _keyword_name_to_object(self, keyword_name):
        """
        Takes a keyword name and returns a keyword object with the given name
        if it exists.
        """
        keyword = get_or_none(Keyword, name=keyword_name)
        if not keyword:
            self.out.append('Warning: {keyword} is not a valid keyword'.format(
                keyword=keyword_name))
        return keyword

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


UNIQUE_COMMANDS = sorted(
    (klass
     for _, klass in inspect.getmembers(sys.modules[__name__], inspect.isclass)
     if klass != Command and issubclass(klass, Command)),
    key=lambda cmd: cmd.META.get('position', float('inf'))
)

ALL_COMMANDS = OrderedDict((
    (alias, cmd)
    for cmd in UNIQUE_COMMANDS
    for alias in [cmd.META['name']] + cmd.META.get('aliases', list())
))


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
