# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Various utilities for the PTS project."""
from __future__ import unicode_literals
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.db import models
import json

from .email_messages import extract_email_address_from_header
from .email_messages import get_decoded_message_payload
from .email_messages import message_from_bytes


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns ``None`` if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def pts_render_to_string(template_name, context=None):
    """
    A custom function to render a template to a string which injects extra
    PTS-specific information to the context, such as the name of the derivative.

    This function is necessary since Django's
    :data:`TEMPLATE_CONTEXT_PROCESSORS <pts.project.settings.TEMPLATE_CONTEXT_PROCESSORS>
    only work when using a :class:`RequestContext <django.template.RequestContext>`,
    whereas this function can be called independently from any HTTP request.
    """
    from pts.core import context_processors
    if context is None:
        context = {}
    extra_context = context_processors.PTS_EXTRAS
    context.update(extra_context)

    return render_to_string(template_name, context)


def render_to_json_response(response):
    """
    Helper function creating an :class:`HttpResponse <django.http.HttpResponse>`
    by serializing the given ``response`` object to a JSON string.

    The resulting HTTP response has Content-Type set to application/json.

    :param response: The object to be serialized in the response. It must be
        serializable by the :mod:`json` module.
    :rtype: :class:`HttpResponse <django.http.HttpResponse>`
    """
    return HttpResponse(
        json.dumps(response),
        content_type='application/json'
    )


class PrettyPrintList(object):
    """
    A class which wraps the built-in :class:`list` object so that when it is
    converted to a string, its contents are printed using the given
    :attr:`delimiter`.

    The default delimiter is a space.

    >>> a = PrettyPrintList([1, 2, 3])
    >>> print(a)
    1 2 3
    >>> print(PrettyPrintList([u'one', u'2', u'3']))
    one 2 3
    >>> print(PrettyPrintList([1, 2, 3], delimiter=', '))
    1, 2, 3
    >>> # Still acts as a list
    >>> a == [1, 2, 3]
    True
    >>> a == ['1', '2', '3']
    False
    """
    def __init__(self, l=None, delimiter=' '):
        if l is None:
            self._list = []
        else:
            self._list = l
        self.delimiter = delimiter

    def __getattr__(self, name, *args, **kwargs):
        return getattr(self._list, name)

    def __len__(self):
        return len(self._list)

    def __getitem__(self, pos):
        return self._list[pos]

    def __iter__(self):
        return self._list.__iter__()

    def __str__(self):
        return self.delimiter.join(map(str, self._list))

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if isinstance(other, PrettyPrintList):
            return self._list == other._list
        return self._list == other


class SpaceDelimitedTextField(models.TextField):
    """
    A custom Django model field which stores a list of strings.

    It stores the list in a :class:`TextField <django.db.models.TextField>`
    as a space delimited list. It is marshalled back to a :class:`PrettyPrintList`
    in the Python domain.
    """
    __metaclass__ = models.SubfieldBase

    description = "Stores a space delimited list of strings"

    def to_python(self, value):
        if value is None:
            return None

        if isinstance(value, PrettyPrintList):
            return value
        elif isinstance(value, list):
            return PrettyPrintList(value)

        return PrettyPrintList(value.split())

    def get_prep_value(self, value, **kwargs):
        if value is None:
            return
        # Any iterable value can be converted into this type of field.
        return ' '.join(map(str, value))

    def get_db_prep_value(self, value, **kwargs):
        return self.get_prep_value(value)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_prep_value(value)


#: A map of currently available VCS systems' shorthands to their names.
VCS_SHORTHAND_TO_NAME = {
    'svn': 'Subversion',
    'git': 'Git',
    'bzr': 'Bazaar',
    'cvs': 'CVS',
    'darcs': 'Darcs',
    'hg': 'Mercurial',
    'mtn': 'Monotone',
}


def get_vcs_name(shorthand):
    """
    Returns a full name for the VCS given its shorthand.

    If the given shorthand is unknown an empty string is returned.

    :param shorthand: The shorthand of a VCS for which a name is required.

    :rtype: string
    """
    return VCS_SHORTHAND_TO_NAME.get(shorthand, '')
