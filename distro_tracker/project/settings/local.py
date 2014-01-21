"""Site-specific settings

This is the file that you should edit to customize the setting of your
PTS installation. By default it imports settings from the ``selected.py``
file which is a symlink to the type of installation to you have
(typically, ``production.py`` or ``development.py``) and lets you add
overrides on top of those type-of-installation-specific settings.
"""
# Load the selected configuration (selected.py is a symlink to preferred config)

from .defaults import INSTALLED_APPS
from .selected import *

## Add your custom settings here

# ADMINS = (
#     ('Your Name', 'your_email@example.com'),
# )
# MANAGERS = ADMINS

# DISTRO_TRACKER_VENDOR_NAME = "Debian"
# DISTRO_TRACKER_VENDOR_URL = "http://www.debian.org"
# DISTRO_TRACKER_VENDOR_RULES = "distro_tracker.vendor.debian.rules"

# If you override the FQDN, you also have to override other settings
# whose values are based on it.
# DISTRO_TRACKER_FQDN = "packages.qa.debian.org"
# DISTRO_TRACKER_CONTROL_EMAIL = 'control@' + DISTRO_TRACKER_FQDN
# DISTRO_TRACKER_CONTACT_EMAIL = 'owner@' + DISTRO_TRACKER_FQDN
# DISTRO_TRACKER_BOUNCES_EMAIL = 'bounces@' + DISTRO_TRACKER_FQDN
# DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL = DISTRO_TRACKER_BOUNCES_EMAIL
# ALLOWED_HOSTS = [ DISTRO_TRACKER_FQDN ]

# If you don't use the packaged version of the PTS, put a random secret
# key here. DO NOT USE THE EXAMPLE KEY GIVEN BELOW.
# SECRET_KEY = 'etu2#5lv=!0(g9l31mw=cpwhioy!egg60lb5o3_67d83#(wu-u'

# You can enable supplementary Django applications here, refer to the
# documation for details about what they do
INSTALLED_APPS += (
    # Can be useful to create visualizations of the models
    # 'django_extensions',

    # Generate warnings for outdated values of the Standards-Version field
    # 'distro_tracker.stdver_warnings',

    # Generate news when packages are uploaded/removed/migrated
    # 'distro_tracker.auto_news',

    # Extract common files from the source package
    # 'distro_tracker.extract_source_files',
)
