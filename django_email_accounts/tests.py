# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
from __future__ import unicode_literals

from django.test import TestCase

from django_email_accounts.models import UserEmail


class UserEmailTests(TestCase):

    def test_user_email_get_or_create_uses_case_insensitive_email(self):
        orig_user_email = UserEmail.objects.create(email='MyEmail@example.net')
        user_email, created = UserEmail.objects.get_or_create(
            email='myemail@example.net')
        self.assertFalse(created)
        self.assertEqual(orig_user_email.pk, user_email.pk)
