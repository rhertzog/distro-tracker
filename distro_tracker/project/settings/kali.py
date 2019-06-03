"""Kali.org specific settings"""

from . import defaults
from .db_postgresql import DATABASES  # noqa

__all__ = [
    'DATABASES',
    'DISTRO_TRACKER_DEBCI_REPOSITORIES',
    'DISTRO_TRACKER_DEBCI_URL',
    'DISTRO_TRACKER_DEVEL_REPOSITORIES',
    'DISTRO_TRACKER_FQDN',
    'DISTRO_TRACKER_VENDOR_NAME',
    'DISTRO_TRACKER_VENDOR_RULES',
    'DISTRO_TRACKER_VENDOR_URL',
    'DJANGO_EMAIL_ACCOUNTS_USE_CAPTCHA',
    'INSTALLED_APPS',
]

INSTALLED_APPS = defaults.INSTALLED_APPS.copy()
INSTALLED_APPS.extend([
    # Extract common files from the source package
    'distro_tracker.extract_source_files',

    # Derivative application
    'distro_tracker.derivative',

    # Captcha support
    'captcha',

    # Debci status
    'distro_tracker.debci_status',
])

# Official service name
DISTRO_TRACKER_FQDN = "pkg.kali.org"
DISTRO_TRACKER_VENDOR_NAME = "Kali Linux"
DISTRO_TRACKER_VENDOR_URL = "http://www.kali.org"

# Captcha support
DJANGO_EMAIL_ACCOUNTS_USE_CAPTCHA = True

#: A module implementing vendor-specific hooks for use by Distro Tracker.
#: For more information see :py:mod:`distro_tracker.vendor`.
DISTRO_TRACKER_VENDOR_RULES = 'distro_tracker.vendor.kali.rules'

#: A list of the repositories where new versions are uploaded
DISTRO_TRACKER_DEVEL_REPOSITORIES = ['kali-dev']

#: repositories to check for debci status
DISTRO_TRACKER_DEBCI_REPOSITORIES = ['kali-dev', 'kali-rolling']

#: URL for debci
DISTRO_TRACKER_DEBCI_URL = 'http://autopkgtest.kali.org'
