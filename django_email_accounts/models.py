# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
from __future__ import unicode_literals
from django.db import models
from django.conf import settings
from django.utils.encoding import python_2_unicode_compatible
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db.utils import IntegrityError
from django.utils import timezone

import string
import random
import hashlib


class ConfirmationException(Exception):
    """
    An exception which is raised when the :py:class:`ConfirmationManager`
    is unable to generate a unique key for a given identifier.
    """
    pass


class ConfirmationManager(models.Manager):
    """
    A custom manager for the :py:class:`Confirmation` model.
    """
    def generate_key(self, identifier):
        """
        Generates a random key for the given identifier.
        :param identifier: A string representation of an identifier for the
            confirmation instance.
        """
        chars = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(chars) for _ in range(16))
        random_string = random_string.encode('ascii')
        salt = hashlib.sha1(random_string).hexdigest()
        hash_input = (salt + identifier).encode('ascii')
        return hashlib.sha1(hash_input).hexdigest()

    def create_confirmation(self, identifier='', **kwargs):
        """
        Creates a :py:class:`Confirmation` object with the given identifier and
        all the given keyword arguments passed.

        :param identifier: A string representation of an identifier for the
            confirmation instance.
        :raises pts.mail.models.ConfirmationException: If it is unable to
            generate a unique key.
        """
        MAX_TRIES = 10
        errors = 0
        while errors < MAX_TRIES:
            confirmation_key = self.generate_key(identifier)
            try:
                return self.create(confirmation_key=confirmation_key, **kwargs)
            except IntegrityError:
                errors += 1

        raise ConfirmationException(
            'Unable to generate a confirmation key for {identifier}'.format(
                identifier=identifier))

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
        that expired :py:class:`Confirmation` instances are never
        returned.

        :rtype: :py:class:`Confirmation` or ``None``
        """
        instance = super(ConfirmationManager, self).get(*args, **kwargs)
        return instance if not instance.is_expired() else None


@python_2_unicode_compatible
class Confirmation(models.Model):
    """
    An abstract model allowing its subclasses to store and create confirmation
    keys.
    """
    confirmation_key = models.CharField(max_length=40, unique=True)
    date_created = models.DateTimeField(auto_now_add=True)

    objects = ConfirmationManager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.confirmation_key

    def is_expired(self):
        """
        :returns True: if the confirmation key has expired
        :returns False: if the confirmation key is still valid
        """
        delta = timezone.now() - self.date_created
        return delta.days >= \
            settings.DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS


class UserManager(BaseUserManager):
    """
    A custom manager for :class:`User`
    """
    def _create_user(self, main_email, password,
                     is_staff, is_superuser, is_active=True, **extra_fields):
        """
        Creates and saves a User with the given username, email and password.
        """
        main_email = self.normalize_email(main_email)
        user = self.model(main_email=main_email,
                          is_staff=is_staff,
                          is_active=is_active,
                          is_superuser=is_superuser,
                          **extra_fields)
        user.set_password(password)
        user.save()

        # Match the email with a UserEmail instance and add it to the set of
        # associated emails for the user.
        email_user, _ = UserEmail.objects.get_or_create(email=main_email)
        user.emails.add(email_user)

        return user

    def create_user(self, main_email, password=None, **extra_fields):
        return self._create_user(main_email, password, False, False,
                                 **extra_fields)

    def create(self, main_email, password=None, **extra_fields):
        return self._create_user(main_email, password, False, False, False,
                                 **extra_fields)

    def create_superuser(self, main_email, password, **extra_fields):
        return self._create_user(main_email, password, True, True,
                                 **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    main_email = models.EmailField(
        max_length=255,
        unique=True,
        verbose_name='email')
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)

    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = 'main_email'

    objects = UserManager()

    def get_full_name(self):
        return self.first_name + ' ' + self.last_name

    def get_short_name(self):
        return self.get_full_name()


@python_2_unicode_compatible
class UserEmail(models.Model):
    email = models.EmailField(max_length=244, unique=True)
    user = models.ForeignKey(User, related_name='emails', null=True)

    def __str__(self):
        return self.email


class UserRegistrationConfirmation(Confirmation):
    """
    A model for user registration confirmations.
    """
    user = models.OneToOneField(User, related_name='confirmation')


class ResetPasswordConfirmation(Confirmation):
    """
    A model for account password reset confirmations.
    """
    user = models.ForeignKey(
        User, related_name='reset_password_confirmations')


class AddEmailConfirmation(Confirmation):
    user = models.ForeignKey(User)
    email = models.ForeignKey('UserEmail')


class MergeAccountConfirmation(Confirmation):
    initial_user = models.ForeignKey(
        User, related_name='merge_account_initial_set')
    merge_with = models.ForeignKey(
        User, related_name='merge_account_with_set')
