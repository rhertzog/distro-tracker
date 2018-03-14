# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Forms for the :mod:`distro_tracker.core` app."""
from django import forms
from django.template.defaultfilters import slugify

from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.models import SourcePackageName, Team


class CreateTeamForm(forms.ModelForm):
    maintainer_email = forms.EmailField(required=False)

    class Meta:
        model = Team
        fields = (
            'name',
            'slug',
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
        # Create a maintainer email instance based on the email given to the
        # form.
        if 'maintainer_email' in self.cleaned_data:
            if self.cleaned_data['maintainer_email']:
                maintainer_email, _ = UserEmail.objects.get_or_create(
                    email=self.cleaned_data['maintainer_email'])
                self.instance.maintainer_email = maintainer_email
            else:
                self.instance.maintainer_email = None

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
