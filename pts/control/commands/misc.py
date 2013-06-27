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
from pts.core.utils import pts_render_to_string
from pts.core.models import Subscription, EmailUser, Package, BinaryPackage
from pts.control.commands.confirmation import needs_confirmation
from pts.control.commands.base import Command

from django.conf import settings
PTS_FQDN = settings.PTS_FQDN


@needs_confirmation
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

    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, package, email):
        super(SubscribeCommand, self).__init__()
        self.package = package
        self.user_email = email

    def get_command_text(self):
        return super(SubscribeCommand, self).get_command_text(
            self.package, self.user_email)

    def pre_confirm(self):
        if EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                   self.package):
            self.warn('{email} is already subscribed to {package}'.format(
                email=self.user_email,
                package=self.package))
            return False

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
                return False

        self.reply('A confirmation mail has been sent to ' + self.user_email)
        return True

    def handle(self):
        subscription = Subscription.objects.create_for(
            package_name=self.package,
            email=self.user_email,
            active=True)
        if subscription:
            self.reply('{email} has been subscribed to {package}'.format(
                email=self.user_email, package=self.package))
        else:
            self.error('Could not subscribe {email} to {package}'.format(
                email=self.user_email, package=self.package))

    def get_confirmation_message(self):
        return pts_render_to_string(
            'control/email-subscription-confirmation.txt', {
                'package': self.package,
            }
        )


@needs_confirmation
class UnsubscribeCommand(Command):
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
        return super(UnsubscribeCommand, self).get_command_text(
            self.package, self.user_email)

    def pre_confirm(self):
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
                return False
        if not EmailUser.objects.is_user_subscribed_to(self.user_email,
                                                       self.package):
            self.error(
                "{email} is not subscribed, you can't unsubscribe.".format(
                    email=self.user_email)
            )
            return False

        self.reply('A confirmation mail has been sent to ' + self.user_email)
        return True

    def handle(self):
        success = Subscription.objects.unsubscribe(self.package,
                                                   self.user_email)
        if success:
            self.reply('{user} has been unsubscribed from {package}'.format(
                user=self.user_email,
                package=self.package))
        else:
            self.error('Could not unsubscribe {email} from {package}'.format(
                email=self.user_email,
                package=self.package))

    def get_confirmation_message(self):
        return pts_render_to_string(
            'control/email-unsubscribe-confirmation.txt', {
                'package': self.package,
            }
        )


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
        return super(WhichCommand, self).get_command_text(self.user_email)

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

    def get_command_text(self):
        return super(WhoCommand, self).get_command_text(self.package_name)

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


@needs_confirmation
class UnsubscribeallCommand(Command):
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
        self.user_email = email

    def get_command_text(self):
        return super(UnsubscribeallCommand, self).get_command_text(
            self.user_email)

    def pre_confirm(self):
        user = get_or_none(EmailUser, email=self.user_email)
        if not user or user.subscription_set.count() == 0:
            self.warn('User {email} is not subscribed to any packages'.format(
                email=self.user_email))
            return False

        self.reply('A confirmation mail has been sent to {email}'.format(
            email=self.user_email))
        return True

    def handle(self):
        user = get_or_none(EmailUser, email=self.user_email)
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
                email=self.user_email,
                package=package,
                fqdn=PTS_FQDN)
            for package in sorted(packages))

    def get_confirmation_message(self):
        return pts_render_to_string(
            'control/email-unsubscribeall-confirmation.txt'
        )
