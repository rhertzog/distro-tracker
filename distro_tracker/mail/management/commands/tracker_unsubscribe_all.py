# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements the command which removes all subscriptions for a given email.
"""
from __future__ import unicode_literals
from django.core.management.base import BaseCommand, CommandError

from distro_tracker.core.models import UserEmail, EmailSettings
from distro_tracker.core.utils import get_or_none


class Command(BaseCommand):
    """
    A Django management command which removes all subscriptions for the given
    emails.
    """
    help = "Removes all package subscriptions for the given emails."

    def add_arguments(self, parser):
        parser.add_argument('emails', nargs='+')

    def handle(self, *args, **kwargs):
        if len(kwargs['emails']) == 0:
            raise CommandError('At least one email must be given.')
        verbosity = int(kwargs.get('verbosity', 1))
        for email in kwargs['emails']:
            out = self._remove_subscriptions(email)
            if verbosity >= 1:
                self.stdout.write(out)

    def _remove_subscriptions(self, email):
        """
        Removes subscriptions for the given email.

        :param email: Email for which to remove all subscriptions.
        :type email: string

        :returns: A message explaining the result of the operation.
        :rtype: string
        """
        user = get_or_none(UserEmail, email__iexact=email)
        if not user:
            return ('Email {email} is not subscribed to any packages. '
                    'Bad email?'.format(email=email))
        email_settings, _ = EmailSettings.objects.get_or_create(user_email=user)
        if email_settings.packagename_set.count() == 0:
            return 'Email {email} is not subscribed to any packages.'.format(
                email=email)
        out = [
            'Unsubscribing {email} from {package}'.format(
                email=email, package=package)
            for package in email_settings.packagename_set.all()
        ]
        email_settings.unsubscribe_all()
        return '\n'.join(out)
