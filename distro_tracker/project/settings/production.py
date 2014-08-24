"""
This file has appropriate settings for running in production.

When running in production, selected.py should point to this file.
"""

# PostgreSQL should be used in production
from .db_postgresql import *  # noqa

# Use paths from the package
from .pkg_paths import *      # noqa
