"""Appropriate settings to run the test suite."""

from .development import *  # noqa

# Don't use bcrypt to run tests (speed gain)
PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.SHA1PasswordHasher',
)

from .defaults import INSTALLED_APPS
# When running the test suite, enable all apps so that we have all the models
INSTALLED_APPS += (
    'distro_tracker.auto_news',
    'distro_tracker.derivative',
    'distro_tracker.extract_source_files',
    'distro_tracker.stdver_warnings',
    'distro_tracker.vendor',
    'distro_tracker.vendor.debian',
)
