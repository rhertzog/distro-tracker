# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Module including some utility functions and classes for manipulating email.
"""
from __future__ import unicode_literals
from django.core.mail import EmailMessage
from django.utils import six
from django.utils.encoding import force_bytes
from email.mime.base import MIMEBase
import re
import copy
import email
import types


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


def name_and_address_from_string(content):
    """
    Takes an address in almost-RFC822 format and turns it into a dict
    {'name': real_name, 'email': email_address}

    The difference with email.utils.parseaddr and rfc822.parseaddr
    is that this routine allows unquoted commas to appear in the real name
    (in violation of RFC822).
    """
    from email.utils import parseaddr
    hacked_content = content.replace(",", "WEWANTNOCOMMAS")
    name, mail = parseaddr(hacked_content)
    if mail:
        return {
            'name': name.replace("WEWANTNOCOMMAS", ","),
            'email': mail.replace("WEWANTNOCOMMAS", ",")
        }
    else:
        return None


def names_and_addresses_from_string(content):
    """
    Takes a string with addresses in RFC822 format and returns a list of dicts
    {'name': real_name, 'email': email_address}
    It tries to be forgiving about unquoted commas in addresses.
    """
    all_parts = [
        name_and_address_from_string(part)
        for part in re.split('(?<=>)\s*,\s*', content)
    ]
    return [
        part
        for part in all_parts
        if part is not None
    ]


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
    if payload is None:
        return None

    # The charset defaults to ascii if none is given
    charset = message.get_content_charset(default_charset)
    try:
        return payload.decode(charset)
    except (UnicodeDecodeError, LookupError):
        # If we did not get the charset right, assume it's latin1 and make
        # sure to not fail furter
        return payload.decode('latin1', 'replace')


def patch_message_for_django_compat(message):
    """
    Live patch the :py:class:`email.message.Message` object passed as
    parameter so that:
    - the as_string() method return the same set of bytes it has been parsed
      from (to preserve as much as possible the original message)
    - the as_bytes() is added too (this method is expected by Django's SMTP
      backend)
    """
    # Django expects patched versions of as_string/as_bytes, see
    # django/core/mail/message.py
    def as_string(self, unixfrom=False, maxheaderlen=0, linesep='\n'):
        """
        Returns the payload of the message encoded as bytes.
        """
        if six.PY3:
            from email.generator import BytesGenerator as Generator
        else:
            from email.generator import Generator

        fp = six.BytesIO()
        g = Generator(fp, mangle_from_=False, maxheaderlen=maxheaderlen)
        if six.PY3:
            g.flatten(self, unixfrom=unixfrom, linesep=linesep)
        else:
            g.flatten(self, unixfrom=unixfrom)
        return force_bytes(fp.getvalue(), 'utf-8')

    message.as_string = types.MethodType(as_string, message)
    message.as_bytes = message.as_string
    return message


def message_from_bytes(message_bytes):
    """
    Returns a live-patched :class:`email.Message` object from the given
    bytes.

    The changes ensure that parsing the message's bytes with this method
    and then returning them by using the returned object's as_string
    method is an idempotent operation.

    An as_bytes method is also created since Django's SMTP backend relies
    on this method (which is usually brought by its own
    :class:`django.core.mail.SafeMIMEText` object but that we don't use
    in our :class:`CustomEmailMessage`).
    """
    if six.PY3:
        from email import message_from_bytes as email_message_from_bytes
    else:
        from email import message_from_string as email_message_from_bytes
    message = email_message_from_bytes(message_bytes)

    return patch_message_for_django_compat(message)


class CustomEmailMessage(EmailMessage):
    """
    A subclass of :class:`django.core.mail.EmailMessage` which can be fed
    an :class:`email.message.Message` instance to define the body of the
    message.

    If :attr:`msg` is set, the :attr:`body <django.core.mail.EmailMessage.body>`
    attribute is ignored.

    If the user wants to attach additional parts to the message, the
    :meth:`attach` method can be used but the user must ensure that the given
    ``msg`` instance is a multipart message before doing so.

    Effectively, this is also a wrapper which allows sending instances of
    :class:`email.message.Message` via Django email backends.
    """
    def __init__(self, msg=None, *args, **kwargs):
        """
        Use the keyword argument ``msg`` to set the
        :class:`email.message.Message` instance which should be used to define
        the body of the message.  The original object is copied.

        If no ``msg`` is set, the object's behaviour is identical to
        :class:`django.core.mail.EmailMessage`
        """
        super(CustomEmailMessage, self).__init__(*args, **kwargs)
        self.msg = msg

    def message(self):
        """
        Returns the underlying :class:`email.message.Message` object.
        In case the user did not set a :attr:`msg` attribute for this instance
        the parent :meth:`EmailMessage.message
        <django.core.mail.EmailMessage.message>` method is used.
        """
        if self.msg:
            msg = self._attach_all()
            return msg
        else:
            return EmailMessage.message(self)

    def _attach_all(self):
        """
        Attaches all existing attachments to the given message ``msg``.
        """
        msg = self.msg
        if self.attachments:
            assert self.msg.is_multipart()
            msg = copy.deepcopy(self.msg)
            for attachment in self.attachments:
                if isinstance(attachment, MIMEBase):
                    msg.attach(attachment)
                else:
                    msg.attach(self._create_attachment(*attachment))
        return msg


def decode_header(header, default_encoding='utf-8'):
    """
    Decodes an email message header and returns it coded as a unicode
    string.

    This is necessary since it is possible that a header is made of multiple
    differently encoded parts which makes :func:`email.header.decode_header`
    insufficient.
    """
    if header is None:
        return None
    decoded_header = email.header.decode_header(header)
    # Join all the different parts of the header into a single unicode string
    result = ''
    for part, encoding in decoded_header:
        if encoding == 'unknown-8bit':
            # Python 3 returns unknown-8bit instead of None when you have 8bit
            # characters without any encoding information
            encoding = 'iso-8859-1'
        if isinstance(part, six.binary_type):
            encoding = encoding if encoding else default_encoding
            try:
                result += part.decode(encoding)
            except UnicodeDecodeError:
                result += part.decode('iso-8859-1', 'replace')
        else:
            result += part
    return result


def unfold_header(header):
    """
    Unfolding is the process to remove the line wrapping added by mail agents.
    An header is a single logical line and they are not allowed to be multi-line
    values.

    We need to unfold their values in particular when we want to reuse the
    values to compose a reply message as Python's email API chokes on those
    newline characters.

    If header is None, the return value is None as well.

    :param:header: the header value to unfold
    :type param: str
    :returns: the unfolded version of the header.
    :rtype: str
    """
    if header is None:
        return None
    return re.sub(r'\r?\n(\s)', r'\1', header, 0, re.MULTILINE)
