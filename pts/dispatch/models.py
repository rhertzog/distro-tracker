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
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.conf import settings
from pts.core.models import EmailUser


class UserBounceInformationManager(models.Manager):
    def get_bounce_info(self, email, date):
        user = EmailUser.objects.get(email=email)
        user_info, _ = self.get_or_create(email_user=user)
        bounce_info, _ = user_info.bounceinformation_set.get_or_create(
            date=date)
        return bounce_info

    def add_bounce_for_user(self, email, date):
        bounce_info = self.get_bounce_info(email, date)
        bounce_info.mails_bounced_number += 1
        bounce_info.save()

        self.limit_bounce_information(email)

    def add_sent_for_user(self, email, date):
        bounce_info = self.get_bounce_info(email, date)
        bounce_info.mails_sent_number += 1
        bounce_info.save()

        self.limit_bounce_information(email)

    def limit_bounce_information(self, email):
        """
        Makes sure not to keep more records than the number of days set by
        ``PTS_MAX_DAYS_TOLERATE_BOUNCE``.
        """
        user_info = self.get(email_user__email=email)
        days = settings.PTS_MAX_DAYS_TOLERATE_BOUNCE
        for info in user_info.bounceinformation_set.all()[days:]:
            info.delete()


@python_2_unicode_compatible
class UserBounceInformation(models.Model):
    email_user = models.OneToOneField(EmailUser)

    objects = UserBounceInformationManager()

    def has_too_many_bounces(self):
        """
        Checks if the user has too many bounces.
        """
        days = settings.PTS_MAX_DAYS_TOLERATE_BOUNCE
        count = 0
        for info in self.bounceinformation_set.all()[:days]:
            # If no mails were sent on a particular day...
            if info.mails_sent_number:
                if info.mails_bounced_number >= info.mails_sent_number:
                    count += 1
        return count == days

    def __str__(self):
        return "Information for {email}".format(email=self.email_user)


@python_2_unicode_compatible
class BounceInformation(models.Model):
    user_information = models.ForeignKey(UserBounceInformation)
    mails_sent_number = models.IntegerField(default=0)
    mails_bounced_number = models.IntegerField(default=0)
    date = models.DateField()

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return '{email} on {date} {sent} {bounced}'.format(
            email=self.user_information.email_user,
            date=self.date,
            sent=self.mails_sent_number,
            bounced=self.mails_bounced_number)
