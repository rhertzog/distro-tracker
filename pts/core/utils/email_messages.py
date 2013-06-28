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
Module including some utility functions and classes for manipulating email.
"""
from __future__ import unicode_literals
from django.utils import six


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


def get_decoded_message_payload(message, default_charset='utf-8'):
    """
    Extracts the payload of the given ``email.message.Message`` and returns it
    decoded based on the Content-Transfer-Encoding and charset.
    """
    # If the message is multipart there is nothing to decode so None is
    # returned
    if message.is_multipart():
        return None
    # Decodes the message based on transfer encoding and returns bytes
    payload = message.get_payload(decode=True)

    # The charset defaults to ascii if none is given
    charset = message.get_content_charset(default_charset)
    return payload.decode(charset)


class BytesEmailMessage(object):
    """
    A wrapper around an ``email.message.Message`` object which changes its
    ``as_string`` method to always return bytes.

    This means that in Python3 the message will not end up with modified
    Content-Transfer-Encoding header and content when the given content is
    parsed from bytes. Rather, it returns the original bytes, as expected.

    To obtain an instance of this object, clients should generally use the
    helper method ``message_from_bytes`` given in this module, but passing
    an already existing ``email.message.Message`` object to the constructor if
    the desired behavior of ``as_string`` is desired is possible too.
    """
    def __init__(self, message):
        self.message = message

    def __getattr__(self, name):
        return getattr(self.message, name)

    def __getitem__(self, name):
        return self.message.__getitem__(name)

    def __setitem__(self, name, val):
        return self.message.__setitem__(name, val)

    def __contains__(self, name):
        return self.message.__contains__(name)

    def __delitem__(self, name):
        return self.message.__delitem__(name)

    def __len__(self):
        return self.message.__len__()

    def as_string(self, unixfrom=False, maxheaderlen=0):
        if six.PY3:
            from email.generator import BytesGenerator as Generator
        else:
            from email.generator import Generator

        bytes_buffer = six.BytesIO()
        generator = Generator(
            bytes_buffer, mangle_from_=False, maxheaderlen=maxheaderlen)
        generator.flatten(self.message, unixfrom=unixfrom)
        return bytes_buffer.getvalue()


def message_from_bytes(message_bytes):
    """
    Returns a Message object from the given bytes.

    The function is used to achieve Python2/3 compatibility by returning an
    object whose as_string method has the same behavior in both versions.

    Namely, it makes sure that parsing the message's bytes with this method and
    then returning them by using the returned object's as_string method is an
    idempotent operation.
    """
    if six.PY3:
        from email import message_from_bytes as email_message_from_bytes
    else:
        from email import message_from_string as email_message_from_bytes
    message = email_message_from_bytes(message_bytes)

    return BytesEmailMessage(message)
