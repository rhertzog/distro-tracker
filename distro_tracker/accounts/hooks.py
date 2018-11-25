# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Functions that Distro-Tracker hooks into django_email_accounts."""

from distro_tracker.accounts.models import User


def post_merge(initial_user, merge_with):
    """
    When two user accounts are joined by :mod:`django_email_accounts`,
    move the teams owned by the account to be deleted to the new merged
    account.
    """
    # Convert to our custom user object to be able to use our own methods
    initial_user = User.objects.get(pk=initial_user.pk)
    merge_with = User.objects.get(pk=merge_with.pk)

    merge_with.owned_teams.all().update(owner=initial_user)
