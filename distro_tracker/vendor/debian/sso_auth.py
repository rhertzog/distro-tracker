# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib import auth
from django.core.exceptions import ImproperlyConfigured

from distro_tracker.accounts.models import UserEmail
from distro_tracker.accounts.models import User

try:
    import ldap
except ImportError:
    ldap = None


class DebianSsoUserMiddleware(RemoteUserMiddleware):
    """
    Middleware that initiates user authentication based on the REMOTE_USER
    field provided by Debian's SSO system, or based on the SSL_CLIENT_S_DN_CN
    field provided by the validation of the SSL client certificate generated
    by sso.debian.org.

    If the currently logged in user is a DD (as identified by having a
    @debian.org address), they are forcefully logged out if the header
    is no longer found or is invalid.
    """
    dacs_header = 'REMOTE_USER'
    cert_header = 'SSL_CLIENT_S_DN_CN'

    @staticmethod
    def dacs_user_to_email(username):
        parts = [part for part in username.split(':') if part]
        federation, jurisdiction = parts[:2]
        if (federation, jurisdiction) != ('DEBIANORG', 'DEBIAN'):
            return
        username = parts[-1]
        if '@' in username:
            return username  # Full email already
        return username + '@debian.org'

    @staticmethod
    def is_debian_member(user):
        return any(
            email.email.endswith('@debian.org')
            for email in user.emails.all()
        )

    def process_request(self, request):
        # AuthenticationMiddleware is required so that request.user exists.
        if not hasattr(request, 'user'):
            raise ImproperlyConfigured(
                "The Django remote user auth middleware requires the"
                " authentication middleware to be installed.  Edit your"
                " MIDDLEWARE_CLASSES setting to insert"
                " 'django.contrib.auth.middleware.AuthenticationMiddleware'"
                " before the DebianSsoUserMiddleware class.")

        dacs_user = request.META.get(self.dacs_header)
        cert_user = request.META.get(self.cert_header)
        if cert_user is not None:
            remote_user = cert_user
        elif dacs_user is not None:
            remote_user = self.dacs_user_to_email(dacs_user)
        else:
            # Debian developers can only authenticate via SSO/SSL certs
            # so log them out now if they no longer have the proper META
            # variable
            if request.user.is_authenticated():
                if self.is_debian_member(request.user):
                    auth.logout(request)
            return

        if request.user.is_authenticated():
            if request.user.emails.filter(email=remote_user).exists():
                # The currently logged in user matches the one given by the
                # headers.
                return

        # This will create the user if it doesn't exist
        user = auth.authenticate(remote_user=remote_user)
        if user:
            # User is valid. Set request.user and persist user in the session
            # by logging the user in.
            request.user = user
            auth.login(request, user)


class DebianSsoUserBackend(RemoteUserBackend):
    """
    The authentication backend which authenticates the provided remote
    user (identified by their @debian.org email) in Distro Tracker. If
    a matching User model instance does not exist, one is
    automatically created. In that case the DDs first and last name
    are pulled from Debian's LDAP.
    """
    def authenticate(self, remote_user):
        if not remote_user:
            return

        email = remote_user

        user_email, _ = UserEmail.objects.get_or_create(email=email)
        if not user_email.user:
            kwargs = {}
            names = self.get_user_details(remote_user)
            if names:
                kwargs.update(names)
            user = User.objects.create_user(main_email=email, **kwargs)
        else:
            user = User.objects.get(pk=user_email.user.id)

        return user

    @staticmethod
    def get_uid(remote_user):
        # Strips off the @debian.org part of the email leaving the uid
        if remote_user.endswith('@debian.org'):
            return remote_user[:-11]
        return remote_user

    def get_user_details(self, remote_user):
        """
        Gets the details of the given user from the Debian LDAP.
        :return: Dict with the keys ``first_name``, ``last_name``
            ``None`` if the LDAP lookup did not return anything.
        """
        if ldap is None:
            return None
        if not remote_user.endswith('@debian.org'):
            # We only know how to extract data for DD via LDAP
            return None

        l = ldap.initialize('ldap://db.debian.org')
        result_set = l.search_s(
            'dc=debian,dc=org',
            ldap.SCOPE_SUBTREE,
            'uid={}'.format(self.get_uid(remote_user)),
            None)
        if not result_set:
            return None

        result = result_set[0]
        return {
            'first_name': result[1]['cn'][0].decode('utf-8'),
            'last_name': result[1]['sn'][0].decode('utf-8'),
        }
