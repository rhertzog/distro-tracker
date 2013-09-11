# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""The URL routes for the PTS project."""

from __future__ import unicode_literals
from django.conf.urls import patterns, include, url
from django.views.generic import TemplateView
from django.core.urlresolvers import reverse_lazy
from pts.core.views import PackageSearchView, PackageAutocompleteView
from pts.core.views import ActionItemJsonView, ActionItemView
from pts.core.views import KeywordsView
from pts.core.views import CreateTeamView
from pts.core.views import TeamDetailsView
from pts.core.views import DeleteTeamView
from pts.core.views import UpdateTeamView
from pts.core.views import AddPackageToTeamView
from pts.core.views import RemovePackageFromTeamView
from pts.core.views import JoinTeamView
from pts.core.views import LeaveTeamView
from pts.core.news_feed import PackageNewsFeed
from pts.accounts.views import RegisterUser
from pts.accounts.views import RegistrationConfirmation
from pts.accounts.views import AccountProfile
from pts.accounts.views import SubscriptionsView
from pts.accounts.views import UserEmailsView
from pts.accounts.views import SubscribeUserToPackageView
from pts.accounts.views import UnsubscribeUserView
from pts.accounts.views import UnsubscribeAllView
from pts.accounts.views import ChooseSubscriptionEmailView
from pts.accounts.views import ChangePersonalInfoView
from pts.accounts.views import PasswordChangeView
from pts.accounts.views import ModifyKeywordsView

from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Redirects for the old PTS package page URLs
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)\.html$',
        'pts.core.views.legacy_package_url_redirect'),

    # Permanent redirect for the old RSS URL
    url(r'^(?P<package_hash>(lib)?.)/(?P<package_name>(\1).+)/news\.rss20\.xml$',
        'pts.core.views.legacy_rss_redirect'),

    url(r'^search$', PackageSearchView.as_view(),
        name='pts-package-search'),

    url(r'^api/package/search/autocomplete$', PackageAutocompleteView.as_view(),
        name='pts-api-package-autocomplete'),
    url(r'^api/action-items/(?P<item_pk>\d+)$', ActionItemJsonView.as_view(),
        name='pts-api-action-item'),
    url(r'^api/keywords/$', KeywordsView.as_view(),
        name='pts-api-keywords'),

    url(r'^admin/', include(admin.site.urls)),

    url(r'^news/(?P<news_id>\d+)$', 'pts.core.views.news_page',
        name='pts-news-page'),
    url(r'^action-items/(?P<item_pk>\d+)$', ActionItemView.as_view(),
        name='pts-action-item'),

    url(r'^$', TemplateView.as_view(template_name='core/index.html'),
        name='pts-index'),

    # Account related URLs
    url(r'^accounts/register/$', RegisterUser.as_view(),
        name='pts-accounts-register'),
    url(r'^accounts/register/success/$',
        TemplateView.as_view(template_name='accounts/success.html'),
        name='pts-accounts-register-success'),
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
    url(r'^accounts/login/$', 'django.contrib.auth.views.login', {
            'template_name': 'accounts/login.html',
        },
        name='pts-accounts-login'),
    url(r'^accounts/logout/$', 'django.contrib.auth.views.logout', {
            'next_page': reverse_lazy('pts-index'),
        },
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
    url(r'^teams/create/$', CreateTeamView.as_view(),
        name='pts-teams-create'),
    url(r'^teams/(?P<pk>\d+)/$', TeamDetailsView.as_view(),
        name='pts-team-page-no-slug'),
    url(r'^teams/(?P<pk>\d+)/(?P<slug>.+)/$', TeamDetailsView.as_view(),
        name='pts-team-page'),
    url(r'^teams/delete/(?P<pk>\d+)/$', DeleteTeamView.as_view(),
        name='pts-team-delete'),
    url(r'^teams/delete/success/$',
        TemplateView.as_view(template_name='core/team-deleted.html'),
        name='pts-team-deleted'),
    url(r'^teams/update/(?P<pk>\d+)/$', UpdateTeamView.as_view(),
        name='pts-team-update'),
    url(r'^teams/add-package/(?P<pk>\d+)/$', AddPackageToTeamView.as_view(),
        name='pts-team-add-package'),
    url(r'^teams/remove-package/(?P<pk>\d+)/$', RemovePackageFromTeamView.as_view(),
        name='pts-team-remove-package'),
    url(r'^teams/join/(?P<pk>\d+)/$', JoinTeamView.as_view(),
        name='pts-team-join'),
    url(r'^teams/leave/(?P<pk>\d+)/$', LeaveTeamView.as_view(),
        name='pts-team-leave'),


    # Dedicated package page
    url(r'^pkg/(?P<package_name>[^/]+)/?$', 'pts.core.views.package_page',
        name='pts-package-page'),
    # RSS news feed
    url(r'^pkg/(?P<package_name>.+)/rss$', PackageNewsFeed(),
        name='pts-package-rss-news-feed'),

    # The package page view catch all. It must be listed *after* the admin URL so that
    # the admin URL is not interpreted as a package named "admin".
    url(r'^(?P<package_name>[^/]+)/?$', 'pts.core.views.package_page_redirect',
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
