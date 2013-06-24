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


class EmailUserBounceStatsManager(models.Manager):
    def get_bounce_stats(self, email, date):
        user = self.get(email=email)
        bounce_stats, created = user.bouncestats_set.get_or_create(date=date)
        if created:
            self.limit_bounce_information(email)
        return bounce_stats

    def add_bounce_for_user(self, email, date):
        bounce_stats = self.get_bounce_stats(email, date)
        bounce_stats.mails_bounced += 1
        bounce_stats.save()

    def add_sent_for_user(self, email, date):
        bounce_stats = self.get_bounce_stats(email, date)
        bounce_stats.mails_sent += 1
        bounce_stats.save()

    def limit_bounce_information(self, email):
        """
        Makes sure not to keep more records than the number of days set by
        ``PTS_MAX_DAYS_TOLERATE_BOUNCE``.
        """
        user = self.get(email=email)
        days = settings.PTS_MAX_DAYS_TOLERATE_BOUNCE
        for info in user.bouncestats_set.all()[days:]:
            info.delete()


class EmailUserBounceStats(EmailUser):
    class Meta:
        proxy = True

    objects = EmailUserBounceStatsManager()

    def has_too_many_bounces(self):
        """
        Checks if the user has too many bounces.
        """
        days = settings.PTS_MAX_DAYS_TOLERATE_BOUNCE
        count = 0
        for stats in self.bouncestats_set.all()[:days]:
            # If no mails were sent on a particular day nothing could bounce
            if stats.mails_sent:
                if stats.mails_bounced >= stats.mails_sent:
                    count += 1
        return count == days


@python_2_unicode_compatible
class BounceStats(models.Model):
    email_user = models.ForeignKey(EmailUserBounceStats)
    mails_sent = models.IntegerField(default=0)
    mails_bounced = models.IntegerField(default=0)
    date = models.DateField()

    class Meta:
        ordering = ['-date']
        unique_together = ('email_user', 'date')

    def __str__(self):
        return (
            'Got {bounced} bounces out of {sent} mails to {email} on {date}'.format(
                email=self.email_user,
                date=self.date,
                sent=self.mails_sent,
                bounced=self.mails_bounced)
        )
