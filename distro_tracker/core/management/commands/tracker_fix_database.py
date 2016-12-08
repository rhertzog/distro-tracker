# Copyright 2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a command to perform various database fixups.
"""
from __future__ import unicode_literals

from django.db.models import Count
from django.db.models.functions import Lower
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand

from distro_tracker.core.models import UserEmail, EmailSettings


class Command(BaseCommand):
    """
    A management command which updates package information found in all
    registered repositories.
    """
    help = "Fix various database inconsistencies"

    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs.get('verbosity', 1)) > 1
        self.drop_duplicate_user_emails()

    def write(self, message):
        if self.verbose:
            self.stdout.write(message)

    def drop_duplicate_user_emails(self):
        qs = UserEmail.objects.annotate(lower_email=Lower('email'))
        qs = qs.values('lower_email').annotate(count=Count('lower_email'))
        qs = qs.filter(count__gt=1)
        for item in qs:
            qs = UserEmail.objects.annotate(lower_email=Lower('email'))
            qs = qs.filter(lower_email=item['lower_email']).order_by('id')
            all_user_emails = list(qs)
            target = all_user_emails[0]
            for source in all_user_emails[1:]:
                self.write("Merging UserEmail {} into {}...".format(
                    source.email, target.email))
                if target.user is None and source.user:
                    self.write(" Associating user")
                    target.user = source.user
                    target.save()
                try:
                    target.emailsettings
                except ObjectDoesNotExist:
                    self.write(" Adding EmailSettings")
                    EmailSettings.objects.create(user_email=target).save()
                    target.refresh_from_db()
                self.merge_subscriptions(target, source)
                source.delete()

    def merge_subscriptions(self, target, source):
        try:
            source.emailsettings
        except ObjectDoesNotExist:
            self.write(" {} has no EmailSettings".format(source.email))
            return
        self.write(" Moving subscriptions")
        target_sub = target.emailsettings.subscription_set
        for sub in source.emailsettings.subscription_set.all():
            if target_sub.filter(package__name=sub.package.name).count() == 0:
                self.write("  Moving {} package subscription "
                           "from {} to {}".format(sub.package.name,
                                                  source.email, target.email))
                target.emailsettings.subscription_set.add(sub)
