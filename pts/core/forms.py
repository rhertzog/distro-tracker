# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Forms for the :mod:`pts.core` app."""
from __future__ import unicode_literals
from django import forms
from pts.core.models import Team
from pts.core.models import SourcePackageName


class CreateTeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = (
            'name',
            'maintainer_email',
            'public',
            'description',
            'url'
        )

    def save(self, *args, **kwargs):
        # The instance needs to be saved before many-to-many relations can
        # reference it.
        instance = super(CreateTeamForm, self).save(commit=True)
        # If the maintainer email is set, associate all packages maintained
        # by that email to the team.
        if not instance.maintainer_email:
            return instance

        filter_kwargs = {
            'source_package_versions__maintainer__contributor_email__email': (
                instance.maintainer_email
            )
        }
        packages = SourcePackageName.objects.filter(**filter_kwargs)
        packages = packages.distinct()

        # Add all the packages to the team's set
        instance.packages.add(*packages)

        return instance
