"""Appropriate settings to run the test suite."""

from .development import *

# Don't use bcrypt to run tests (speed gain)
PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.SHA1PasswordHasher',
)
