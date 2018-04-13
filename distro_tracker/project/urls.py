# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""The URL routes for the Distro Tracker project."""


import importlib

from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from distro_tracker.accounts.views import (
    AccountMergeConfirmedView,
    AccountMergeConfirmView,
    AccountMergeFinalize,
    AccountProfile,
    ChangePersonalInfoView,
    ChooseSubscriptionEmailView,
    ConfirmAddAccountEmail,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    ManageAccountEmailsView,
    ModifyKeywordsView,
    PasswordChangeView,
    RegisterUser,
    RegistrationConfirmation,
    ResetPasswordView,
    SubscribeUserToPackageView,
    SubscriptionsView,
    UnsubscribeAllView,
    UnsubscribeUserView,
    UserEmailsView
)
from distro_tracker.core.news_feed import PackageNewsFeed
from distro_tracker.core.views import (
    ActionItemJsonView,
    ActionItemView,
    AddPackageToTeamView,
    AddTeamMember,
    ConfirmMembershipView,
    CreateTeamView,
    DeleteTeamView,
    EditMembershipView,
    IndexView,
    JoinTeamView,
    KeywordsView,
    LeaveTeamView,
    ManageTeamMembers,
    OpenSearchDescription,
    PackageAutocompleteView,
    PackageNews,
    PackageSearchView,
    TeamAutocompleteView,
    TeamSearchView,
    RemovePackageFromTeamView,
    RemoveTeamMember,
    SetMembershipKeywords,
    SetMuteTeamView,
    TeamDetailsView,
    TeamListView,
    UpdateTeamView,
    legacy_package_url_redirect,
    legacy_rss_redirect,
    news_page,
    package_page,
    package_page_redirect
)

admin.autodiscover()

urlpatterns = [
    # Redirects for the old PTS package page URLs
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)\.html$',
        legacy_package_url_redirect),

    # Permanent redirect for the old RSS URL
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)'
        r'/news\.rss20\.xml$',
        legacy_rss_redirect),

    url(r'^search$', PackageSearchView.as_view(),
        name='dtracker-package-search'),
    url(r'^search.xml$', OpenSearchDescription.as_view(),
        name='dtracker-opensearch-description'),
    url(r'^favicon.ico$',
        lambda r: redirect(settings.STATIC_URL + 'favicon.ico'),
        name='dtracker-favicon'),

    url(r'^api/package/search/autocomplete$', PackageAutocompleteView.as_view(),
        name='dtracker-api-package-autocomplete'),
    url(r'^api/action-items/(?P<item_pk>\d+)$', ActionItemJsonView.as_view(),
        name='dtracker-api-action-item'),
    url(r'^api/keywords/$', KeywordsView.as_view(),
        name='dtracker-api-keywords'),

    url(r'^admin/', admin.site.urls),

    url(r'^news/(?P<news_id>\d+)/?$', news_page,
        name='dtracker-news-page'),
    url(r'^news/(?P<news_id>\d+)/(?P<slug>.+)/$', news_page,
        name='dtracker-news-page'),
    url(r'^action-items/(?P<item_pk>\d+)$', ActionItemView.as_view(),
        name='dtracker-action-item'),

    url(r'^$', IndexView.as_view(), name='dtracker-index'),

    # Account related URLs
    url(r'^accounts/register/$', RegisterUser.as_view(),
        name='dtracker-accounts-register'),
    url(r'^accounts/\+reset-password/\+success/$',
        TemplateView.as_view(
            template_name='accounts/password-reset-success.html'),
        name='dtracker-accounts-password-reset-success'),
    url(r'^accounts/\+reset-password/(?P<confirmation_key>.+)/$',
        ResetPasswordView.as_view(),
        name='dtracker-accounts-reset-password'),
    url(r'^accounts/\+forgot-password/$', ForgotPasswordView.as_view(),
        name='dtracker-accounts-forgot-password'),
    url(r'^accounts/register/success/$',
        TemplateView.as_view(template_name='accounts/success.html'),
        name='dtracker-accounts-register-success'),
    url(r'^accounts/\+manage-emails/$', ManageAccountEmailsView.as_view(),
        name='dtracker-accounts-manage-emails'),
    url(r'^accounts/\+confirm-new-email/(?P<confirmation_key>.+)/$',
        ConfirmAddAccountEmail.as_view(),
        name='dtracker-accounts-confirm-add-email'),
    url(r'^accounts/\+merge-accounts/confirm/$',
        AccountMergeConfirmView.as_view(),
        name='dtracker-accounts-merge-confirmation'),
    url(r'^accounts/\+merge-accounts/confirmed/$',
        AccountMergeConfirmedView.as_view(),
        name='dtracker-accounts-merge-confirmed'),
    url(r'^accounts/\+merge-accounts/finalize/(?P<confirmation_key>.+)/$',
        AccountMergeFinalize.as_view(),
        name='dtracker-accounts-merge-finalize'),
    url(r'^accounts/\+merge-accounts/finalized/$',
        TemplateView.as_view(
            template_name='accounts/accounts-merge-finalized.html'),
        name='dtracker-accounts-merge-finalized'),
    url(r'^accounts/confirm/(?P<confirmation_key>[^/]+)$',
        RegistrationConfirmation.as_view(),
        name='dtracker-accounts-confirm-registration'),
    url(r'^accounts/profile/$',
        AccountProfile.as_view(),
        name='dtracker-accounts-profile'),
    url(r'^accounts/subscriptions/$',
        SubscriptionsView.as_view(),
        name='dtracker-accounts-subscriptions'),
    url(r'^accounts/profile/subscriptions/choose-subscription-email/$',
        ChooseSubscriptionEmailView.as_view(),
        name='dtracker-accounts-choose-email'),
    url(r'^accounts/login/$', LoginView.as_view(),
        name='dtracker-accounts-login'),
    url(r'^accounts/logout/$', LogoutView.as_view(),
        name='dtracker-accounts-logout'),
    url(r'^accounts/profile/modify/$', ChangePersonalInfoView.as_view(),
        name='dtracker-accounts-profile-modify'),
    url(r'^accounts/profile/password-change/$', PasswordChangeView.as_view(),
        name='dtracker-accounts-profile-password-change'),

    url(r'^api/accounts/profile/emails/$', UserEmailsView.as_view(),
        name='dtracker-api-accounts-emails'),
    url(r'^api/accounts/profile/subscribe/$',
        SubscribeUserToPackageView.as_view(),
        name='dtracker-api-accounts-subscribe'),
    url(r'^api/accounts/profile/unsubscribe/$', UnsubscribeUserView.as_view(),
        name='dtracker-api-accounts-unsubscribe'),
    url(r'^api/accounts/profile/unsubscribe-all/$',
        UnsubscribeAllView.as_view(),
        name='dtracker-api-accounts-unsubscribe-all'),
    url(r'^api/accounts/profile/keywords/$', ModifyKeywordsView.as_view(),
        name='dtracker-api-accounts-profile-keywords'),
    url(r'^accounts/profile/keywords', ModifyKeywordsView.as_view(),
        name='dtracker-accounts-profile-keywords'),

    # Team-related URLs
    url(r'^teams/\+create/$', CreateTeamView.as_view(),
        name='dtracker-teams-create'),
    url(r'^teams/(?P<slug>.+)/\+delete/$', DeleteTeamView.as_view(),
        name='dtracker-team-delete'),
    url(r'^teams/\+delete-success/$',
        TemplateView.as_view(template_name='core/team-deleted.html'),
        name='dtracker-team-deleted'),
    url(r'^teams/(?P<slug>.+)/\+update/$', UpdateTeamView.as_view(),
        name='dtracker-team-update'),
    url(r'^teams/(?P<slug>.+)/\+add-package/$', AddPackageToTeamView.as_view(),
        name='dtracker-team-add-package'),
    url(r'^teams/(?P<slug>.+)/\+remove-package/$',
        RemovePackageFromTeamView.as_view(),
        name='dtracker-team-remove-package'),
    url(r'^teams/(?P<slug>.+)/\+join/$', JoinTeamView.as_view(),
        name='dtracker-team-join'),
    url(r'^teams/(?P<slug>.+)/\+leave/$', LeaveTeamView.as_view(),
        name='dtracker-team-leave'),
    url(r'^teams/(?P<slug>.+)/\+add-member/$', AddTeamMember.as_view(),
        name='dtracker-team-add-member'),
    url(r'^teams/(?P<slug>.+)/\+remove-member/$', RemoveTeamMember.as_view(),
        name='dtracker-team-remove-member'),
    url(r'^teams/(?P<slug>.+)/\+manage/$', ManageTeamMembers.as_view(),
        name='dtracker-team-manage'),
    url(r'^teams/$', TeamListView.as_view(),
        name='dtracker-team-list'),
    url(r'^teams/\+confirm/(?P<confirmation_key>.+)/$',
        ConfirmMembershipView.as_view(),
        name='dtracker-team-confirm-membership'),
    url(r'^team/\+search$', TeamSearchView.as_view(),
        name='dtracker-team-search'),
    url(r'^teams/(?P<slug>.+)/\+mute/$', SetMuteTeamView.as_view(action='mute'),
        name='dtracker-team-mute'),
    url(r'^teams/(?P<slug>.+)/\+unmute/$',
        SetMuteTeamView.as_view(action='unmute'),
        name='dtracker-team-unmute'),
    url(r'^teams/(?P<slug>.+)/\+set-keywords/$',
        SetMembershipKeywords.as_view(),
        name='dtracker-team-set-keywords'),
    url(r'^teams/(?P<slug>.+)/\+manage-membership/$',
        EditMembershipView.as_view(),
        name='dtracker-team-manage-membership'),
    url(r'^teams/(?P<slug>.+?)/$', TeamDetailsView.as_view(),
        name='dtracker-team-page'),

    # Package  news page
    url(r'^pkg/(?P<package_name>.+)/news/', PackageNews.as_view(),
        name='dtracker-package-news'),

    # Dedicated package page
    url(r'^pkg/(?P<package_name>[^/]+)/?$', package_page,
        name='dtracker-package-page'),
    # RSS news feed
    url(r'^pkg/(?P<package_name>.+)/rss$', PackageNewsFeed(),
        name='dtracker-package-rss-news-feed'),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', django.contrib.admindocs.urls),
]

for app in settings.INSTALLED_APPS:
    try:
        urlmodule = importlib.import_module(app + '.tracker_urls')
        if hasattr(urlmodule, 'urlpatterns'):
            urlpatterns += urlmodule.urlpatterns
    except ImportError:
        pass

urlpatterns += [
    # The package page view catch all. It must be listed *after* the admin
    # URL so that the admin URL is not interpreted as a package named "admin".
    url(r'^(?P<package_name>[^/]+)/?$', package_page_redirect,
        name='dtracker-package-page-redirect'),
]

if settings.DJANGO_EMAIL_ACCOUNTS_USE_CAPTCHA:
    import captcha.urls
    urlpatterns += [
        url(r'^captcha/', include(captcha.urls.urlpatterns)),
    ]

if settings.DEBUG:
    import django.views.static
    import debug_toolbar
    urlpatterns = [
        url(r'^media/(?P<path>.*)$', django.views.static.serve,
            {'document_root': settings.MEDIA_ROOT}),
        url(r'^static/(?P<path>.*)$', django.views.static.serve,
            {'document_root': settings.STATIC_ROOT}),
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
