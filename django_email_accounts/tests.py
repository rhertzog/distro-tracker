# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Unit tests for django_email_accounts."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from django_email_accounts.models import User, UserEmail


class UserEmailTests(TestCase):

    def test_user_email_get_or_create_uses_case_insensitive_email(self):
        orig_user_email = UserEmail.objects.create(email='MyEmail@example.net')
        user_email, created = UserEmail.objects.get_or_create(
            email='myemail@example.net')
        self.assertFalse(created)
        self.assertEqual(orig_user_email.pk, user_email.pk)

    def test_user_email_save_does_validation(self):
        user_email = UserEmail(email='foobar')
        with self.assertRaises(ValidationError):
            user_email.save()

    def test_user_email_create_does_validation(self):
        with self.assertRaises(ValidationError):
            UserEmail.objects.create(email='foobar')

    def test_user_email_get_or_create_does_validation(self):
        with self.assertRaises(ValidationError):
            UserEmail.objects.get_or_create(email='foobar')


class RegisterUserTests(TestCase):
    """Test the process of registering a new user."""

    def setUp(self):
        self.email = "user@example.net"

    def get_user_data(self, email="user@example.net"):
        return {
            "main_email": email,
            "first_name": "John",
            "last_name": "Doe",
        }

    def test_create_new_user(self):
        self.client.post(reverse('dtracker-accounts-register'),
                         self.get_user_data())

        user = User.objects.get(main_email=self.email)
        user_email = user.emails.first()
        self.assertEqual(user.main_email, self.email)
        self.assertEqual(user_email.email, self.email)

    def test_create_existing_user_with_different_case(self):
        User.objects.create(main_email="User@example.net")

        self.client.post(
            reverse('dtracker-accounts-register'), self.get_user_data()
        )

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(UserEmail.objects.count(), 1)
        user = User.objects.first()
        self.assertEqual(user.main_email, "User@example.net")
        self.assertEqual(user.emails.first().email, "User@example.net")


class LoginViewTests(TestCase):

    def test_login_redirect_to_next(self):
        """
        Tests if login redirects to the correct page
        """
        username = 'user@domain.com'
        password = 'abcd'
        login_url = reverse('dtracker-accounts-login')
        redirect_url = '/foobar/'

        User.objects.create_user(
            main_email=username, password=password, first_name='', last_name='')
        data = {'username': username, 'password': password}

        # Tests login redirects to the account page by default
        response = self.client.post(login_url, data)
        self.assertRedirects(response, reverse('dtracker-accounts-profile'))

        # Tests that adding a next parameter redirects the page
        url = login_url + '?next=' + redirect_url

        response = self.client.post(url, data)
        self.assertRedirects(
            response, redirect_url, fetch_redirect_response=False)

        # Test that visiting login page after being logged in
        # redirects to profile
        response = self.client.get(login_url)
        self.assertRedirects(
            response, reverse('dtracker-accounts-profile'))
