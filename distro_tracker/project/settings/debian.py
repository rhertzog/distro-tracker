"""Debian.org specific settings"""

import os.path

from . import defaults
from .db_postgresql import DATABASES  # noqa

__all__ = [
    'ALLOWED_HOSTS',
    'AUTHENTICATION_BACKENDS',
    'DATABASES',
    'DISTRO_TRACKER_BUGS_PANEL_TEMPLATE',
    'DISTRO_TRACKER_CVE_URL',
    'DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES',
    'DISTRO_TRACKER_DEVEL_REPOSITORIES',
    'DISTRO_TRACKER_FQDN',
    'DISTRO_TRACKER_REMOVALS_URL',
    'DISTRO_TRACKER_VENDOR_RULES',
    'DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE',
    'DJANGO_EMAIL_ACCOUNTS_POST_LOGOUT_REDIRECT',
    'DJANGO_EMAIL_ACCOUNTS_PRE_LOGIN_HOOK',
    'INSTALLED_APPS',
    'MIDDLEWARE',
]

INSTALLED_APPS = defaults.INSTALLED_APPS.copy()
INSTALLED_APPS.extend([
    # Many debian.org customizations
    'distro_tracker.vendor.debian',
    # Generate warnings for outdated values of the Standards-Version field
    'distro_tracker.stdver_warnings',
    # Extract common files from the source package
    'distro_tracker.extract_source_files',
])

# Official service name
DISTRO_TRACKER_FQDN = "tracker.debian.org"
ALLOWED_HOSTS = [
    DISTRO_TRACKER_FQDN,
    "2qlvvvnhqyda2ahd.onion",
]

# Custom data path (used only if it exists, so that we can reuse
# those settings in a development environment too).
if os.path.isdir('/srv/tracker.debian.org/data'):
    DISTRO_TRACKER_DATA_PATH = '/srv/tracker.debian.org/data'
    __all__.append('DISTRO_TRACKER_DATA_PATH')

if os.path.isfile('/etc/ssl/ca-global/ca-certificates.crt'):
    DISTRO_TRACKER_CA_BUNDLE = '/etc/ssl/ca-global/ca-certificates.crt'
    __all__.append('DISTRO_TRACKER_CA_BUNDLE')

#: A module implementing vendor-specific hooks for use by Distro Tracker.
#: For more information see :py:mod:`distro_tracker.vendor`.
DISTRO_TRACKER_VENDOR_RULES = 'distro_tracker.vendor.debian.rules'

#: A custom template which the bugs panel should use
DISTRO_TRACKER_BUGS_PANEL_TEMPLATE = 'debian/bugs.html'

#: A custom template which the vcs table field should use
DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE = 'debian/package-table-fields/vcs.html'

#: A list of suite names which should be used when updating piuparts stats
DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES = (
    'sid',
)

#: The page documenting package removals
DISTRO_TRACKER_REMOVALS_URL = "https://ftp-master.debian.org/removals.txt"

#: A list of the repositories where new versions are uploaded
DISTRO_TRACKER_DEVEL_REPOSITORIES = ['unstable', 'experimental']

#: URL for CVE tracker
DISTRO_TRACKER_CVE_URL = 'https://security-tracker.debian.org/tracker/'

# Various settings for sso.debian.org support
MIDDLEWARE = defaults.MIDDLEWARE.copy()
MIDDLEWARE.insert(
    MIDDLEWARE.index(
        'django.contrib.auth.middleware.AuthenticationMiddleware') + 1,
    'distro_tracker.vendor.debian.sso_auth.DebianSsoUserMiddleware'
)
AUTHENTICATION_BACKENDS = defaults.AUTHENTICATION_BACKENDS.copy()
AUTHENTICATION_BACKENDS.insert(
    0, 'distro_tracker.vendor.debian.sso_auth.DebianSsoUserBackend')
DJANGO_EMAIL_ACCOUNTS_PRE_LOGIN_HOOK = \
    'distro_tracker.vendor.debian.rules.pre_login'
DJANGO_EMAIL_ACCOUNTS_POST_LOGOUT_REDIRECT = \
    'distro_tracker.vendor.debian.rules.post_logout'
