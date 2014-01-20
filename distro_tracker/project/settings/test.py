"""Appropriate settings to run the test suite."""

from .development import *

# Don't use bcrypt to run tests (speed gain)
PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.SHA1PasswordHasher',
)

SOUTH_TESTS_MIGRATE = False

from .defaults import INSTALLED_APPS
# When running the test suite, lets all apps be tested
INSTALLED_APPS += (
    'distro_tracker.stdver_warnings',
    'distro_tracker.auto_news',
    'distro_tracker.extract_source_files',
    'distro_tracker.vendor',
    'distro_tracker.vendor.debian',
)
