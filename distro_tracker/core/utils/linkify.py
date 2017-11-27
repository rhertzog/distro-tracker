# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Module including some utility functions to inject links in plain text.
"""
import re

from django.conf import settings

from distro_tracker.core.utils.plugins import PluginRegistry


class Linkify(metaclass=PluginRegistry):
    """
    A base class representing ways to inject useful links in plain text data

    If you want to recognize a new syntax where links could provide value to
    a view of the content, just create a subclass and implement the linkify
    method.
    """

    @staticmethod
    def linkify(text):
        """
        :param text: the text where we should inject HTML links
        :type param: str
        :returns: the text formatted with HTML links
        :rtype: str
        """
        return text


class LinkifyHttpLinks(Linkify):
    """
    Detect http:// and https:// URLs and transform them in true HTML
    links.
    """

    @staticmethod
    def linkify(text):
        return re.sub(r'(?:^|(?<=\s))(https?://[^\s]*)',
                      r'<a href="\1">\1</a>',
                      text)


class LinkifyDebianBugLinks(Linkify):
    """
    Detect "Closes: #123, 234" syntax used in Debian changelogs to close
    bugs and inject HTML links to the corresponding bug tracker entry.
    Also handles the "Closes: 123 456" fields of .changes files.
    """

    close_prefix = 'Closes:'
    close_field = 'Closes:'
    bug_url = 'https://bugs.debian.org/'

    @classmethod
    def _linkify_field(cls, text):
        if not cls.close_field:
            return text
        split_text = re.split(
            '(^' + cls.close_field + r'(?: \d+)+\s*$)',
            text, flags=re.IGNORECASE | re.MULTILINE)
        generated_link = ''
        for i, txt in enumerate(split_text):
            if i % 2:
                new_txt = re.sub(
                    r'(\d+)', r'<a href="{}\1">\1</a>'.format(cls.bug_url),
                    txt, flags=re.IGNORECASE)
                generated_link += new_txt
            else:
                generated_link += txt
        return generated_link

    @classmethod
    def _linkify_changelog_entry(cls, text):
        split_text = re.split(
            '(' + cls.close_prefix +
            r'\s*(?:bug)?(?:#)?\d+(?:\s*,\s*(?:bug)?(?:#)?\d+)*)',
            text, flags=re.IGNORECASE)
        generated_link = ''
        for i, txt in enumerate(split_text):
            if i % 2:
                new_txt = re.sub(
                    r'((?:#)?(\d+))',
                    r'<a href="{}\2">\1</a>'.format(cls.bug_url),
                    txt, flags=re.IGNORECASE)
                generated_link += new_txt
            else:
                generated_link += txt
        return generated_link

    @classmethod
    def linkify(cls, text):
        return cls._linkify_changelog_entry(cls._linkify_field(text))


class LinkifyUbuntuBugLinks(LinkifyDebianBugLinks):
    """
    Detect "LP: #123, 234" syntax used in Ubuntu changelogs to close
    bugs and inject HTML links to the corresponding bug tracker entry.
    """

    close_prefix = 'LP:'
    close_field = 'Launchpad-Bugs-Fixed:'
    bug_url = 'https://bugs.launchpad.net/bugs/'


class LinkifyCVELinks(Linkify):
    """
    Detect "CVE-2014-1234" words and transform them into links to the
    CVE tracker at cve.mitre.org. The exact URL can be overridden with a
    ``DISTRO_TRACKER_CVE_URL`` configuration setting to redirect
    the URL to a custom tracker.
    """

    @staticmethod
    def linkify(text):
        address = getattr(settings, 'DISTRO_TRACKER_CVE_URL',
                          'https://cve.mitre.org/cgi-bin/cvename.cgi?name=')
        return re.sub(r'(?:(?<=\s)|\A)((CVE)-(\d){4}-(\d){4,})',
                      r'<a href="{}\1">\1</a>'.format(address),
                      text, flags=re.IGNORECASE)


def linkify(message):
    """
    :param message: the message where we should inject HTML links
    :type param: str
    :returns: the message formatted with HTML links
    :rtype: str
    """
    for plugin in Linkify.plugins:
        message = plugin.linkify(message)
    return message
