"""Override path-related settings to use system wide paths.

The paths indicated in this file are those setup by the official Debian
package.
"""
from __future__ import unicode_literals

DISTRO_TRACKER_DATA_PATH = '/var/lib/distro-tracker'
DISTRO_TRACKER_CACHE_DIRECTORY = '/var/cache/distro-tracker'
DISTRO_TRACKER_LOG_DIRECTORY = '/var/log/distro-tracker'
