# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements all commands which deal with message keywords.
"""

import re

from distro_tracker.core.models import (
    EmailSettings,
    Keyword,
    PackageName,
    Subscription,
    UserEmail
)
from distro_tracker.core.utils import get_or_none
from distro_tracker.mail.control.commands.base import Command

__all__ = (
    'ViewDefaultKeywordsCommand',
    'ViewPackageKeywordsCommand',
    'SetDefaultKeywordsCommand',
    'SetPackageKeywordsCommand',
    'KeywordCommandMixin',
)


class KeywordCommandMixin(object):
    """
    A mixin including some utility methods for commands which handle keywords.
    """
    def error_not_subscribed(self, email, package_name):
        """
        Helper returns an error saying the user is not subscribed to the
        package.

        :param email: The email of the user which is not subscribed to the
            package.
        :param package_name: The name of the package the user is not subscribed
            to.
        """
        self.error('%s is not subscribed to the package %s',
                   email, package_name)

    def get_subscription(self, email, package_name):
        """
        Helper method returning a
        :py:class:`Subscription <distro_tracker.core.models.Subscription>`
        instance for the given package and user.
        It logs any errors found while retrieving this instance, such as the
        user not being subscribed to the given package.

        :param email: The email of the user.
        :param package_name: The name of the package.
        """
        user_email = get_or_none(UserEmail, email__iexact=email)
        email_settings = get_or_none(EmailSettings, user_email=user_email)
        if not user_email or not email_settings:
            self.error_not_subscribed(email, package_name)
            return

        package = get_or_none(PackageName, name=package_name)
        if not package:
            self.error('Package %s does not exist', package_name)
            return

        subscription = get_or_none(Subscription,
                                   package=package,
                                   email_settings=email_settings)
        if not subscription:
            self.error_not_subscribed(email, package_name)

        return subscription

    def keyword_name_to_object(self, keyword_name):
        """
        Takes a keyword name and returns a
        :py:class:`Keyword <distro_tracker.core.models.Keyword>` object with
        the given name if it exists. If not, a warning is added to the commands'
        output.

        :param keyword_name: The name of the keyword to be retrieved.
        :rtype: :py:class:`Keyword <distro_tracker.core.models.Keyword>` or
            ``None``
        """
        keyword = get_or_none(Keyword, name=keyword_name)
        if not keyword:
            self.warning('%s is not a valid keyword', keyword_name)
        return keyword

    def add_keywords(self, keywords, manager):
        """
        Adds the keywords given in the iterable ``keywords`` to the ``manager``

        :param keywords: The keywords to be added to the ``manager``
        :type keywords: any iterable containing
            :py:class:`Keyword <distro_tracker.core.models.Keyword>` instances

        :param manager: The manager to which the keywords should be added.
        :type manager: :py:class:`Manager <django.db.models.Manager>`
        """
        for keyword_name in keywords:
            keyword = self.keyword_name_to_object(keyword_name)
            if keyword:
                manager.add(keyword)

    def remove_keywords(self, keywords, manager):
        """
        Removes the keywords given in the iterable ``keywords`` from the
        ``manager``.

        :param keywords: The keywords to be removed from the ``manager``
        :type keywords: any iterable containing
            :py:class:`Keyword <distro_tracker.core.models.Keyword>` instances

        :param manager: The manager from which the keywords should be removed.
        :type manager: :py:class:`Manager <django.db.models.Manager>`
        """
        for keyword_name in keywords:
            keyword = self.keyword_name_to_object(keyword_name)
            if keyword:
                manager.remove(keyword)

    def set_keywords(self, keywords, manager):
        """
        Sets the keywords given in the iterable ``keywords`` to the ``manager``
        so that they are the only keywords it contains.

        :param keywords: The keywords to be set to the ``manager``
        :type keywords: any iterable containing
            :py:class:`Keyword <distro_tracker.core.models.Keyword>` instances

        :param manager: The manager to which the keywords should be added.
        :type manager: :py:class:`Manager <django.db.models.Manager>`
        """
        manager.clear()
        self.add_keywords(keywords, manager)

    OPERATIONS = {
        '+': add_keywords,
        '-': remove_keywords,
        '=': set_keywords,
    }
    """
    Maps symbols to operations. When the symbol is found in a keyword command
    the given operation is called.

    - '+': :py:meth:`add_keywords`
    - '-': :py:meth:`remove_keywords`
    - '=': :py:meth:`set_keywords`
    """


class ViewDefaultKeywordsCommand(Command, KeywordCommandMixin):
    """
    Implementation of the keyword command which handles displaying a list
    of the user's default keywords.
    """
    META = {
        'position': 10,
        'name': 'view-default-keywords',
        'aliases': ['keyword', 'tag', 'keywords', 'tags'],
        'description': '''keyword [<email>]
  Tells you the keywords you are accepting by default for packages
  with no specific keywords set.

  Each mail sent through the Distro Tracker is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, email):
        super(ViewDefaultKeywordsCommand, self).__init__()
        self.email = email

    def get_command_text(self):
        return super(ViewDefaultKeywordsCommand, self).get_command_text(
            self.email)

    def handle(self):
        user_email, _ = UserEmail.objects.get_or_create(email=self.email)
        email_settings, _ = \
            EmailSettings.objects.get_or_create(user_email=user_email)
        self.reply("Here's the default list of accepted keywords for %s:",
                   self.email)
        self.list_reply(sorted(
            keyword.name for keyword in email_settings.default_keywords.all()))


class ViewPackageKeywordsCommand(Command, KeywordCommandMixin):
    """
    Implementation of the keyword command version which handles listing
    all keywords associated to a package for a particular user.
    """
    META = {
        'position': 11,
        'name': 'view-package-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'description': '''keyword <srcpackage> [<email>]
  Tells you the keywords you are accepting for the given package.

  Each mail sent through Distro Tracker is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, package, email):
        super(ViewPackageKeywordsCommand, self).__init__()
        self.package = package
        self.email = email

    def get_command_text(self):
        return super(ViewPackageKeywordsCommand, self).get_command_text(
            self.package,
            self.email)

    def handle(self):
        subscription = self.get_subscription(self.email, self.package)
        if not subscription:
            return

        self.reply(
            "Here's the list of accepted keywords associated to package")
        self.reply('%s for %s', self.package, self.email)
        self.list_reply(sorted(
            keyword.name for keyword in subscription.keywords.all()))


class SetDefaultKeywordsCommand(Command, KeywordCommandMixin):
    """
    Implementation of the keyword command which handles modifying a user's
    list of default keywords.
    """
    META = {
        'position': 12,
        'name': 'set-default-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'description': '''keyword [<email>] {+|-|=} <list of keywords>
  Accept (+) or refuse (-) mails associated to the given keyword(s).
  Define the list (=) of accepted keywords.
  These keywords are applied for subscriptions where no specific
  keyword set is given.'''
    }
    REGEX_LIST = (
        (r'(?:\s+(?P<email>\S+@\S+))?\s+(?P<operation>[-+=])'
         r'\s+(?P<keywords>\S+(?:\s+\S+)*)$'),
    )

    def __init__(self, email, operation, keywords):
        super(SetDefaultKeywordsCommand, self).__init__()
        self.email = email
        self.operation = operation
        self.keywords = keywords

    def get_command_text(self):
        return super(SetDefaultKeywordsCommand, self).get_command_text(
            self.email,
            self.operation,
            self.keywords)

    def handle(self):
        keywords = re.split(r'[,\s]+', self.keywords)
        user_email, _ = UserEmail.objects.get_or_create(email=self.email)
        email_settings, _ = \
            EmailSettings.objects.get_or_create(user_email=user_email)

        operation_method = self.OPERATIONS[self.operation]
        operation_method(self, keywords, email_settings.default_keywords)

        self.reply("Here's the new default list of accepted keywords for %s :",
                   self.email)
        self.list_reply(sorted(
            keyword.name for keyword in email_settings.default_keywords.all()
        ))


class SetPackageKeywordsCommand(Command, KeywordCommandMixin):
    """
    Implementation of the keyword command version which modifies subscription
    specific keywords.
    """
    META = {
        'name': 'set-package-keywords',
        'aliases': ['keyword', 'keywords', 'tag', 'tags'],
        'position': 13,
        'description': (
            '''keyword <srcpackage> [<email>] {+|-|=} <list of keywords>
  Accept (+) or refuse (-) mails associated to the given keyword(s) for the
  given package.
  Define the list (=) of accepted keywords.
  These keywords take precedence over default keywords.''')
    }
    REGEX_LIST = (
        (r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?\s+'
         r'(?P<operation>[-+=])\s+(?P<keywords>\S+(?:\s+\S+)*)$'),
    )

    def __init__(self, package, email, operation, keywords):
        super(SetPackageKeywordsCommand, self).__init__()
        self.package = package
        self.email = email
        self.operation = operation
        self.keywords = keywords

    def get_command_text(self):
        return super(SetPackageKeywordsCommand, self).get_command_text(
            self.package,
            self.email,
            self.operation,
            self.keywords)

    def handle(self):
        """
        Actual implementation of the keyword command version which handles
        subscription specific keywords.
        """
        keywords = re.split(r'[,\s]+', self.keywords)
        subscription = self.get_subscription(self.email, self.package)
        if not subscription:
            return

        operation_method = self.OPERATIONS[self.operation]
        operation_method(self, keywords, subscription.keywords)

        self.reply(
            "Here's the new list of accepted keywords associated to package\n"
            "%s for %s :", self.package, self.email)
        self.list_reply(sorted(
            keyword.name for keyword in subscription.keywords.all()))
