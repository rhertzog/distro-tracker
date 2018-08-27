"""Appropriate settings to run the test suite."""

from . import defaults
from .development import *  # noqa

# Don't use bcrypt to run tests (speed gain)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.SHA1PasswordHasher',
]

# Restore INSTALLED_APPS and MIDDLEWARE from defaults to disable debug_toolbar
INSTALLED_APPS = defaults.INSTALLED_APPS.copy()
MIDDLEWARE = defaults.MIDDLEWARE

TEST_NON_SERIALIZED_APPS = [
    'django.contrib.contenttypes'
]

# When running the test suite, enable all apps so that we have all the models
INSTALLED_APPS.extend([
    'distro_tracker.auto_news',
    'distro_tracker.derivative',
    'distro_tracker.extract_source_files',
    'distro_tracker.stdver_warnings',
    'distro_tracker.vendor',
    'distro_tracker.vendor.debian',
])
