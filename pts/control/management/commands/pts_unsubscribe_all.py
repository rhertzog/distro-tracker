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
from django.core.management.base import BaseCommand, CommandError

from pts.core.models import EmailUser
from pts.core.utils import get_or_none


class Command(BaseCommand):
    """
    A Django management command which removes all subscriptions for the given
    emails.
    """
    args = 'email [email ...]'

    help = "Removes all package subscriptions for the given emails."

    def handle(self, *args, **kwargs):
        if len(args) == 0:
            raise CommandError('At least one email must be given.')
        verbosity = int(kwargs.get('verbosity', 1))
        for email in args:
            out = self._remove_subscriptions(email)
            if verbosity >= 1:
                self.stdout.write(out)

    def _remove_subscriptions(self, email):
        user = get_or_none(EmailUser, email=email)
        if not user:
            return ('Email {email} is not subscribed to any packages. '
                    'Bad email?'.format(email=email))
        if user.package_set.count() == 0:
            return 'Email {email} is not subscribed to any packages.'.format(
                email=email)
        out = [
            'Unsubscribing {email} from {package}'.format(
                email=email, package=package)
            for package in user.package_set.all()
        ]
        user.unsubscribe_all()
        return '\n'.join(out)
