"""Debian.org specific settings"""

import os.path
from .defaults import (
    INSTALLED_APPS, MIDDLEWARE_CLASSES, AUTHENTICATION_BACKENDS)
from .db_postgresql import DATABASES  # noqa

INSTALLED_APPS += (
    # Many debian.org customizations
    'distro_tracker.vendor.debian',
    # Generate warnings for outdated values of the Standards-Version field
    'distro_tracker.stdver_warnings',
    # Extract common files from the source package
    'distro_tracker.extract_source_files',
)

# Official service name
DISTRO_TRACKER_FQDN = "tracker.debian.org"

# Custom data path (used only if it exists, so that we can reuse
# those settings in a development environment too).
if os.path.isdir('/srv/tracker.debian.org/data'):
    DISTRO_TRACKER_DATA_PATH = '/srv/tracker.debian.org/data'

#: A module implementing vendor-specific hooks for use by Distro Tracker.
#: For more information see :py:mod:`distro_tracker.vendor`.
DISTRO_TRACKER_VENDOR_RULES = 'distro_tracker.vendor.debian.rules'

#: A custom template which the bugs panel should use
DISTRO_TRACKER_BUGS_PANEL_TEMPLATE = 'debian/bugs.html'

#: A list of suite names which should be used when updating piuparts stats
DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES = (
    'sid',
)

# Various settings for sso.debian.org support
_index_auth = MIDDLEWARE_CLASSES.index(
    'django.contrib.auth.middleware.AuthenticationMiddleware') + 1
MIDDLEWARE_CLASSES = MIDDLEWARE_CLASSES[:_index_auth] + \
    ('distro_tracker.vendor.debian.sso_auth.DebianSsoUserMiddleware',) + \
    MIDDLEWARE_CLASSES[_index_auth:]
AUTHENTICATION_BACKENDS = \
    ('distro_tracker.vendor.debian.sso_auth.DebianSsoUserBackend',) + \
    AUTHENTICATION_BACKENDS
DJANGO_EMAIL_ACCOUNTS_PRE_LOGIN_HOOK = \
    'distro_tracker.vendor.debian.rules.pre_login'
DJANGO_EMAIL_ACCOUNTS_POST_LOGOUT_REDIRECT = \
    'distro_tracker.vendor.debian.rules.post_logout'
