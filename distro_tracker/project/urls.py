# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""The URL routes for the Distro Tracker project."""

from __future__ import unicode_literals
from django.conf.urls import patterns, include, url
from django.views.generic import TemplateView
from distro_tracker.core.views import PackageSearchView, PackageAutocompleteView
from distro_tracker.core.views import ActionItemJsonView, ActionItemView
from distro_tracker.core.views import KeywordsView
from distro_tracker.core.views import CreateTeamView
from distro_tracker.core.views import TeamDetailsView
from distro_tracker.core.views import DeleteTeamView
from distro_tracker.core.views import UpdateTeamView
from distro_tracker.core.views import AddPackageToTeamView
from distro_tracker.core.views import RemovePackageFromTeamView
from distro_tracker.core.views import JoinTeamView
from distro_tracker.core.views import LeaveTeamView
from distro_tracker.core.views import TeamListView
from distro_tracker.core.views import ManageTeamMembers
from distro_tracker.core.views import RemoveTeamMember
from distro_tracker.core.views import AddTeamMember
from distro_tracker.core.views import ConfirmMembershipView
from distro_tracker.core.views import SetMuteTeamView
from distro_tracker.core.views import SetMembershipKeywords
from distro_tracker.core.views import EditMembershipView
from distro_tracker.core.news_feed import PackageNewsFeed
from distro_tracker.accounts.views import ConfirmAddAccountEmail
from distro_tracker.accounts.views import LoginView
from distro_tracker.accounts.views import AccountMergeFinalize
from distro_tracker.accounts.views import RegisterUser
from distro_tracker.accounts.views import ManageAccountEmailsView
from distro_tracker.accounts.views import ForgotPasswordView
from distro_tracker.accounts.views import ResetPasswordView
from distro_tracker.accounts.views import RegistrationConfirmation
from distro_tracker.accounts.views import AccountProfile
from distro_tracker.accounts.views import SubscriptionsView
from distro_tracker.accounts.views import UserEmailsView
from distro_tracker.accounts.views import SubscribeUserToPackageView
from distro_tracker.accounts.views import LogoutView
from distro_tracker.accounts.views import UnsubscribeUserView
from distro_tracker.accounts.views import UnsubscribeAllView
from distro_tracker.accounts.views import ChooseSubscriptionEmailView
from distro_tracker.accounts.views import ChangePersonalInfoView
from distro_tracker.accounts.views import PasswordChangeView
from distro_tracker.accounts.views import ModifyKeywordsView
from distro_tracker.accounts.views import AccountMergeConfirmView
from distro_tracker.accounts.views import AccountMergeConfirmedView

from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Redirects for the old PTS package page URLs
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)\.html$',
        'distro_tracker.core.views.legacy_package_url_redirect'),

    # Permanent redirect for the old RSS URL
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)/news\.rss20\.xml$',
        'distro_tracker.core.views.legacy_rss_redirect'),

    url(r'^search$', PackageSearchView.as_view(),
        name='pts-package-search'),

    url(r'^api/package/search/autocomplete$', PackageAutocompleteView.as_view(),
        name='pts-api-package-autocomplete'),
    url(r'^api/action-items/(?P<item_pk>\d+)$', ActionItemJsonView.as_view(),
        name='pts-api-action-item'),
    url(r'^api/keywords/$', KeywordsView.as_view(),
        name='pts-api-keywords'),

    url(r'^admin/', include(admin.site.urls)),

    url(r'^news/(?P<news_id>\d+)$', 'distro_tracker.core.views.news_page',
        name='pts-news-page'),
    url(r'^action-items/(?P<item_pk>\d+)$', ActionItemView.as_view(),
        name='pts-action-item'),

    url(r'^$', TemplateView.as_view(template_name='core/index.html'),
        name='pts-index'),

    # Account related URLs
    url(r'^accounts/register/$', RegisterUser.as_view(),
        name='pts-accounts-register'),
    url(r'^accounts/\+reset-password/\+success/$',
        TemplateView.as_view(template_name='accounts/password-reset-success.html'),
        name='pts-accounts-password-reset-success'),
    url(r'^accounts/\+reset-password/(?P<confirmation_key>.+)/$',
        ResetPasswordView.as_view(),
        name='pts-accounts-reset-password'),
    url(r'^accounts/\+forgot-password/$', ForgotPasswordView.as_view(),
        name='pts-accounts-forgot-password'),
    url(r'^accounts/register/success/$',
        TemplateView.as_view(template_name='accounts/success.html'),
        name='pts-accounts-register-success'),
    url(r'^accounts/\+manage-emails/$', ManageAccountEmailsView.as_view(),
        name='pts-accounts-manage-emails'),
    url(r'^accounts/\+confirm-new-email/(?P<confirmation_key>.+)/$',
        ConfirmAddAccountEmail.as_view(),
        name='pts-accounts-confirm-add-email'),
    url(r'^accounts/\+merge-accounts/confirm/$', AccountMergeConfirmView.as_view(),
        name='pts-accounts-merge-confirmation'),
    url(r'^accounts/\+merge-accounts/confirmed/$', AccountMergeConfirmedView.as_view(),
        name='pts-accounts-merge-confirmed'),
    url(r'^accounts/\+merge-accounts/finalize/(?P<confirmation_key>.+)/$', AccountMergeFinalize.as_view(),
        name='pts-accounts-merge-finalize'),
    url(r'^accounts/\+merge-accounts/finalized/$',
        TemplateView.as_view(template_name='accounts/accounts-merge-finalized.html'),
        name='pts-accounts-merge-finalized'),
    url(r'^accounts/confirm/(?P<confirmation_key>[^/]+)$',
        RegistrationConfirmation.as_view(),
        name='pts-accounts-confirm-registration'),
    url(r'^accounts/profile/$',
        AccountProfile.as_view(),
        name='pts-accounts-profile'),
    url(r'^accounts/subscriptions/$',
        SubscriptionsView.as_view(),
        name='pts-accounts-subscriptions'),
    url(r'^accounts/profile/subscriptions/choose-subscription-email/$',
        ChooseSubscriptionEmailView.as_view(),
        name='pts-accounts-choose-email'),
    url(r'^accounts/login/$', LoginView.as_view(),
        name='pts-accounts-login'),
    url(r'^accounts/logout/$', LogoutView.as_view(),
        name='pts-accounts-logout'),
    url(r'^accounts/profile/modify/$', ChangePersonalInfoView.as_view(),
        name='pts-accounts-profile-modify'),
    url(r'^accounts/profile/password-change/$', PasswordChangeView.as_view(),
        name='pts-accounts-profile-password-change'),

    url(r'^api/accounts/profile/emails/$', UserEmailsView.as_view(),
        name='pts-api-accounts-emails'),
    url(r'^api/accounts/profile/subscribe/$', SubscribeUserToPackageView.as_view(),
        name='pts-api-accounts-subscribe'),
    url(r'^api/accounts/profile/unsubscribe/$', UnsubscribeUserView.as_view(),
        name='pts-api-accounts-unsubscribe'),
    url(r'^api/accounts/profile/unsubscribe-all/$', UnsubscribeAllView.as_view(),
        name='pts-api-accounts-unsubscribe-all'),
    url(r'^api/accounts/profile/keywords/$', ModifyKeywordsView.as_view(),
        name='pts-api-accounts-profile-keywords'),
    url(r'^accounts/profile/keywords', ModifyKeywordsView.as_view(),
        name='pts-accounts-profile-keywords'),

    # Team-related URLs
    url(r'^teams/\+create/$', CreateTeamView.as_view(),
        name='pts-teams-create'),
    url(r'^teams/(?P<slug>.+)/\+delete/$', DeleteTeamView.as_view(),
        name='pts-team-delete'),
    url(r'^teams/\+delete-success/$',
        TemplateView.as_view(template_name='core/team-deleted.html'),
        name='pts-team-deleted'),
    url(r'^teams/(?P<slug>.+)/\+update/$', UpdateTeamView.as_view(),
        name='pts-team-update'),
    url(r'^teams/(?P<slug>.+)/\+add-package/$', AddPackageToTeamView.as_view(),
        name='pts-team-add-package'),
    url(r'^teams/(?P<slug>.+)/\+remove-package/$', RemovePackageFromTeamView.as_view(),
        name='pts-team-remove-package'),
    url(r'^teams/(?P<slug>.+)/\+join/$', JoinTeamView.as_view(),
        name='pts-team-join'),
    url(r'^teams/(?P<slug>.+)/\+leave/$', LeaveTeamView.as_view(),
        name='pts-team-leave'),
    url(r'^teams/(?P<slug>.+)/\+add-member/$', AddTeamMember.as_view(),
        name='pts-team-add-member'),
    url(r'^teams/(?P<slug>.+)/\+remove-member/$', RemoveTeamMember.as_view(),
        name='pts-team-remove-member'),
    url(r'^teams/(?P<slug>.+)/\+manage/$', ManageTeamMembers.as_view(),
        name='pts-team-manage'),
    url(r'^teams/$', TeamListView.as_view(),
        name='pts-team-list'),
    url(r'^teams/\+confirm/(?P<confirmation_key>.+)/$', ConfirmMembershipView.as_view(),
        name='pts-team-confirm-membership'),
    url(r'^teams/(?P<slug>.+)/\+mute/$', SetMuteTeamView.as_view(action='mute'),
        name='pts-team-mute'),
    url(r'^teams/(?P<slug>.+)/\+unmute/$', SetMuteTeamView.as_view(action='unmute'),
        name='pts-team-unmute'),
    url(r'^teams/(?P<slug>.+)/\+set-keywords/$', SetMembershipKeywords.as_view(),
        name='pts-team-set-keywords'),
    url(r'^teams/(?P<slug>.+)/\+manage-membership/$', EditMembershipView.as_view(),
        name='pts-team-manage-membership'),
    url(r'^teams/(?P<slug>.+?)/$', TeamDetailsView.as_view(),
        name='pts-team-page'),


    # Dedicated package page
    url(r'^pkg/(?P<package_name>[^/]+)/?$', 'distro_tracker.core.views.package_page',
        name='pts-package-page'),
    # RSS news feed
    url(r'^pkg/(?P<package_name>.+)/rss$', PackageNewsFeed(),
        name='pts-package-rss-news-feed'),

    # The package page view catch all. It must be listed *after* the admin URL so that
    # the admin URL is not interpreted as a package named "admin".
    url(r'^(?P<package_name>[^/]+)/?$', 'distro_tracker.core.views.package_page_redirect',
        name='pts-package-page-redirect'),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
)


from django.conf import settings
if settings.DEBUG:
    urlpatterns = patterns('',
        (r'^media/(?P<path>.*)$',
         'django.views.static.serve', {
            'document_root': settings.MEDIA_ROOT
          }
        ),
        (r'^static/(?P<path>.*)$',
         'django.views.static.serve', {
            'document_root': settings.STATIC_ROOT,
          }
        ),
    ) + urlpatterns
