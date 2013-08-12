# -*- coding: utf-8 -*-

# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

"""
Debian-specific models.
"""

from __future__ import unicode_literals
from django.db import models
from django.utils.encoding import python_2_unicode_compatible

from pts.core.utils import SpaceDelimitedTextField
from pts.core.utils import get_or_none
from pts.core.models import PackageName
from pts.core.models import SourcePackageName
from jsonfield import JSONField

import re


@python_2_unicode_compatible
class DebianContributor(models.Model):
    """
    Model containing additional Debian-specific information about contributors.
    """
    email = models.OneToOneField('core.ContributorEmail')
    agree_with_low_threshold_nmu = models.BooleanField(default=False)
    is_debian_maintainer = models.BooleanField(default=False)
    allowed_packages = SpaceDelimitedTextField(blank=True)

    def __str__(self):
        return 'Debian contributor <{email}>'.format(email=self.email)


@python_2_unicode_compatible
class LintianStats(models.Model):
    """
    Model for lintian stats of packages.
    """
    package = models.OneToOneField(PackageName, related_name='lintian_stats')
    stats = JSONField()

    def __str__(self):
        return 'Lintian stats for package {package}'.format(
            package=self.package)

    def get_lintian_url(self, full=False):
        """
        Returns the lintian URL for the package matching the
        :class:`LintianStats <pts.vendor.debian.models.LintianStats>`.

        :param full: Whether the URL should include the full lintian report or only
            the errors and warnings.
        :type full: Boolean
        """
        package = get_or_none(SourcePackageName, pk=self.package.pk)
        if not package:
            return ''
        maintainer_email = ''
        if package.main_version:
            maintainer = package.main_version.maintainer
            if maintainer:
                maintainer_email = maintainer.email
        # First adapt the maintainer URL to the form expected by lintian.debian.org
        lintian_maintainer_email = re.sub(
            r"""[àáèéëêòöøîìùñ~/\(\)" ']""",
            '_',
            maintainer_email)

        report = 'full' if full else 'maintainer'

        return (
            'http://lintian.debian.org/{report}/{maintainer}.html#{pkg}'.format(
                report=report,
                maintainer=lintian_maintainer_email,
                pkg=self.package)
        )


@python_2_unicode_compatible
class PackageTransition(models.Model):
    package = models.ForeignKey(PackageName, related_name='package_transitions')
    transition_name = models.CharField(max_length=50)
    status = models.CharField(max_length=50, blank=True, null=True)
    reject = models.BooleanField(default=False)

    def __str__(self):
        return "Transition {name} ({status}) for package {pkg}".format(
            name=self.transition_name, status=self.status, pkg=self.package)


@python_2_unicode_compatible
class PackageExcuses(models.Model):
    package = models.OneToOneField(PackageName, related_name='excuses')
    excuses = JSONField()

    def __str__(self):
        return "Excuses for the package {pkg}".format(pkg=self.package)


@python_2_unicode_compatible
class BuildLogCheckStats(models.Model):
    package = models.OneToOneField(
        SourcePackageName,
        related_name='build_logcheck_stats')
    stats = JSONField()

    def __str__(self):
        return "Build logcheck stats for {pkg}".format(pkg=self.package)
