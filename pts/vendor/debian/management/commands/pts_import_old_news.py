# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

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
from django.utils import timezone
from pts.core.models import EmailNews
from pts.core.models import PackageName

import os
from datetime import datetime
import email


class Command(BaseCommand):
    """
    Import old PTS news.
    """
    args = 'root-dir'

    def get_directories(self, root_directory):
        return [
            os.path.join(root_directory, d)
            for d in os.listdir(root_directory)
            if os.path.isdir(os.path.join(root_directory, d))
        ]

    def write(self, message):
        if self.verbose:
            self.stdout.write(message)

    def import_package_news(self, package_directory_name):
        package_name = os.path.basename(package_directory_name)
        self.write('Processing package {pkg}...'.format(pkg=package_name))

        try:
            package = PackageName.objects.get(name=package_name)
        except PackageName.DoesNotExist:
            self.write('Package does not exist. Skipping messages...')
            return

        news_directory = os.path.join(package_directory_name, 'news')

        for news_file in sorted(os.listdir(news_directory)):
            news_file_path = os.path.join(news_directory, news_file)

            try:
                with open(news_file_path, 'rb') as f:
                    msg = email.message_from_file(f)
                if 'Date' in msg:
                    timestamp = email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))
                    date = datetime.utcfromtimestamp(timestamp)
                    date = timezone.make_aware(date, timezone.utc)
                else:
                    date = timezone.now()

                EmailNews.objects.create_email_news(
                    package=package,
                    message=msg,
                    datetime_created=date)
            except:
                import traceback
                traceback.print_exc()
                self.write('Problem importing news {}'.format(news_file_path))

        self.write('Complete.')

    def import_all_news(self, root_directory):
        for hash_directory_path in self.get_directories(root_directory):
            for package_directory_path in self.get_directories(hash_directory_path):
                self.import_package_news(package_directory_path)

    def handle(self, *args, **kwargs):
        if len(args) != 1:
            raise CommandError("Root directory of old news not provided")
        self.verbose = int(kwargs.get('verbosity', 1)) > 1

        # Hack to be able to set the date created field to something else than now.
        EmailNews._meta.get_field_by_name('datetime_created')[0].auto_now_add = False

        self.import_all_news(args[0])

        EmailNews._meta.get_field_by_name('datetime_created')[0].auto_now_add = True
