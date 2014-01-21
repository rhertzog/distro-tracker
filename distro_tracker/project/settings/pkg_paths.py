"""Override path-related settings to use system wide paths.

The paths indicated in this file are those setup by the official Debian
package.
"""
from __future__ import unicode_literals

import os.path

DISTRO_TRACKER_BASE_PATH = '/var/lib/package-tracking-system'

STATIC_ROOT = os.path.join(DISTRO_TRACKER_BASE_PATH, 'static')
MEDIA_ROOT = os.path.join(DISTRO_TRACKER_BASE_PATH, 'media')
TEMPLATE_DIRS = (
    os.path.join(DISTRO_TRACKER_BASE_PATH, 'templates'),
)

DISTRO_TRACKER_KEYRING_DIRECTORY = os.path.join(DISTRO_TRACKER_BASE_PATH, 'keyring')
DISTRO_TRACKER_CACHE_DIRECTORY = '/var/cache/package-tracking-system'
