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
from pts.accounts.models import User


def post_merge(initial_user, merge_with):
    """
    When two user accounts are joined by :mod:`django_email_accounts`,
    move the teams owned by the account to be deleted to the new merged
    account.
    """
    # Convert the instances to PTS User instance (with PTS-specific
    # methods)
    initial_user = User.objects.get(pk=initial_user.pk)
    merge_with = User.objects.get(pk=merge_with.pk)

    merge_with.owned_teams.all().update(owner=initial_user)
