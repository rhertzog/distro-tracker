# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a command which tries to update the signature information
for :class:`News <distro_tracker.core.models.News>` instances which do not have
any associated signatures.
"""
from __future__ import unicode_literals
from django.db import models
from django.core.management.base import BaseCommand
from distro_tracker.core.models import EmailNews


class Command(BaseCommand):
    """
    A Django management command which tries to update the signature information
    for :class:`News <distro_tracker.core.models.News>` instances which do not
    have any associated signatures.
    """
    help = (
        "Update the signature information related to News items which do not"
        " have any related signatures yet."
    )

    def write(self, text):
        if self.verbose:
            self.stdout.write(text)

    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs['verbosity']) > 1

        self.write("Retrieving list of news to update...")
        no_signature_news = EmailNews.objects.annotate(
            cnt=models.Count('signed_by'))
        no_signature_news = no_signature_news.filter(cnt=0)
        self.write("Processing news...")
        self.write("{ID}: {TITLE}")
        for news in no_signature_news:
            self.write("{}: {}".format(news.id, news))
            # Simply saving the instance directly triggers the signature
            # verification.
            news.save()
