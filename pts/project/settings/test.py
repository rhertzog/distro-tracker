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
    'pts.functional_tests',
    'pts.stdver_warnings',
    'pts.auto_news',
    'pts.extract_source_files',
    'pts.vendor',
    'pts.vendor.debian',
)
