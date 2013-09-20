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
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.utils.decorators import method_decorator
from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.views.generic.base import View
from django.views.generic.edit import CreateView
from django.views.generic.edit import UpdateView
from django.views.generic.edit import FormView
from django.views.generic import TemplateView
from django.utils.http import urlencode
from django.core.urlresolvers import reverse_lazy
from django.template.loader import render_to_string
from django_email_accounts.models import User
from django_email_accounts.models import UserEmail
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.contrib.auth.forms import PasswordChangeForm
from django.http import Http404

from django_email_accounts.forms import (
    AddEmailToAccountForm,
    UserCreationForm,
    ResetPasswordForm,
    ForgotPasswordForm,
    ChangePersonalInfoForm,
)
from django_email_accounts.models import (
    MergeAccountConfirmation,
    UserRegistrationConfirmation,
    AddEmailConfirmation,
    ResetPasswordConfirmation,
)
from django_email_accounts import run_hook





class RegisterUser(CreateView):
    """
    Provides a view that displays a registration form on a GET request and
    registers the user on a POST.

    ``template_name`` and ``success_url`` properties can be overridden when
    instantiating the view in order to customize the page displayed on a GET
    request and the URL to which the user should be redirected after a
    successful POST, respectively.

    Additionally, by overriding the ``confirmation_email_template`` and
    ``confirmation_email_subject`` it is possible to customize the subject and
    content of a confirmation email sent to the user being registered.

    Instead of providing a ``confirmation_email_template`` you may also override
    the :meth:`get_confirmation_email_content` to provide a custom rendered
    text content.

    The sender of the email can be changed by modifying the
    ``confirmation_email_from_address`` setting.
    """
    template_name = 'accounts/register.html'
    model = User
    success_url = reverse_lazy('accounts-register-success')

    confirmation_email_template = 'accounts/registration-confirmation-email.txt'
    confirmation_email_subject = 'Registration Confirmation'
    confirmation_email_from_address = settings.DEFAULT_FROM_EMAIL

    def get_confirmation_email_content(self, confirmation):
        return render_to_string(self.confirmation_email_template, {
            'confirmation': confirmation,
        })

    def get_form_class(self):
        return UserCreationForm

    def form_valid(self, form):
        response = super(RegisterUser, self).form_valid(form)
        self.send_confirmation_mail(form.instance)

        return response

    def send_confirmation_mail(self, user):
        """
        Sends a confirmation email to the user. The user is inactive until the
        email is confirmed by clicking a URL found in the email.
        """
        confirmation = UserRegistrationConfirmation.objects.create_confirmation(
            user=user)

        send_mail(
            self.confirmation_email_subject,
            self.get_confirmation_email_content(confirmation),
            from_email=self.confirmation_email_from_address,
            recipient_list=[user.main_email])


class LoginRequiredMixin(object):
    """
    A view mixin which makes sure that the user is logged in before accessing
    the view.
    """
    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(LoginRequiredMixin, self).dispatch(*args, **kwargs)


class MessageMixin(object):
    """
    A View mixin which adds a success info message to the list of messages
    managed by the :mod:`django.contrib.message` framework in case a form has
    been successfully processed.

    The message which is added is retrieved by calling the :meth:`get_message`
    method. Alternatively, a :attr:`message` attribute can be set if no
    calculations are necessary.
    """
    def form_valid(self, *args, **kwargs):
        message = self.get_message()
        if message:
            messages.info(self.request, message)
        return super(MessageMixin, self).form_valid(*args, **kwargs)

    def get_message(self):
        if self.message:
            return self.message


class SetPasswordMixin(object):
    def form_valid(self, form):
        user = self.confirmation.user
        user.is_active = True
        password = form.cleaned_data['password1']
        user.set_password(password)
        user.save()

        # The confirmation key is no longer needed
        self.confirmation.delete()

        # Log the user in
        user = authenticate(username=user.main_email, password=password)
        login(self.request, user)

        return super(SetPasswordMixin, self).form_valid(form)

    def get_confirmation_instance(self, confirmation_key):
        self.confirmation = get_object_or_404(
            self.confirmation_class,
            confirmation_key=confirmation_key)
        return self.confirmation

    def post(self, request, confirmation_key):
        self.get_confirmation_instance(confirmation_key)
        return super(SetPasswordMixin, self).post(request, confirmation_key)

    def get(self, request, confirmation_key):
        self.get_confirmation_instance(confirmation_key)
        return super(SetPasswordMixin, self).get(request, confirmation_key)


class RegistrationConfirmation(SetPasswordMixin, MessageMixin, FormView):
    form_class = ResetPasswordForm
    template_name = 'accounts/registration-confirmation.html'
    success_url = reverse_lazy('accounts-profile')
    message = 'You have successfully registered'
    confirmation_class = UserRegistrationConfirmation


class ResetPasswordView(SetPasswordMixin, MessageMixin, FormView):
    form_class = ResetPasswordForm
    template_name = 'accounts/registration-reset-password.html'
    success_url = reverse_lazy('accounts-profile')
    message = 'You have successfully reset your password'
    confirmation_class = ResetPasswordConfirmation


class ForgotPasswordView(FormView):
    form_class = ForgotPasswordForm
    success_url = reverse_lazy('accounts-password-reset-success')
    template_name = 'accounts/forgot-password.html'

    confirmation_email_template = 'accounts/password-reset-confirmation-email.txt'
    confirmation_email_subject = 'Password Reset Confirmation'
    confirmation_email_from_address = settings.DEFAULT_FROM_EMAIL

    def get_confirmation_email_content(self, confirmation):
        return render_to_string(self.confirmation_email_template, {
            'confirmation': confirmation,
        })

    def form_valid(self, form):
        # Create a ResetPasswordConfirmation instance
        email = form.cleaned_data['email']
        user = User.objects.get(emails__email=email)
        confirmation = ResetPasswordConfirmation.objects.create_confirmation(user=user)

        # Send a confirmation email
        send_mail(
            self.confirmation_email_subject,
            self.get_confirmation_email_content(confirmation),
            from_email=self.confirmation_email_from_address,
            recipient_list=[email])

        return super(ForgotPasswordView, self).form_valid(form)


class ChangePersonalInfoView(LoginRequiredMixin, MessageMixin, UpdateView):
    template_name = 'accounts/change-personal-info.html'
    form_class = ChangePersonalInfoForm
    model = User
    success_url = reverse_lazy('accounts-profile-modify')
    message = 'Successfully changed your information'

    def get_object(self, queryset=None):
        return self.request.user


class PasswordChangeView(LoginRequiredMixin, MessageMixin, FormView):
    template_name = 'accounts/password-update.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('accounts-profile-password-change')
    message = 'Successfully updated your password'

    def get_form_kwargs(self):
        kwargs = super(PasswordChangeView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form, *args, **kwargs):
        form.save()
        return super(PasswordChangeView, self).form_valid(form, *args, **kwargs)


class AccountProfile(LoginRequiredMixin, View):
    template_name = 'accounts/profile.html'

    def get(self, request):
        return render(request, self.template_name, {
            'user': request.user,
        })


class ManageAccountEmailsView(LoginRequiredMixin, MessageMixin, FormView):
    """
    Render a page letting users add or remove emails to their accounts.

    Apart from the ``success_url``, a ``merge_accounts_url`` can be provided,
    if the name of the view is to differ from ``accounts-merge-confirmation``
    """
    form_class = AddEmailToAccountForm
    template_name = 'accounts/profile-manage-emails.html'
    success_url = reverse_lazy('accounts-manage-emails')
    merge_accounts_url = reverse_lazy('accounts-merge-confirmation')

    confirmation_email_template = 'accounts/add-email-confirmation-email.txt'
    confirmation_email_subject = 'Add Email To Account'
    confirmation_email_from_address = settings.DEFAULT_FROM_EMAIL

    def get_confirmation_email_content(self, confirmation):
        return render_to_string(self.confirmation_email_template, {
            'confirmation': confirmation,
        })

    def form_valid(self, form):
        email = form.cleaned_data['email']
        email_user, _ = UserEmail.objects.get_or_create(email=email)
        if not email_user.user:
            # The email is not associated with an account yet.
            # Ask for confirmation to add it to this account.
            confirmation = AddEmailConfirmation.objects.create_confirmation(
                user=self.request.user,
                email=email_user)
            self.message = (
                'Before the email is associated with this account, '
                'you must follow the confirmation link sent to the address'
            )
            # Send a confirmation email
            send_mail(
                self.confirmation_email_subject,
                self.get_confirmation_email_content(confirmation),
                from_email=self.confirmation_email_from_address,
                recipient_list=[email])
        elif email_user.user == self.request.user:
            self.message = 'This email is already associated with your account.'
        else:
            # Offer the user to merge the two accounts
            return redirect(self.merge_accounts_url + '?' + urlencode({
                'email': email,
            }))

        return super(ManageAccountEmailsView, self).form_valid(form)


class AccountMergeConfirmView(LoginRequiredMixin, View):
    template_name = 'accounts/account-merge-confirm.html'
    success_url = reverse_lazy('accounts-merge-confirmed')

    confirmation_email_template = 'accounts/merge-accounts-confirmation-email.txt'
    confirmation_email_subject = 'Merge Accounts'
    confirmation_email_from_address = settings.DEFAULT_FROM_EMAIL

    def get_confirmation_email_content(self, confirmation):
        return render_to_string(self.confirmation_email_template, {
            'confirmation': confirmation,
        })

    def get_email_user(self, query_dict):
        if 'email' not in query_dict:
            raise Http404
        email = query_dict['email']
        email_user = get_object_or_404(UserEmail, email=email)
        return email_user

    def get(self, request):
        self.request = request
        email_user = self.get_email_user(self.request.GET)

        return render(request, self.template_name, {
            'email_user': email_user,
        })

    def post(self, request):
        self.request = request

        email_user = self.get_email_user(self.request.POST)
        if not email_user.user or email_user.user == self.request.user:
            pass

        # Send a confirmation mail
        confirmation = MergeAccountConfirmation.objects.create_confirmation(
            initial_user=self.request.user,
            merge_with=email_user.user)
        send_mail(
            self.confirmation_email_subject,
            self.get_confirmation_email_content(confirmation),
            from_email=self.confirmation_email_from_address,
            recipient_list=[email_user.email])

        return redirect(self.success_url + '?' + urlencode({
            'email': email_user.email,
        }))


class AccountMergeFinalize(LoginRequiredMixin, View):
    template_name = 'accounts/account-merge-finalize.html'
    success_url = reverse_lazy('accounts-merge-finalized')

    def get(self, request, confirmation_key):
        confirmation = get_object_or_404(
            MergeAccountConfirmation,
            confirmation_key=confirmation_key)

        if confirmation.merge_with != request.user:
            raise PermissionDenied

        return render(request, self.template_name, {
            'confirmation': confirmation,
        })

    def post(self, request, confirmation_key):
        confirmation = get_object_or_404(
            MergeAccountConfirmation,
            confirmation_key=confirmation_key)
        if confirmation.merge_with != request.user:
            raise PermissionDenied

        initial_user = confirmation.initial_user
        merge_with = confirmation.merge_with

        # Move emails
        for email in merge_with.emails.all():
            initial_user.emails.add(email)

        # Run a post merge hook
        run_hook('post-merge', initial_user, merge_with)

        confirmation.delete()

        # The current user is no longer valid
        logout(request)
        # The account is now obsolete and should be removed
        merge_with.delete()

        return redirect(self.success_url)


class AccountMergeConfirmedView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/accounts-merge-confirmed.html'

    def get_context_data(self, **kwargs):
        if 'email' not in self.request.GET:
            raise Http404
        email = self.request.GET['email']
        email_user = get_object_or_404(UserEmail, email=email)
        context = super(AccountMergeConfirmedView, self).get_context_data(**kwargs)
        context['email'] = email_user

        return context


class ConfirmAddAccountEmail(View):
    template_name = 'accounts/new-email-added.html'

    def get(self, request, confirmation_key):
        confirmation = get_object_or_404(
            AddEmailConfirmation,
            confirmation_key=confirmation_key)
        user = confirmation.user
        email_user = confirmation.email
        confirmation.delete()
        # If the email has become associated with a different user in the mean
        # time, abort the operation.
        if email_user.user and email_user.user != user:
            raise PermissionDenied
        email_user.user = user
        email_user.save()

        return render(request, self.template_name, {
            'new_email': email_user,
        })
