# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Models for the :mod:`pts.accounts` app."""
from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from pts.core.models import Confirmation
from pts.core.models import EmailUser
from pts.core.models import PackageName


class UserManager(BaseUserManager):
    """
    A custom manager for :class:`User`
    """
    def _create_user(self, main_email, password,
                     is_staff, is_superuser, is_active=True, **extra_fields):
        """
        Creates and saves a User with the given username, email and password.
        """
        # Necessary to avoid a circular dependency of the modules
        main_email = self.normalize_email(main_email)
        user = self.model(main_email=main_email,
                          is_staff=is_staff,
                          is_active=is_active,
                          is_superuser=is_superuser)
        user.set_password(password)
        user.save()

        # Match the email with a EmailUser instance and add it to the set of
        # associated emails for the user.
        email_user, _ = EmailUser.objects.get_or_create(email=main_email)
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

    def is_subscribed_to(self, package):
        """
        Checks if the user is subscribed to the given package. The user is
        considered subscribed if at least one of its associated emails is
        subscribed.

        :param package: The name of the package or a package instance
        :type package: string or :class:`pts.core.models.PackageName`
        """
        if not isinstance(package, PackageName):
            package = PackageName.objects.get(name=package)
        qs = package.subscriptions.filter(pk__in=self.emails.all())
        return qs.exists()

class UserRegistrationConfirmation(Confirmation):
    """
    A model for user registration confirmations.
    """
    user = models.OneToOneField(User, related_name='confirmation')
