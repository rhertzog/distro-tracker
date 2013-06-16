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
Module for encoding and decoding Variable Envelope Return Path addresses.

It is implemented following the recommendations laid out in
`VERP <http://cr.yp.to/proto/verp.txt>`_ and
`<http://cr.yp.to/proto/verp.txt>`_


>>> from pts.core.utils import verp

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
    char: '+' + hex(ord(char)).lstrip('0x').upper()
    for char in _CHARACTERS
}
_DECODE_MAPPINGS = {
    encode_as: char
    for char, encode_as in _ENCODE_MAPPINGS.items()
}


def encode(sender_address, recipient_address, separator='-'):
    """
    Encodes ``sender_address``, ``recipient_address`` to a VERP compliant
    address to be used as the envelope-from (return-path) address.

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
    for encoded_as, char in _DECODE_MAPPINGS.items():
        address = address.replace(encoded_as, char)
    return address


if __name__ == '__main__':
    import doctest
    doctest.testmod()
