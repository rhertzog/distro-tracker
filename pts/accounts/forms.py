# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Forms for the :mod:`pts.accounts` app."""
from __future__ import unicode_literals
from django import forms
from pts.accounts.models import User
from pts.accounts.models import UserEmail


class UserCreationForm(forms.ModelForm):
    """
    A form for creating a PTS user (:class:`User <pts.accounts.models.User>`).

    The created user has no privileges and its account is inactive until
    a confirmation link is followed.
    """
    class Meta:
        model = User
        fields = (
            'main_email',
            'first_name',
            'last_name',
        )

    def clean_main_email(self):
        main_email = self.cleaned_data['main_email']
        # Check whether a different user is already associated with this
        # email address.
        try:
            email_user = UserEmail.objects.get(email=main_email)
        except UserEmail.DoesNotExist:
            return main_email

        if email_user.user is not None:
            raise forms.ValidationError('The email address is already in use')

        return main_email

    def save(self, *args, **kwargs):
        user = super(UserCreationForm, self).save(commit=True)
        email, _ = UserEmail.objects.get_or_create(email=user.main_email)
        user.emails.add(email)
        user.save()

        return user


class ResetPasswordForm(forms.Form):
    """
    A form for resetting a user's password.

    The user must provide a new password and confirm the new password in
    a separate field.
    """
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput())

    password2 = forms.CharField(
        label='Repeat password',
        widget=forms.PasswordInput())

    def clean_password2(self):
        password1 = self.cleaned_data['password1']
        password2 = self.cleaned_data['password2']

        if password1 != password2:
            raise forms.ValidationError("The two passwords do not match.")

        return password2


class ChangePersonalInfoForm(forms.ModelForm):
    """
    A form providing a way for the user to change his account's personal info.
    """
    class Meta:
        model = User
        fields = ['first_name', 'last_name']


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField()

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(emails__email=email).count() == 0:
            raise forms.ValidationError("No user with the given email is registered")

        return email


class AddEmailToAccountForm(forms.Form):
    email = forms.EmailField()
