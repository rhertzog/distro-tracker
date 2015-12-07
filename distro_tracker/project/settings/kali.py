"""Kali.org specific settings"""

from .defaults import INSTALLED_APPS
from .db_postgresql import DATABASES  # noqa

INSTALLED_APPS += (
    # Generate news when packages are uploaded/removed/migrated
    'distro_tracker.auto_news',

    # Extract common files from the source package
    'distro_tracker.extract_source_files',

    # Derivative application
    'distro_tracker.derivative',

    # Captcha support
    'captcha',
)

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
