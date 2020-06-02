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
Module implementing the processing of received emails which could be turned
into news items.
"""
from distro_tracker.core.models import EmailNews, PackageName
from distro_tracker.core.utils import get_or_none


def create_news(message, package, create_package=False, **kwargs):
    """
    Create a news item from the given message.

    The created news parameters are:

    - title - the Subject of the message
    - content - the message content itself
    - content_type - message/rfc822

    :param message: A message which should be turned into a news item.
    :type message: :class:`email.message.Message`
    :param package: The package for which this news item should be created.
    :type package: :class:`distro_tracker.core.models.PackageName` or a string.

    :returns: The created news item
    :rtype: :class:`distro_tracker.core.models.News`
    """
    if not isinstance(package, PackageName):
        if create_package:
            package, _ = PackageName.objects.get_or_create(name=package)
        else:
            package = get_or_none(PackageName, name=package)
    if package is None:  # Don't record news for non-existing packages
        return
    return EmailNews.objects.create_email_news(message, package, **kwargs)
