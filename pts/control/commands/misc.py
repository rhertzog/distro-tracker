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

from pts.core.utils import get_or_none
from pts.core.models import Subscription, EmailUser, Package, BinaryPackage
from pts.control.models import CommandConfirmation
from pts.control.commands.base import Command, SendConfirmationCommandMixin

from django.conf import settings
PTS_FQDN = settings.PTS_FQDN


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
        super(SubscribeCommand, self).__init__()
        self.package = package
        self.user_email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.package, self.user_email)

    def handle(self):
        if EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                   self.package):
            self.warn('{email} is already subscribed to {package}'.format(
                email=self.user_email,
                package=self.package))
            return

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
                self.warn(
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))
                return

        self.send_confirmation_mail(
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
        super(UnsubscribeCommand, self).__init__()
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
                self.warn(
                    '{package} is neither a source package '
                    'nor a binary package.'.format(package=self.package))
                return
        if not EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                       self.package):
            self.error(
                "{email} is not subscribed, you can't unsubscribe.".format(
                    email=self.user_email)
            )
            return

        self.send_confirmation_mail(
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
        super(ConfirmCommand, self).__init__()
        self.confirmation_key = confirmation_key

    def get_command_text(self):
        return Command.get_command_text(self, self.confirmation_key)

    def handle(self):
        command_confirmation = get_or_none(
            CommandConfirmation,
            confirmation_key=self.confirmation_key)
        if not command_confirmation:
            self.error('Confirmation failed')
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
            self.error('Could not subscribe ' + user_email + ' to ' + package)

    def _unsubscribe(self, package, user_email):
        success = Subscription.objects.unsubscribe(package, user_email)
        if success:
            self.reply('{user} has been unsubscribed from {package}'.format(
                user=user_email,
                package=package))
        else:
            self.error('Could not unsubscribe {email} from {package}'.format(
                email=user_email,
                package=package))

    def _unsubscribeall(self, user_email):
        user = get_or_none(EmailUser, email=user_email)
        if user is None:
            return
        packages = [
            subscription.package.name
            for subscription in user.subscription_set.all()
        ]
        user.unsubscribe_all()
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
        super(WhichCommand, self).__init__()
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


class WhoCommand(Command):
    META = {
        'description': """who <package>
  Outputs all the subscriber emails for the given package in
  an obfuscated form.""",
        'name': 'who',
        'position': 5,
    }

    REGEX_LIST = (
        r'(?:\s+(?P<package>\S+))$',
    )

    def __init__(self, package):
        super(WhoCommand, self).__init__()
        self.package_name = package

    def handle(self):
        package = get_or_none(Package, name=self.package_name)
        if not package:
            self.error('Package {package} does not exist'.format(
                package=self.package_name))
            return

        if package.subscriptions.count() == 0:
            self.reply(
                'Package {package} does not have any subscribers'.format(
                    package=package.name))
            return

        self.reply(
            "Here's the list of subscribers to package {package}:".format(
                package=self.package_name))
        self.list_reply(
            self.obfuscate(subscriber)
            for subscriber in package.subscriptions.all()
        )

    def obfuscate(self, email_user):
        """
        Helper method which obfuscates the given email.
        """
        email = email_user.email
        local_part, domain = email.rsplit('@', 1)
        domain_parts = domain.split('.')
        obfuscated_domain = '.'.join(
            part[0] + '.' * (len(part) - 1)
            for part in domain_parts
        )
        return local_part + '@' + obfuscated_domain


class QuitCommand(Command):
    META = {
        'description': '''quit
  Stops processing commands''',
        'name': 'quit',
        'aliases': ['thanks', '--'],
        'position': 6
    }

    REGEX_LIST = (
        r'$',
    )

    def handle(self):
        self.reply('Stopping processing here.')


class UnsubscribeallCommand(Command, SendConfirmationCommandMixin):
    META = {
        'description': '''unsubscribeall [<email>]
  Cancel all subscriptions of <email>. Like the subscribe command,
  it will use the From address if <email> is not given.''',
        'name': 'unsubscribeall',
        'position': 7,
    }

    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, email):
        super(UnsubscribeallCommand, self).__init__()
        self.email = email

    def get_command_text(self):
        return Command.get_command_text(self, self.email)

    def handle(self):
        user = get_or_none(EmailUser, email=self.email)
        if not user or user.subscription_set.count() == 0:
            self.warn('User {email} is not subscribed to any packages'.format(
                email=self.email))
            return

        self.send_confirmation_mail(
            user_email=self.email,
            template='control/email-unsubscribeall-confirmation.txt',
            context={})

        self.reply('A confirmation mail has been sent to {email}'.format(
            email=self.email))
