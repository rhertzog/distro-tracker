# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements a management command which adds a new keyword.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from distro_tracker.core.models import (
    EmailSettings,
    Keyword,
    Subscription,
    UserEmail
)
from distro_tracker.core.utils import get_or_none


class Command(BaseCommand):
    """
    A management command that adds a new keyword.

    It supports simply adding a new keyword and allowing users to add it to
    their subscriptions or to automatically add it to users' lists that
    already contain a different keyword (given as a parameter to the command).
    """
    help = ("Add a new keyword.\n."  # noqa
            "The command supports simply adding a new keyword and allowing"
            " users to add it to their subscriptions or to automatically add"
            " it to users' lists that already contain a different keyword"
            " (given as a parameter to the command).")

    def add_arguments(self, parser):
        parser.add_argument('keyword')
        parser.add_argument('existing_keyword', nargs='?', default=None)
        parser.add_argument(
            '--set-default',
            action='store_true',
            dest='is_default_keyword',
            default=False,
            help='Make the new keyword a default one'
        )

    def warning(self, msg, *args):
        if self.verbose > 1:
            text = msg % args
            self.stdout.write("Warning: {text}".format(text=text))

    def add_keyword_to_user_defaults(self, keyword, user_set):
        """
        Adds the given ``keyword`` to the
        :py:attr:`default_keywords
        <distro_tracker.core.models.EmailSettings.default_keywords>`
        list of each user found in the given QuerySet ``user_set``.

        :param keyword: The keyword which should be added to all the users'
            :py:attr:`default_keywords
            <distro_tracker.core.models.EmailSettings.default_keywords>`
        :type keyword: :py:class:`Keyword <distro_tracker.core.models.Keyword>`

        :param user_set: The set of users to which the given keyword should be
            added as a default keyword.
        :type user_set: :py:class:`QuerySet <django.db.models.query.QuerySet>`
            or other iterable of
            :py:class:`UserEmail <distro_tracker.core.models.UserEmail>`
            instances
        """
        for user_email in user_set:
            email_settings, _ = \
                EmailSettings.objects.get_or_create(user_email=user_email)
            email_settings.default_keywords.add(keyword)

    def add_keyword_to_subscriptions(self, new_keyword, existing_keyword):
        """
        Adds the given ``new_keyword`` to each
        :py:class:`Subscription <distro_tracker.core.models.Subscription>`'s
        keywords list which already contains the ``existing_keyword``.

        :param new_keyword: The keyword to add to the
            :py:class:`Subscription <distro_tracker.core.models.Subscription>`'s
            keywords
        :type new_keyword:
            :py:class:`Keyword <distro_tracker.core.models.Keyword>`

        :param existing_keyword: The keyword or name of the keyword based on
            which all
            :py:class:`Subscription <distro_tracker.core.models.Subscription>`
            to which the ``new_keyword`` should be added are chosen.
        :type existing_keyword:
            :py:class:`Keyword <distro_tracker.core.models.Keyword>`
            or string
        """
        if not isinstance(existing_keyword, Keyword):
            existing_keyword = get_or_none(Keyword, name=existing_keyword)
            if not existing_keyword:
                raise CommandError("Given keyword does not exist. "
                                   "No actions taken.")

        self.add_keyword_to_user_defaults(
            new_keyword,
            UserEmail.objects.filter(
                emailsettings__default_keywords=existing_keyword)
        )
        for subscription in Subscription.objects.all():
            if existing_keyword in subscription.keywords.all():
                if subscription._use_user_default_keywords:
                    # Skip these subscriptions since the keyword was already
                    # added to user's default lists.
                    continue
                else:
                    subscription.keywords.add(new_keyword)

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.verbose = int(kwargs.get('verbosity', 1)) > 1
        keyword = kwargs['keyword']
        if not keyword:
            raise CommandError("The name of the new keyword must be given")

        default = kwargs['is_default_keyword']
        keyword, created = Keyword.objects.get_or_create(
            name=keyword,
            defaults={
                'default': default,
            }
        )

        if not created:
            self.warning("The given keyword already exists")
            return

        if default:
            self.add_keyword_to_user_defaults(
                keyword,
                UserEmail.objects.exclude(emailsettings__isnull=True)
            )

        if kwargs['existing_keyword'] is not None:
            # Add the new keyword to all subscribers and subscriptions which
            # contain the parameter keyword
            other_keyword = kwargs['existing_keyword']
            self.add_keyword_to_subscriptions(keyword, other_keyword)

        if self.verbose:
            self.stdout.write('Successfully added new keyword {keyword}'.format(
                keyword=keyword))
