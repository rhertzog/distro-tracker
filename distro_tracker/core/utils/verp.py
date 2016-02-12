# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Module for encoding and decoding Variable Envelope Return Path addresses.

It is implemented following the recommendations laid out in
`VERP <http://cr.yp.to/proto/verp.txt>`_ and
`<http://www.courier-mta.org/draft-varshavchik-verp-smtpext.txt>`_


>>> from distro_tracker.core.utils import verp

>>> str(verp.encode('itny-out@domain.com', 'node42!ann@old.example.com'))
'itny-out-node42+21ann=old.example.com@domain.com'

>>> map(str, decode('itny-out-node42+21ann=old.example.com@domain.com'))
['itny-out@domain.com', 'node42!ann@old.example.com']
"""
from __future__ import unicode_literals

__all__ = ('encode', 'decode')

_RETURN_ADDRESS_TEMPLATE = (
    '{slocal}{separator}{encoderlocal}={encoderdomain}@{sdomain}')

_CHARACTERS = ('@', ':', '%', '!', '-', '[', ']', '+')
_ENCODE_MAPPINGS = {
    char: '+{val:0X}'.format(val=ord(char))
    for char in _CHARACTERS
}


def encode(sender_address, recipient_address, separator='-'):
    """
    Encodes ``sender_address``, ``recipient_address`` to a VERP compliant
    address to be used as the envelope-from (return-path) address.

    :param sender_address: The email address of the sender
    :type sender_address: string

    :param recipient_address: The email address of the recipient
    :type recipient_address: string

    :param separator: The separator to be used between the sender's local
        part and the encoded recipient's local part in the resulting
        VERP address.

    :rtype: string

    >>> str(encode('itny-out@domain.com', 'node42!ann@old.example.com'))
    'itny-out-node42+21ann=old.example.com@domain.com'
    >>> str(encode('itny-out@domain.com', 'tom@old.example.com'))
    'itny-out-tom=old.example.com@domain.com'
    >>> str(encode('itny-out@domain.com', 'dave+priority@new.example.com'))
    'itny-out-dave+2Bpriority=new.example.com@domain.com'

    >>> str(encode('bounce@dom.com', 'user+!%-:@[]+@other.com'))
    'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com'
    """
    # Split the addresses in two parts based on the last occurrence of '@'
    slocal, sdomain = sender_address.rsplit('@', 1)
    rlocal, rdomain = recipient_address.rsplit('@', 1)
    # Encode recipient parts by replacing relevant characters
    encoderlocal, encoderdomain = map(_encode_chars, (rlocal, rdomain))
    # Putting it all together
    return _RETURN_ADDRESS_TEMPLATE.format(slocal=slocal,
                                           separator=separator,
                                           encoderlocal=encoderlocal,
                                           encoderdomain=encoderdomain,
                                           sdomain=sdomain)


def decode(verp_address, separator='-'):
    """
    Decodes the given VERP encoded from address and returns the original
    sender address and recipient address, returning them as a tuple.

    :param verp_address: The return path address
    :type sender_address: string

    :param separator: The separator to be expected between the sender's local
        part and the encoded recipient's local part in the given
        ``verp_address``

    >>> from_email, to_email = 'bounce@domain.com', 'user@other.com'
    >>> decode(encode(from_email, to_email)) == (from_email, to_email)
    True

    >>> map(str, decode('itny-out-dave+2Bpriority=new.example.com@domain.com'))
    ['itny-out@domain.com', 'dave+priority@new.example.com']
    >>> map(str, decode('itny-out-node42+21ann=old.example.com@domain.com'))
    ['itny-out@domain.com', 'node42!ann@old.example.com']
    >>> map(str, decode('bounce-addr+2B40=dom.com@asdf.com'))
    ['bounce@asdf.com', 'addr+40@dom.com']

    >>> s = 'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com'
    >>> str(decode(s)[1])
    'user+!%-:@[]+@other.com'
    """
    left_part, sdomain = verp_address.rsplit('@', 1)
    left_part, encodedrdomain = left_part.rsplit('=', 1)
    slocal, encodedrlocal = left_part.rsplit(separator, 1)
    rlocal, rdomain = map(_decode_chars, (encodedrlocal, encodedrdomain))

    return (slocal + '@' + sdomain, rlocal + '@' + rdomain)


def _encode_chars(address):
    """
    Helper function to replace the special characters in the recipient's
    address.
    """
    return ''.join(_ENCODE_MAPPINGS.get(char, char) for char in address)


def _decode_chars(address):
    """
    Helper function to replace the encoded special characters with their
    regular character representation.
    """
    for char in _CHARACTERS:
        address = address.replace(_ENCODE_MAPPINGS[char], char)
        address = address.replace(_ENCODE_MAPPINGS[char].lower(), char)
    return address


if __name__ == '__main__':
    import doctest
    doctest.testmod()
