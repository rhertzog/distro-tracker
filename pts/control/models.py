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
Defines models specific for the :py:mod:`pts.control` app.
"""
from __future__ import unicode_literals
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.utils import IntegrityError
from django.utils.encoding import python_2_unicode_compatible

import hashlib
import string
import random

PTS_CONFIRMATION_EXPIRATION_DAYS = settings.PTS_CONFIRMATION_EXPIRATION_DAYS


class CommandConfirmationException(Exception):
    """
    An exception which is raised when the :py:class:`CommandConfirmationManager`
    is unable to generate a unique key for the given command.
    """
    pass


class CommandConfirmationManager(models.Manager):
    """
    A custom manager for the :py:class:`CommandConfirmation` model.
    """
    def generate_key(self, command):
        """
        Generates a random key for the given command.
        :param command: A string representation of a command.
        """
        chars = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(chars) for _ in range(16))
        random_string = random_string.encode('ascii')
        salt = hashlib.sha1(random_string).hexdigest()
        hash_input = (salt + command).encode('ascii')
        return hashlib.sha1(hash_input).hexdigest()

    def create_for_commands(self, commands):
        """
        Creates a :py:class:`CommandConfirmation` object for the given commands.

        :param commands: An iterable of commands for which a confirmation is requested.
        :raises pts.control.models.CommandConfirmationException: If it is unable to generate a unique key.
        """
        commands = '\n'.join(commands)
        MAX_TRIES = 10
        errors = 0
        while errors < MAX_TRIES:
            confirmation_key = self.generate_key(commands)
            try:
                return self.create(
                    commands=commands, confirmation_key=confirmation_key)
            except IntegrityError:
                errors += 1

        raise CommandConfirmationException(
            'Unable to generate a confirmation key for {command}'.format(
                commands=commands))

    def clean_up_expired(self):
        """
        Removes all expired confirmation keys.
        """
        for confirmation in self.all():
            if confirmation.is_expired():
                confirmation.delete()

    def get(self, *args, **kwargs):
        """
        Overrides the default :py:class:`django.db.models.Manager` method so
        that expired :py:class:`CommandConfirmation` instances are never
        returned.

        :rtype: :py:class:`CommandConfirmation` or ``None``
        """
        instance = models.Manager.get(self, *args, **kwargs)
        return instance if not instance.is_expired() else None


@python_2_unicode_compatible
class CommandConfirmation(models.Model):
    """
    A model representing pending confirmations for email interface commands.
    """
    commands = models.TextField()
    confirmation_key = models.CharField(max_length=40, unique=True)
    date_created = models.DateTimeField(auto_now_add=True)

    objects = CommandConfirmationManager()

    def __str__(self):
        return self.commands

    def is_expired(self):
        """
        :returns True: if the confirmation key has expired
        :returns False: if the confirmation key is still valid
        """
        delta = timezone.now() - self.date_created
        return delta.days >= PTS_CONFIRMATION_EXPIRATION_DAYS

    @property
    def command_list(self):
        """
        :return: A list of strings representing commands which are confirmed
                  by this instance.
        """
        return self.commands.splitlines()
