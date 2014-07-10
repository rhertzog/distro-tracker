#!/usr/bin/env python

import os
import os.path
import re

from distutils.core import setup

def find_package_data(basedir):
    pkgdata = {}
    pkgdir = {}
    EXCLUDE_FROM_DATA=('.py', '.pyc', '.pyo')
    for directory, _, files in os.walk(basedir):
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


with open('debian/changelog') as f:
    res = re.search('\((\d.*)\)', f.readline())
    version = res.group(1)

setup(name='DistroTracker',
      version=version,
      description='Synoptic view of all packages of a Debian-based distribution',
      author='Distro Tracker Developers',
      author_email='debian-qa@lists.debian.org',
      url='http://wiki.debian.org/qa.debian.org/distro-tracker',
      packages=[
        '.'.join(directory.split(os.sep))
        for directory, _, files in os.walk('distro_tracker')
        if '__init__.py' in files
      ],
      package_data=find_package_data('distro_tracker'),
     )
setup(name='DjangoEmailAccounts',
      version=version,
      description='User registration app for Django',
      author='Distro Tracker Developers',
      author_email='debian-qa@lists.debian.org',
      url='http://wiki.debian.org/qa.debian.org/distro-tracker',
      packages=[
        '.'.join(directory.split(os.sep))
        for directory, _, files in os.walk('django_email_accounts')
        if '__init__.py' in files
      ],
      package_data=find_package_data('django_email_accounts'),
     )
