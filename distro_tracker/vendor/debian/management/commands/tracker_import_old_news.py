# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
import email
import os
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from distro_tracker.core.models import EmailNews, News, PackageName


class Command(BaseCommand):
    """
    Import old PTS news.

    The imported news' signature information is not automatically extracted.
    """

    def add_arguments(self, parser):
        parser.add_argument('rootdir')

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
        if not os.path.exists(news_directory):
            self.write("Package has no news directory.")
            return

        email_news = []
        for news_file in sorted(os.listdir(news_directory)):
            news_file_path = os.path.join(news_directory, news_file)

            try:
                with open(news_file_path, 'rb') as f:
                    if hasattr(email, 'message_from_binary_file'):
                        msg = email.message_from_binary_file(f)
                    else:
                        msg = email.message_from_file(f)
                if 'Date' in msg:
                    timestamp = email.utils.mktime_tz(
                        email.utils.parsedate_tz(msg['Date']))
                    date = datetime.utcfromtimestamp(timestamp)
                    date = timezone.make_aware(date, timezone.utc)
                else:
                    date = timezone.now()

                news_kwargs = EmailNews.get_email_news_parameters(msg)
                content = news_kwargs.pop('file_content')
                news_kwargs['news_file'] = ContentFile(content,
                                                       name='news-file')

                email_news.append(News(
                    package=package,
                    datetime_created=date,
                    **news_kwargs))
            except Exception:
                import traceback
                traceback.print_exc()
                self.write('Problem importing news {}'.format(news_file_path))

        self.write("All news for the package processed. "
                   "Bulk creating the instances.")
        News.objects.bulk_create(email_news)

        self.write('Complete.')

    def import_all_news(self, root_directory):
        for hash_directory in self.get_directories(root_directory):
            for package_directory in self.get_directories(hash_directory):
                self.import_package_news(package_directory)

    def handle(self, *args, **kwargs):
        if 'rootdir' not in kwargs or not kwargs['rootdir']:
            raise CommandError("Root directory of old news not provided")
        self.verbose = int(kwargs.get('verbosity', 1)) > 1

        # Hack to be able to set the date created field to something else
        # than now.
        EmailNews._meta.get_field('datetime_created').auto_now_add = False

        self.import_all_news(kwargs['rootdir'])

        EmailNews._meta.get_field('datetime_created').auto_now_add = True
