# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

# This file has been forked from django-bootstrap-form which was
# BSD licensed:
#
# Copyright (c) Ming Hsien Tzang and individual contributors.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#
#     3. Neither the name of django-bootstrap-form nor the names of its
#        contributors may be used to endorse or promote products derived from
#        this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from django import forms
from django.template import Context, Template

from distro_tracker.test import TestCase

CHOICES = (
    (0, 'Zero'),
    (1, 'One'),
    (2, 'Two'),
)


class ExampleForm(forms.Form):
    char_field = forms.CharField()
    choice_field = forms.ChoiceField(choices=CHOICES)
    radio_choice = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    multiple_choice = forms.MultipleChoiceField(choices=CHOICES)
    multiple_checkbox = forms.MultipleChoiceField(
        choices=CHOICES, widget=forms.CheckboxSelectMultiple)
    file_fied = forms.FileField()
    password_field = forms.CharField(widget=forms.PasswordInput)
    textarea = forms.CharField(widget=forms.Textarea)
    boolean_field = forms.BooleanField()


class BootstrapTemplateTagTests(TestCase):
    def setUp(self):
        self.maxDiff = None
        self.form = ExampleForm()
        self.form.use_required_attribute = False

    def render_template(self, content):
        return Template(content).render(Context({'form': self.form}))

    def load_test_data(self, filename):
        path = self.get_test_data_path(filename)
        with open(path) as f:
            return f.read()

    def test_basic_form(self):
        expected = self.load_test_data('bootstrap-form-basic.html')

        template_content = "{% load bootstrap %}{{ form|bootstrap }}"
        html = self.render_template(template_content)

        self.assertHTMLEqual(expected, html)

    def test_inline_form(self):
        expected = self.load_test_data('bootstrap-form-inline.html')

        template_content = "{% load bootstrap %}{{ form|bootstrap_inline }}"
        html = self.render_template(template_content)

        self.assertHTMLEqual(expected, html)

    def test_horizontal_form(self):
        expected = self.load_test_data('bootstrap-form-horizontal.html')

        template_content = "{% load bootstrap %}{{ form|bootstrap_horizontal }}"
        html = self.render_template(template_content)

        self.assertHTMLEqual(expected, html)
