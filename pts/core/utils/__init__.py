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
from django.template.loader import render_to_string

from .email_messages import extract_email_address_from_header
from .email_messages import get_decoded_message_payload
from .email_messages import message_from_bytes


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns None if it
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

    This function is necessary since Django's TEMPLATE_CONTEXT_PROCESSORS only
    work when using a RequestContext, wheras this function can be called
    independently from any HTTP request.
    """
    from pts.core import context_processors
    if context is None:
        context = {}
    extra_context = context_processors.PTS_EXTRAS
    context.update(extra_context)

    return render_to_string(template_name, context)
