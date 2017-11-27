# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Models for the :mod:`distro_tracker.accounts` app."""
from django_email_accounts.models import User as EmailAccountsUser

# Re-export some objects of django_email_accounts
from django_email_accounts.models import UserEmail
from django_email_accounts.models import (  # noqa
    UserRegistrationConfirmation,
    ResetPasswordConfirmation,
    AddEmailConfirmation,
    MergeAccountConfirmation,
)


class User(EmailAccountsUser):
    """
    Proxy model for :class:`django_email_accounts.models.User` extending it
    with some Distro Tracker specific methods.
    """
    class Meta:
        proxy = True

    def is_subscribed_to(self, package):
        """
        Checks if the user is subscribed to the given package. The user is
        considered subscribed if at least one of its associated emails is
        subscribed.

        :param package: The name of the package or a package instance
        :type package: string or :class:`distro_tracker.core.models.PackageName`
        """
        from distro_tracker.core.models import PackageName
        if not isinstance(package, PackageName):
            try:
                package = PackageName.objects.get(name=package)
            except PackageName.DoesNotExist:
                return False
        qs = package.subscriptions.filter(user_email__in=self.emails.all())
        return qs.exists()

    def unsubscribe_all(self, email=None):
        """
        Terminate the user's subscription associated to the given
        email. Uses the main email if not specified.
        """
        if not email:
            email = self.main_email
        user_email = UserEmail.objects.get(email=email)
        if self.emails.filter(pk=user_email.id).exists():
            user_email.emailsettings.subscription_set.all().delete()
