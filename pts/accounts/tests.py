# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""
Tests for the :mod:`pts.accounts` app.
"""
from __future__ import unicode_literals
from django.test import TestCase
from pts.accounts.models import User
from pts.core.models import EmailUser


class UserManagerTests(TestCase):
    """
    Tests for the :class:`pts.accounts.UserManager` class.
    """
    def test_create_user(self):
        email = 'user@domain.com'

        u = User.objects.create_user(main_email=email, password='asdf')

        # The user is correctly created
        self.assertEqual(1, User.objects.count())
        self.assertEqual(email, u.main_email)
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)
        self.assertTrue(u.is_active)
        # The user is associated with a EmailUser
        self.assertEqual(1, u.emails.count())
        email_user = EmailUser.objects.all()[0]
        self.assertEqual(u, email_user.user)

    def test_create_user_existing_email(self):
        """
        Tests creating a user when the email already exists.
        """
        email = 'user@domain.com'
        EmailUser.objects.create(email=email)

        u = User.objects.create_user(main_email=email, password='asdf')

        # The user is associated with the existing email user
        self.assertEqual(1, EmailUser.objects.count())
        self.assertEqual(u, EmailUser.objects.all()[0].user)

    def test_create_superuser(self):
        email = 'user@domain.com'

        u = User.objects.create_superuser(main_email=email, password='asdf')

        # The user is created
        self.assertEqual(1, User.objects.count())
        self.assertTrue(u.is_superuser)
        self.assertTrue(u.is_staff)

    def test_create(self):
        email = 'user@domain.com'

        u = User.objects.create(main_email=email, password='asdf')

        # The user is correctly created
        self.assertEqual(1, User.objects.count())
        self.assertEqual(email, u.main_email)
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)
        # This creates inactive users
        self.assertFalse(u.is_active)
        # The user is associated with a EmailUser
        self.assertEqual(1, u.emails.count())
        email_user = EmailUser.objects.all()[0]
        self.assertEqual(u, email_user.user)
