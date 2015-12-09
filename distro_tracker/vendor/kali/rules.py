# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Kali specific rules
"""
from __future__ import unicode_literals

import os.path

from distro_tracker.mail import mail_news


def classify_message(msg, package, keyword):
    # Default values for git commit notifications
    xgitrepo = msg.get('X-Git-Repo')
    if xgitrepo:
        if not package:
            if xgitrepo.endswith('.git'):
                xgitrepo = xgitrepo[:-4]
            package = os.path.basename(xgitrepo)
        if not keyword:
            keyword = 'vcs'

    # Store some messages as news
    if msg.get('X-Distro-Tracker-News', 'no') == 'yes' and package:
        mail_news.create_news(msg, package)
    return (package, keyword)


def approve_default_message(msg):
    """
    The function should return a ``Boolean`` indicating whether this message
    should be forwarded to subscribers which are subscribed to default
    keyword messages.

    :param msg: The message to approve
    :type msg: :py:class:`email.message.Message`
    """
    return False
