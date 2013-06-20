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

from pts.control.commands.base import Command
from pts.core.models import (
    Subscription, EmailUser, Package, Keyword)

from pts.core.utils import get_or_none

import re

__all__ = (
    'ViewDefaultKeywordsCommand',
    'ViewPackageKeywordsCommand',
    'SetDefaultKeywordsCommand',
    'SetPackageKeywordsCommand',
)


class KeywordCommandMixin(object):
    """
    A mixin including some utility methods for commands which handle keywords.
    """
    def get_subscription(self, email, package_name):
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            self.error('{email} is not subscribed to any package'.format(
                email=email))
            return

        package = get_or_none(Package, name=package_name)
        if not package:
            self.error('Package {package} does not exist'.format(
                package=package_name))
            return

        subscription = get_or_none(Subscription,
                                   package=package,
                                   email_user=email_user)
        if not subscription:
            self.error(
                '{email} is not subscribed to the package {package}'.format(
                    email=email,
                    package=package_name)
            )

        return subscription

    def keyword_name_to_object(self, keyword_name):
        """
        Takes a keyword name and returns a Keyword object with the given name
        if it exists.
        """
        keyword = get_or_none(Keyword, name=keyword_name)
        if not keyword:
            self.warn('{keyword} is not a valid keyword'.format(
                keyword=keyword_name))
        return keyword

    def add_keywords(self, keywords, manager):
        """
        Adds the keywords given in the iterable ``keywords`` to the ``manager``
        """
        for keyword_name in keywords:
            keyword = self.keyword_name_to_object(keyword_name)
            if keyword:
                manager.add(keyword)

    def remove_keywords(self, keywords, manager):
        """
        Removes the keywords given in the iterable ``keywords`` from the
        ``manager``.
        """
        for keyword_name in keywords:
            keyword = self.keyword_name_to_object(keyword_name)
            if keyword:
                manager.remove(keyword)

    def set_keywords(self, keywords, manager):
        """
        Sets the keywords given in the iterable ``keywords`` to the ``manager``
        so that they are the only keywords it contains.
        """
        manager.clear()
        self.add_keywords(keywords, manager)

    OPERATIONS = {
        '+': add_keywords,
        '-': remove_keywords,
        '=': set_keywords,
    }


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

  Each mail sent through the Package Tracking System is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, email):
        Command.__init__(self)
        self.email = email

    def handle(self):
        email_user, _ = EmailUser.objects.get_or_create(email=self.email)
        self.reply(
            "Here's the default list of accepted keywords for {email}:".format(
                email=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in email_user.default_keywords.all()))


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

  Each mail sent through the Package Tracking System is associated
  to a keyword and you receive only the mails associated to keywords
  you are accepting.
  You may select a different set of keywords for each package.'''
    }
    REGEX_LIST = (
        r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?$',
    )

    def __init__(self, package, email):
        Command.__init__(self)
        self.package = package
        self.email = email

    def handle(self):
        subscription = self.get_subscription(self.email, self.package)
        if not subscription:
            return

        self.reply(
            "Here's the list of accepted keywords associated to package")
        self.reply('{package} for {user}'.format(package=self.package,
                                                 user=self.email))
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
        Command.__init__(self)
        self.email = email
        self.operation = operation
        self.keywords = keywords

    def handle(self):
        keywords = re.split('[,\s]+', self.keywords)
        email_user, _ = EmailUser.objects.get_or_create(email=self.email)

        operation_method = self.OPERATIONS[self.operation]
        operation_method(self, keywords, email_user.default_keywords)

        self.reply(
            "Here's the new default list of accepted keywords for "
            "{user} :".format(user=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in email_user.default_keywords.all()
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
  These keywords take precendence to default keywords.''')
    }
    REGEX_LIST = (
        (r'\s+(?P<package>\S+)(?:\s+(?P<email>\S+@\S+))?\s+'
         r'(?P<operation>[-+=])\s+(?P<keywords>\S+(?:\s+\S+)*)$'),
    )

    def __init__(self, package, email, operation, keywords):
        Command.__init__(self)
        self.package = package
        self.email = email
        self.operation = operation
        self.keywords = keywords

    def handle(self):
        """
        Actual implementation of the keyword command version which handles
        subscription specific keywords.
        """
        keywords = re.split('[,\s]+', self.keywords)
        subscription = self.get_subscription(self.email, self.package)
        if not subscription:
            return

        operation_method = self.OPERATIONS[self.operation]
        operation_method(self, keywords, subscription.keywords)

        self.reply(
            "Here's the new list of accepted keywords associated to package")
        self.reply('{package} for {user} :'.format(package=self.package,
                                                   user=self.email))
        self.list_reply(sorted(
            keyword.name for keyword in subscription.keywords.all()))
