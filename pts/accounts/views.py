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
from django.views.generic import TemplateView
from django.views.generic.edit import CreateView
from django.views.generic.edit import UpdateView
from django.views.generic.edit import FormView
from django.views.generic.base import View
from django.core.urlresolvers import reverse_lazy
from django.core.urlresolvers import reverse
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.http import HttpResponseForbidden
from django.http import Http404
from django.conf import settings
from pts.accounts.forms import AddEmailToAccountForm
from pts.accounts.forms import UserCreationForm
from pts.accounts.forms import ResetPasswordForm
from pts.accounts.forms import ForgotPasswordForm
from pts.accounts.forms import ChangePersonalInfoForm
from pts.accounts.models import MergeAccountConfirmation
from pts.accounts.models import User
from pts.accounts.models import UserRegistrationConfirmation
from pts.accounts.models import AddEmailConfirmation
from pts.accounts.models import ResetPasswordConfirmation
from pts.core.utils import pts_render_to_string
from pts.core.utils import render_to_json_response
from pts.core.models import Subscription
from pts.core.models import EmailUser
from pts.core.models import Keyword


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
    success_url = reverse_lazy('pts-accounts-profile')
    message = 'You have successfully registered to the PTS'
    confirmation_class = UserRegistrationConfirmation


class ResetPasswordView(SetPasswordMixin, MessageMixin, FormView):
    form_class = ResetPasswordForm
    template_name = 'accounts/registration-reset-password.html'
    success_url = reverse_lazy('pts-accounts-profile')
    message = 'You have successfully reset your password'
    confirmation_class = ResetPasswordConfirmation


class ForgotPasswordView(FormView):
    form_class = ForgotPasswordForm
    success_url = reverse_lazy('pts-accounts-password-reset-success')
    template_name = 'accounts/forgot-password.html'

    def form_valid(self, form):
        # Create a ResetPasswordConfirmation instance
        email = form.cleaned_data['email']
        user = User.objects.get(emails__email=email)
        confirmation = ResetPasswordConfirmation.objects.create_confirmation(user=user)

        # Send a confirmation email
        send_mail(
            'PTS Password Reset Confirmation',
            pts_render_to_string('accounts/password-reset-confirmation-email.txt', {
                'confirmation': confirmation,
            }),
            from_email=settings.PTS_CONTACT_EMAIL,
            recipient_list=[email])

        return super(ForgotPasswordView, self).form_valid(form)


class ChangePersonalInfoView(LoginRequiredMixin, MessageMixin, UpdateView):
    template_name = 'accounts/change-personal-info.html'
    form_class = ChangePersonalInfoForm
    model = User
    success_url = reverse_lazy('pts-accounts-profile-modify')
    message = 'Successfully changed your information'

    def get_object(self, queryset=None):
        return self.request.user


class PasswordChangeView(LoginRequiredMixin, MessageMixin, FormView):
    template_name = 'accounts/password-update.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('pts-accounts-profile-password-change')
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
    """
    form_class = AddEmailToAccountForm
    template_name = 'accounts/profile-manage-emails.html'
    success_url = reverse_lazy('pts-accounts-manage-emails')

    def form_valid(self, form):
        email = form.cleaned_data['email']
        email_user, _ = EmailUser.objects.get_or_create(email=email)
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
                'PTS Add Email To Account',
                pts_render_to_string('accounts/add-email-confirmation-email.txt', {
                    'confirmation': confirmation,
                }),
                from_email=settings.PTS_CONTACT_EMAIL,
                recipient_list=[email])
        elif email_user.user == self.request.user:
            self.message = 'This email is already associated with your account.'
        else:
            # Offer the user to merge the two accounts
            return redirect(reverse('pts-accounts-merge-confirmation') + '?' + urlencode({
                'email': email,
            }))

        return super(ManageAccountEmailsView, self).form_valid(form)


class AccountMergeConfirmView(LoginRequiredMixin, View):
    template_name = 'accounts/account-merge-confirm.html'
    success_url = reverse_lazy('pts-accounts-merge-confirmed')

    def get_email_user(self, query_dict):
        if 'email' not in query_dict:
            raise Http404
        email = query_dict['email']
        email_user = get_object_or_404(EmailUser, email=email)
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
            'PTS Merge Accounts',
            pts_render_to_string('accounts/merge-accounts-confirmation-email.txt', {
                'confirmation': confirmation,
            }),
            from_email=settings.PTS_CONTACT_EMAIL,
            recipient_list=[email_user.email])

        return redirect(self.success_url + '?' + urlencode({
            'email': email_user.email,
        }))


class AccountMergeFinalize(LoginRequiredMixin, View):
    template_name = 'accounts/account-merge-finalize.html'
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
        # Move any teams that the user owns
        merge_with.owned_teams.all().update(owner=initial_user)

        confirmation.delete()

        # The current user is no longer valid
        logout(request)
        # The account is now obsolete and should be removed
        merge_with.delete()

        return redirect('pts-accounts-merge-finalized')


class AccountMergeConfirmedView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/pts-accounts-merge-confirmed.html'

    def get_context_data(self, **kwargs):
        if 'email' not in self.request.GET:
            raise Http404
        email = self.request.GET['email']
        email_user = get_object_or_404(EmailUser, email=email)
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


class SubscriptionsView(LoginRequiredMixin, View):
    """
    Displays a user's subscriptions.

    This includes both direct package subscriptions and team memberships.
    """
    template_name = 'accounts/subscriptions.html'

    def get(self, request):
        user = request.user
        # Map users emails to the subscriptions of that email
        subscriptions = {
            email: {
                'subscriptions': sorted([
                    subscription for subscription in email.subscription_set.all()
                ], key=lambda sub: sub.package.name),
                'team_memberships': sorted([
                    membership for membership in email.membership_set.all()
                ], key=lambda m: m.team.name)
            }
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


class ModifyKeywordsView(LoginRequiredMixin, View):
    """
    Lets the logged in user modify his default keywords or
    subscription-specific keywords.
    """
    def get_keywords(self, keywords):
        """
        :returns: :class:`Keyword <pts.core.models.Keyword>` instances for the
            given keyword names.
        """
        return Keyword.objects.filter(name__in=keywords)

    def modify_default_keywords(self, email, keywords):
        try:
            email_user = self.user.emails.get(email=email)
        except EmailUser.DoesNotExist:
            return HttpResponseForbidden()

        email_user.default_keywords = self.get_keywords(keywords)

        return self.render_response()

    def modify_subscription_keywords(self, email, package, keywords):
        try:
            email_user = self.user.emails.get(email=email)
        except EmailUser.DoesNotExist:
            return HttpResponseForbidden()

        subscription = get_object_or_404(
            Subscription, email_user=email_user, package__name=package)

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
            if 'next' in request.POST:
                return redirect(request.POST['next'])
            else:
                return redirect('pts-index')

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
            email_user = request.user.emails.get(email=email)
        except EmailUser.DoesNotExist:
            return HttpResponseForbidden()

        if 'package' in request.GET:
            package = request.GET['package']
            subscription = get_object_or_404(
                Subscription, email_user=email_user, package__name=package)
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
                'user_keywords': email_user.default_keywords.all(),
            }

        context.update({
            'keywords': Keyword.objects.order_by('name').all(),
            'email': email,
        })

        return render(request, 'accounts/modify-subscription.html', context)
