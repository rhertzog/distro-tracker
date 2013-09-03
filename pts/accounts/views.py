# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Views for the :mod:`pts.accounts` app."""
from __future__ import unicode_literals
from django.views.generic.edit import CreateView
from django.views.generic.edit import FormView
from django.views.generic.base import View
from django.core.urlresolvers import reverse_lazy
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.http import HttpResponseForbidden
from django.http import Http404
from django.conf import settings
from pts.accounts.forms import UserCreationForm
from pts.accounts.forms import ResetPasswordForm
from pts.accounts.models import User
from pts.accounts.models import UserRegistrationConfirmation
from pts.core.utils import pts_render_to_string
from pts.core.utils import render_to_json_response
from pts.core.models import Subscription


class RegisterUser(CreateView):
    template_name = 'accounts/register.html'
    model = User
    success_url = reverse_lazy('pts-accounts-register-success')

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
            'PTS Registration Confirmation',
            pts_render_to_string('accounts/registration-confirmation-email.txt', {
                'confirmation': confirmation,
            }),
            from_email=settings.PTS_CONTACT_EMAIL,
            recipient_list=[user.main_email])


class RegistrationConfirmation(FormView):
    form_class = ResetPasswordForm
    template_name = 'accounts/registration-confirmation.html'
    success_url = reverse_lazy('pts-accounts-profile')

    def post(self, request, confirmation_key):
        self.confirmation = get_object_or_404(
            UserRegistrationConfirmation,
            confirmation_key=confirmation_key)
        return super(RegistrationConfirmation, self).post(
            self, request, confirmation_key)

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

        messages.success(
            self.request, 'You have successfully registered to the PTS')

        return super(RegistrationConfirmation, self).form_valid(form)

    def get(self, request, confirmation_key):
        self.confirmation = get_object_or_404(
            UserRegistrationConfirmation,
            confirmation_key=confirmation_key)
        return super(RegistrationConfirmation, self).get(request,confirmation_key)


class LoginRequiredMixin(object):
    """
    A view mixin which makes sure that the user is logged in before accessing
    the view.
    """
    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(LoginRequiredMixin, self).dispatch(*args, **kwargs)


class AccountProfile(LoginRequiredMixin, View):
    template_name = 'accounts/profile.html'

    def get(self, request):
        return render(request, self.template_name, {
            'user': request.user,
        })


class SubscriptionsView(LoginRequiredMixin, View):
    """
    Displays a user's subscriptions.
    """
    template_name = 'accounts/subscriptions.html'

    def get(self, request):
        user = request.user
        # Map users emails to the subscriptions of that email
        subscriptions = {
            email: sorted([
                subscription for subscription in email.subscription_set.all()
            ], key=lambda sub: sub.package.name)
            for email in user.emails.all()
        }
        return render(request, self.template_name, {
            'subscriptions': subscriptions,
        })


class UserEmailsView(LoginRequiredMixin, View):
    """
    Returns a JSON encoded list of the currently logged in user's emails.
    """
    def get(self, request):
        user = request.user
        return render_to_json_response([
            email.email for email in user.emails.all()
        ])


class SubscribeUserToPackageView(LoginRequiredMixin, View):
    """
    Subscribes the user to a package.

    The user whose email address is provided must currently be logged in.
    """
    def post(self, request):
        package = request.POST.get('package', None)
        emails = request.POST.getlist('email', None)

        if not package or not emails:
            raise Http404

        # Check whether the logged in user is associated with the given emails
        users_emails = [e.email for e in request.user.emails.all()]
        for email in emails:
            if email not in users_emails:
                return HttpResponseForbidden()

        # Create the subscriptions
        for email in emails:
            Subscription.objects.create_for(
                package_name=package,
                email=email)

        if request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            next = request.POST.get('next', None)
            if not next:
                return redirect('pts-package-page', package_name=package)
            return redirect(next)


class UnsubscribeUserView(LoginRequiredMixin, View):
    """
    Unsubscribes the currently logged in user from the given package.
    An email can be optionally provided in which case only the given email is
    unsubscribed from the package, if the logged in user owns it.
    """
    def post(self, request):
        if 'package' not in request.POST:
            raise Http404

        package = request.POST['package']
        user = request.user

        if 'email' not in request.POST:
            # Unsubscribe all the user's emails from the package
            qs = Subscription.objects.filter(
                email_user__in=user.emails.all(),
                package__name=package)
        else:
            # Unsubscribe only the given email from the package
            qs = Subscription.objects.filter(
                email_user__email=request.POST['email'],
                package__name=package)

        qs.delete()

        if request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            if 'next' in request.POST:
                return redirect(request.POST['next'])
            else:
                return redirect('pts-package-page', package_name=package)


class UnsubscribeAllView(LoginRequiredMixin, View):
    """
    The view unsubscribes the currently logged in user from all packages.
    If an optional ``email`` POST parameter is provided, only removes all
    subscriptions for the given emails.
    """
    def post(self, request):
        user = request.user
        if 'email' not in request.POST:
            emails = user.emails.all()
        else:
            emails = user.emails.filter(email__in=request.POST.getlist('email'))

        # Remove all the subscriptions
        Subscription.objects.filter(email_user__in=emails).delete()

        if request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            if 'next' in request.POST:
                return redirect(request.POST['next'])
            else:
                return redirect('pts-index')


class ChooseSubscriptionEmailView(LoginRequiredMixin, View):
    """
    Lets the user choose which email to subscribe to a package with.
    This is an alternative view when JS is disabled and the appropriate choice
    cannot be offered in a popup.
    """
    template_name = 'accounts/choose-email.html'
    def get(self, request):
        if 'package' not in request.GET:
            raise Http404

        return render(request, self.template_name, {
            'package': request.GET['package'],
            'emails': request.user.emails.all(),
        })
