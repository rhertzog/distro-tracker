# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib import auth
from distro_tracker.accounts.models import UserEmail
from distro_tracker.accounts.models import User

try:
    import ldap
except ImportError:
    ldap = None


class DebianSsoUserMiddleware(RemoteUserMiddleware):
    """
    Middleware that initiates user authentication based on the REMOTE_USER
    field provided by Debian's SSO system.

    If the currently logged in user is a DD (as identified by having a
    @debian.org address), he is forcefully logged out if the header is no longer
    found or is invalid.
    """
    header = 'REMOTE_USER'

    def extract_email(self, username):
        parts = [part for part in username.split(':') if part]
        federation, jurisdiction = parts[:2]
        if (federation, jurisdiction) != ('DEBIANORG', 'DEBIAN'):
            return
        username = parts[-1]
        if '@' in username:
            return username  # Full email already
        return username + '@debian.org'

    def is_debian_member(self, user):
        return any(
            email.email.endswith('@debian.org')
            for email in user.emails.all()
        )

    def log_out_user(self, request):
        if request.user.is_authenticated():
            if self.is_debian_member(request.user):
                auth.logout(request)

    def process_request(self, request):
        if self.header not in request.META:
            # If a user is logged in via Debian SSO, sign him out
            self.log_out_user(request)
            return

        username = request.META[self.header]
        if not username:
            self.log_out_user(request)
            return
        email = self.extract_email(username)

        if request.user.is_authenticated():
            if request.user.emails.filter(email=email).exists():
                # The currently logged in user matches the one given by the
                # headers.
                return

        user = auth.authenticate(remote_user=email)
        if user:
            request.user = user
            auth.login(request, user)


class DebianSsoUserBackend(RemoteUserBackend):
    """
    The authentication backend which authenticates the provided remote user
    (identified by his @debian.org email) in Distro Tracker. If a matching User
    model instance does not exist, one is automatically created. In that case
    the DDs first and last name are pulled from Debian's LDAP.
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

    def get_uid(self, remote_user):
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

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
