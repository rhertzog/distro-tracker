# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Views for the :mod:`distro_tracker.accounts` app."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden
)
from django.shortcuts import get_object_or_404, render, resolve_url
from django.urls import reverse_lazy
from django.utils.html import format_html
from django.views.generic.base import View

from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import (
    EmailSettings,
    Keyword,
    Subscription,
    get_web_package
)
from distro_tracker.core.utils import (
    distro_tracker_render_to_string,
    render_to_json_response
)
from distro_tracker.core.utils.http import safe_redirect

from django_email_accounts import views as email_accounts_views
from django_email_accounts.views import LoginRequiredMixin


class ConfirmationRenderMixin(object):
    def get_confirmation_email_content(self, confirmation):
        return distro_tracker_render_to_string(
            self.confirmation_email_template,
            {'confirmation': confirmation}
        )


class LoginView(email_accounts_views.LoginView):
    success_url = reverse_lazy('dtracker-accounts-profile')


class LogoutView(email_accounts_views.LogoutView):
    success_url = reverse_lazy('dtracker-index')


class RegisterUser(ConfirmationRenderMixin, email_accounts_views.RegisterUser):
    success_url = reverse_lazy('dtracker-accounts-register-success')

    confirmation_email_subject = '{name} Registration Confirmation'.format(
        name=settings.GET_INSTANCE_NAME())
    confirmation_email_from_address = settings.DISTRO_TRACKER_CONTACT_EMAIL


class RegistrationConfirmation(email_accounts_views.RegistrationConfirmation):
    success_url = reverse_lazy('dtracker-accounts-profile')
    message = 'You have successfully registered to the {name}'.format(
        name=settings.GET_INSTANCE_NAME())


class ResetPasswordView(ConfirmationRenderMixin,
                        email_accounts_views.ResetPasswordView):
    success_url = reverse_lazy('dtracker-accounts-profile')


class ForgotPasswordView(ConfirmationRenderMixin,
                         email_accounts_views.ForgotPasswordView):
    success_url = reverse_lazy('dtracker-accounts-password-reset-success')
    email_subject = '{name} Password Reset Confirmation'.format(
        name=settings.GET_INSTANCE_NAME())
    email_from_address = settings.DISTRO_TRACKER_CONTACT_EMAIL


class ChangePersonalInfoView(email_accounts_views.ChangePersonalInfoView):
    success_url = reverse_lazy('dtracker-accounts-profile-modify')


class PasswordChangeView(email_accounts_views.PasswordChangeView):
    success_url = reverse_lazy('dtracker-accounts-profile-password-change')


class AccountProfile(email_accounts_views.AccountProfile):
    pass


class ManageAccountEmailsView(ConfirmationRenderMixin,
                              email_accounts_views.ManageAccountEmailsView):
    success_url = reverse_lazy('dtracker-accounts-manage-emails')
    merge_accounts_url = reverse_lazy('dtracker-accounts-merge-confirmation')

    confirmation_email_subject = 'Add Email To {name} Account'.format(
        name=settings.GET_INSTANCE_NAME())
    confirmation_email_from_address = settings.DISTRO_TRACKER_CONTACT_EMAIL


class AccountMergeConfirmView(ConfirmationRenderMixin,
                              email_accounts_views.AccountMergeConfirmView):
    success_url = reverse_lazy('dtracker-accounts-merge-confirmed')
    confirmation_email_subject = 'Merge {name} Accounts'.format(
        name=settings.GET_INSTANCE_NAME())
    confirmation_email_from_address = settings.DISTRO_TRACKER_CONTACT_EMAIL


class AccountMergeFinalize(email_accounts_views.AccountMergeFinalize):
    success_url = reverse_lazy('dtracker-accounts-merge-finalized')


class AccountMergeConfirmedView(email_accounts_views.AccountMergeConfirmedView):
    template_name = 'accounts/tracker-accounts-merge-confirmed.html'


class ConfirmAddAccountEmail(email_accounts_views.ConfirmAddAccountEmail):
    pass


class SubscriptionsView(LoginRequiredMixin, View):
    """
    Displays a user's subscriptions.

    This includes both direct package subscriptions and team memberships.
    """
    template_name = 'accounts/subscriptions.html'

    def get(self, request):
        user = request.user
        keyword_qs = Keyword.objects.order_by('name')
        user_emails = UserEmail.objects.filter(user=user).order_by(
            'email'
        ).prefetch_related(
            Prefetch(
                'emailsettings__subscription_set___keywords',
                queryset=keyword_qs
            ),
            Prefetch(
                'emailsettings__default_keywords',
                queryset=keyword_qs
            )
        )
        # Map users emails to the subscriptions of that email
        for user_email in user_emails:
            EmailSettings.objects.get_or_create(user_email=user_email)
        subscriptions = [
            {
                'email': user_email,
                'subscriptions': sorted([
                    subscription for subscription
                    in user_email.emailsettings.subscription_set.all()
                ], key=lambda sub: sub.package.name),
                'team_memberships': sorted([
                    membership for membership in user_email.membership_set.all()
                ], key=lambda m: m.team.name)
            }
            for user_email in user_emails
        ]
        # Initializing session variable if not set.
        request.session.setdefault('selected_emails', [str(user_emails[0])])
        return render(request, self.template_name, {
            'subscriptions': subscriptions,
            'selected_emails': request.session['selected_emails']
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

        # Remember selected emails via session variable
        request.session['selected_emails'] = emails

        # Check whether the logged in user is associated with the given emails
        users_emails = [e.email for e in request.user.emails.all()]
        for email in emails:
            if email not in users_emails:
                return HttpResponseForbidden()

        _pkg = get_web_package(package)
        _err = None

        if _pkg:
            try:
                for email in emails:
                    Subscription.objects.create_for(
                        package_name=package,
                        email=email)
            except ValidationError as e:
                _err = e.message
        else:
            _err = format_html(
                "Package {pkg} does not exist.",
                pkg=package,
            )

        if request.is_ajax():
            json_result = {'status': 'ok'}
            if _err is not None:
                json_result = {
                    'status': 'failed',
                    'error': _err,
                }
            return render_to_json_response(json_result)
        else:
            if _err:
                return HttpResponseBadRequest(_err)
            _next = request.POST.get('next', None)
            return safe_redirect(
                _next,
                resolve_url('dtracker-package-page', package_name=package),
            )


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
            user_emails = UserEmail.objects.filter(user=user)
            qs = Subscription.objects.filter(
                email_settings__user_email__in=user_emails,
                package__name=package)
        else:
            # Unsubscribe only the given email from the package
            qs = Subscription.objects.filter(
                email_settings__user_email__email=request.POST['email'],
                package__name=package)

        qs.delete()

        if request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            _next = request.POST.get('next', None)
            return safe_redirect(
                _next,
                resolve_url('dtracker-package-page', package_name=package),
            )


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
        Subscription.objects.filter(
            email_settings__user_email__in=emails).delete()

        if request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            _next = request.POST.get('next', None)
            return safe_redirect(
                _next,
                resolve_url('dtracker-index'),
            )


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

        if not get_web_package(request.GET['package']):
            raise Http404

        return render(request, self.template_name, {
            'package': request.GET['package'],
            'emails': request.user.emails.all(),
        })


class ModifyKeywordsView(LoginRequiredMixin, View):
    """
    Lets the logged-in user modify their default keywords or
    subscription-specific keywords.
    """
    def get_keywords(self, keywords):
        """
        :returns: :class:`Keyword <distro_tracker.core.models.Keyword>`
            instances for the given keyword names.
        """
        return Keyword.objects.filter(name__in=keywords)

    def modify_default_keywords(self, email, keywords):
        try:
            user_email = UserEmail.objects.get(user=self.user, email=email)
        except (UserEmail.DoesNotExist):
            return HttpResponseForbidden()

        email_settings, _ = \
            EmailSettings.objects.get_or_create(user_email=user_email)
        email_settings.default_keywords.set(self.get_keywords(keywords))

        return self.render_response()

    def modify_subscription_keywords(self, email, package, keywords):
        try:
            user_email = UserEmail.objects.get(user=self.user, email=email)
        except (UserEmail.DoesNotExist):
            return HttpResponseForbidden()

        email_settings, _ = \
            EmailSettings.objects.get_or_create(user_email=user_email)
        subscription = get_object_or_404(
            Subscription, email_settings__user_email=user_email,
            package__name=package)

        subscription.keywords.clear()
        for keyword in self.get_keywords(keywords):
            subscription.keywords.add(keyword)

        return self.render_response()

    def render_response(self):
        if self.request.is_ajax():
            return render_to_json_response({
                'status': 'ok',
            })
        else:
            _next = self.request.POST.get('next', None)
            return safe_redirect(
                _next,
                resolve_url('dtracker-index'),
            )

    def post(self, request):
        if 'email' not in request.POST or 'keyword[]' not in request.POST:
            raise Http404

        self.user = request.user
        self.request = request
        email = request.POST['email']
        keywords = request.POST.getlist('keyword[]')

        if 'package' in request.POST:
            return self.modify_subscription_keywords(
                email, request.POST['package'], keywords)
        else:
            return self.modify_default_keywords(email, keywords)

    def get(self, request):
        if 'email' not in request.GET:
            raise Http404
        email = request.GET['email']

        try:
            user_email = request.user.emails.get(email=email)
        except UserEmail.DoesNotExist:
            return HttpResponseForbidden()

        if 'package' in request.GET:
            package = request.GET['package']
            subscription = get_object_or_404(
                Subscription, email_settings__user_email=user_email,
                package__name=package)
            context = {
                'post': {
                    'email': email,
                    'package': package,
                },
                'package': package,
                'user_keywords': subscription.keywords.all(),
            }
        else:
            context = {
                'post': {
                    'email': email,
                },
                'user_keywords':
                    user_email.emailsettings.default_keywords.all(),
            }

        context.update({
            'keywords': Keyword.objects.order_by('name').all(),
            'email': email,
        })

        return render(request, 'accounts/modify-subscription.html', context)
