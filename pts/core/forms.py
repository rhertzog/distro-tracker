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
from django.template.defaultfilters import slugify
from pts.core.models import Team
from pts.core.models import SourcePackageName


class CreateTeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = (
            'name',
            'slug',
            'maintainer_email',
            'public',
            'description',
            'url',
        )

    def __init__(self, *args, **kwargs):
        super(CreateTeamForm, self).__init__(*args, **kwargs)
        self.fields['slug'].required = self.is_update()

    def is_update(self):
        return hasattr(self, 'instance') and self.instance.pk is not None

    def clean(self):
        """
        Provides a default value for the slug field based on the given team
        name, but only if the team is only just being created (not an
        update of an existing instance).
        """
        cleaned_data = super(CreateTeamForm, self).clean()
        if not self.is_update():
            if not cleaned_data['slug'] and 'name' in cleaned_data:
                cleaned_data['slug'] = slugify(cleaned_data['name'])

        return cleaned_data

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


class AddTeamMemberForm(forms.Form):
    email = forms.EmailField()
