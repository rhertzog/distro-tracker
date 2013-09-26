#!/usr/bin/env python

import os
import os.path

from distutils.core import setup
from itertools import chain

def find_package_data():
    pkgdata = {}
    pkgdir= {}
    EXCLUDE_FROM_DATA=('.py', '.pyc', '.pyo')
    for directory, _, files in chain(os.walk('pts'), os.walk('django_email_accounts')):
        package = '.'.join(directory.split(os.sep))
        if '__init__.py' in files:
            # Record real packages and their directories
            pkgdata[package] = [
                f for f in files
                if not f.endswith(EXCLUDE_FROM_DATA)
            ]
            pkgdir[package] = directory
        else:
            # Find parent package
            while package not in pkgdata and package:
                package = ".".join(package.split(".")[:-1])
            # Add data files relative to their parent package
            reldir = os.path.relpath(directory, pkgdir[package])
            pkgdata[package].extend(
                os.path.join(reldir, f)
                for f in files
                if not f.endswith(EXCLUDE_FROM_DATA)
            )
    return pkgdata

setup(name='DistroTracker',
      version='0.1',
      description='Synoptic view of all packages of a Debian-based distribution',
      author='Distro Tracker Developers',
      author_email='debian-qa@lists.debian.org',
      url='http://wiki.debian.org/qa.debian.org/distro-tracker',
      packages=[
        '.'.join(directory.split(os.sep))
        for directory, _, files in chain(os.walk('pts'), os.walk('django_email_accounts'))
        if '__init__.py' in files
      ],
      package_data=find_package_data(),
     )
