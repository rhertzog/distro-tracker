# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.sites.models import Site


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns None if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def extract_email_address_from_header(header):
    """
    Extracts the email address from the From email header.

    >>> str(extract_email_address_from_header('Real Name <foo@domain.com>'))
    'foo@domain.com'
    >>> str(extract_email_address_from_header('foo@domain.com'))
    'foo@domain.com'
    """
    from email.utils import parseaddr
    real_name, from_address = parseaddr(header)
    return from_address


def get_decoded_message_payload(message, default_charset='ascii'):
    """
    Extracts the payload of the given ``email.message.Message`` and returns it
    decoded based on the Content-Transfer-Encoding and charset.

    This function is necessary due to the fact that the get_payload method of
    the ``Message`` object in Python3 encodes the payload of messages where
    CTE is 8bit as ``raw-unicode-escape`` instead of using the charset given
    in the message.
    """
    # If the message is multipart there is nothing to decode so None is
    # returned
    if message.is_multipart():
        return None
    # Decodes the message based on transfer encoding and returns bytes
    payload = message.get_payload(decode=True)

    # The charset defaults to ascii if none is given
    charset = message.get_content_charset(default_charset)
    try:
        # Try decoding the given bytes based on the charset of the message
        decoded_payload = payload.decode(charset)
    except UnicodeDecodeError:
        decoded_payload = payload.decode('raw-unicode-escape')

    return decoded_payload


def render_template_to_string(template_name, context=None):
    """
    A custom function to render a template to a string which injects extra
    PTS-specific information to the context, such as the name of the derivative.

    This function is necessary since Django's TEMPLATE_CONTEXT_PROCESSORS only
    work when using a RequestContext, wheras this function can be called
    independently from any HTTP request.
    """
    if context is None:
        context = {}
    extra_context = {
        'PTS_DERIVATIVE_NAME': settings.PTS_DERIVATIVE_NAME,
        'PTS_OWNER_EMAIL': settings.PTS_OWNER_EMAIL,
        'PTS_CONTROL_EMAIL': settings.PTS_CONTROL_EMAIL,
        'PTS_SITE_DOMAIN': Site.objects.get_current(),
    }
    context.update(extra_context)

    return render_to_string(template_name, context)
