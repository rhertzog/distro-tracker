# Copyright 2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Module including some utility functions to inject links in plain text.
"""
from __future__ import unicode_literals
import re

from django.utils import six
from django.conf import settings

from distro_tracker.core.utils.plugins import PluginRegistry


class Linkify(six.with_metaclass(PluginRegistry)):
    """
    A base class representing ways to inject useful links in plain text data

    If you want to recognize a new syntax where links could provide value to
    a view of the content, just create a subclass and implement the linkify
    method.
    """

    @classmethod
    def linkify(self, text):
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

    @classmethod
    def linkify(self, text):
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
    def _linkify_field(self, text):
        if not self.close_field:
            return text
        split_text = re.split(
            '(^' + self.close_field + r'(?: \d+)+\s*$)',
            text, flags=re.IGNORECASE | re.MULTILINE)
        generated_link = ''
        for i, txt in enumerate(split_text):
            if i % 2:
                new_txt = re.sub(
                    r'(\d+)', r'<a href="{}\1">\1</a>'.format(self.bug_url),
                    txt, flags=re.IGNORECASE)
                generated_link += new_txt
            else:
                generated_link += txt
        return generated_link

    @classmethod
    def _linkify_changelog_entry(self, text):
        split_text = re.split(
            '(' + self.close_prefix +
            r'\s*(?:bug)?(?:#)?\d+(?:\s*,\s*(?:bug)?(?:#)?\d+)*)',
            text, flags=re.IGNORECASE)
        generated_link = ''
        for i, txt in enumerate(split_text):
            if i % 2:
                new_txt = re.sub(
                    r'((?:#)?(\d+))',
                    r'<a href="{}\2">\1</a>'.format(self.bug_url),
                    txt, flags=re.IGNORECASE)
                generated_link += new_txt
            else:
                generated_link += txt
        return generated_link

    @classmethod
    def linkify(self, text):
        return self._linkify_changelog_entry(self._linkify_field(text))


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
    CVE tracker at cve.mitre.org. The exact URL can be overriden with a
    ``DISTRO_TRACKER_CVE_URL`` configuration setting to redirect
    the URL to a custom tracker.
    """

    @classmethod
    def linkify(self, text):
        address = getattr(settings, 'DISTRO_TRACKER_CVE_URL',
                          'https://cve.mitre.org/cgi-bin/cvename.cgi?name=')
        return re.sub(r'((CVE)-(\d){4}-(\d){4,})',
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
