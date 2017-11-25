# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Various utilities for the distro-tracker project."""
from __future__ import unicode_literals
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.db import models
from django.conf import settings
import os
import json
import gpgme
import datetime
import io

# Re-export some functions
from .email_messages import extract_email_address_from_header  # noqa
from .email_messages import get_decoded_message_payload        # noqa
from .email_messages import message_from_bytes                 # noqa


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns ``None`` if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def distro_tracker_render_to_string(template_name, context=None):
    """
    A custom function to render a template to a string which injects extra
    distro-tracker specific information to the context, such as the name
    of the derivative.

    This function is necessary since Django's
    :data:`TEMPLATE_CONTEXT_PROCESSORS
    <distro_tracker.project.settings.TEMPLATE_CONTEXT_PROCESSORS> only work when
    using a :class:`RequestContext <django.template.RequestContext>`, whereas
    this function can be called independently from any HTTP request.
    """
    from distro_tracker.core import context_processors
    if context is None:
        context = {}
    extra_context = context_processors.DISTRO_TRACKER_EXTRAS
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

    It stores the list in a :class:`TextField <django.db.models.TextField>` as a
    space delimited list. It is marshalled back to a :class:`PrettyPrintList` in
    the Python domain.
    """

    description = "Stores a space delimited list of strings"

    def from_db_value(self, value, expression, connection, context):
        return self.to_python(value)

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


def verify_signature(content):
    """
    The function extracts any possible signature information found in the given
    content.

    Uses the ``DISTRO_TRACKER_KEYRING_DIRECTORY`` setting to access the keyring.
    If this setting does not exist, no signatures can be validated.

    :type content: :class:`bytes` or :class:`string`

    :returns: Information about the signers of the content as a list or
        ``None`` if there is no (valid) signature.
    :rtype: list of ``(name, email)`` pairs or ``None``
    :type content: :class:`bytes`
    """
    keyring_directory = getattr(settings, 'DISTRO_TRACKER_KEYRING_DIRECTORY',
                                None)
    if not keyring_directory:
        # The vendor has not provided a keyring
        return None

    if isinstance(content, str):
        content = content.encode('utf-8')

    os.environ['GNUPGHOME'] = keyring_directory
    ctx = gpgme.Context()

    # Try to verify the given content
    plain = io.BytesIO()
    try:
        signatures = ctx.verify(io.BytesIO(content), None, plain)
    except gpgme.GpgmeError:
        return None

    # Extract signer information
    signers = []
    for signature in signatures:
        key_missing = bool(signature.summary & gpgme.SIGSUM_KEY_MISSING)

        if key_missing:
            continue

        key = ctx.get_key(signature.fpr)
        signers.append((key.uids[0].name, key.uids[0].email))

    return signers


def now():
    """
    Returns datetime.datetime.now() and can be easily mocked out
    for tests.
    """
    return datetime.datetime.now()
