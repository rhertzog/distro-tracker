"""Debian.org specific settings"""

ADMINS = (
    ('Tracker Admins', 'owner@tracker.debian.org'),
)
MANAGERS = ADMINS

# If you override the FQDN, you also have to override other settings
# whose values are based on it.
DISTRO_TRACKER_FQDN = "tracker.debian.org"
DISTRO_TRACKER_CONTROL_EMAIL = 'control@' + DISTRO_TRACKER_FQDN
DISTRO_TRACKER_CONTACT_EMAIL = 'owner@' + DISTRO_TRACKER_FQDN
DISTRO_TRACKER_BOUNCES_EMAIL = 'bounces@' + DISTRO_TRACKER_FQDN
DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL = DISTRO_TRACKER_BOUNCES_EMAIL
ALLOWED_HOSTS = [ DISTRO_TRACKER_FQDN ]

DISTRO_TRACKER_VENDOR_NAME = "Debian"
DISTRO_TRACKER_VENDOR_URL = "http://www.debian.org"

#: A module implementing vendor-specific hooks for use by Distro Tracker.
#: For more information see :py:mod:`distro_tracker.vendor`.
DISTRO_TRACKER_VENDOR_RULES = 'distro_tracker.vendor.debian.rules'

#: A custom template which the bugs panel should use
DISTRO_TRACKER_BUGS_PANEL_TEMPLATE = 'debian/bugs.html'

#: A list of suite names which should be used when updating piuparts stats
DISTRO_TRACKER_DEBIAN_PIUPARTS_SUITES = (
    'sid',
)

DJANGO_EMAIL_ACCOUNTS_PRE_LOGIN_HOOK = \
    'distro_tracker.vendor.debian.rules.pre_login'
DJANGO_EMAIL_ACCOUNTS_POST_LOGOUT_REDIRECT = \
    'distro_tracker.vendor.debian.rules.post_logout'
