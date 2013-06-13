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


class DuplicateDict(object):
    """
    A container class which stores key, value pairs where the key does not
    have to be unique.

    When accessing the container, the value returned for a given key is defined
    as the first value which was put in the container for that key.

    >>> d = DuplicateDict()
    >>> d.add('key1', 'value1')
    >>> d.add('key2', 'value2')
    >>> d.add('key1', 'value3')
    >>> str(d.get('key1'))
    'value1'
    >>> str(d.get('key2'))
    'value2'

    When iterating through all the items in the container, all key, value pairs
    are returned in an undefined order.

    >>> l = list((str(key), str(value)) for key, value in d.items())
    >>> len(l)
    3
    >>> ('key1', 'value1') in l
    True
    >>> ('key1', 'value3') in l
    True
    >>> ('key2', 'value2') in l
    True
    """
    def __init__(self):
        self._items = {}

    def items(self):
        return (
            (key, value)
            for key, values in self._items.items()
            for value in values
        )

    def __iter__(self):
        def wrap():
            # The key is yielded as many times as there are items in the dict
            for key, values in self._items.items():
                for _ in values:
                    yield key
        return wrap()

    def get(self, key, default=None):
        if key not in self._items:
            return default
        else:
            return self._items[key][0]

    def __getitem__(self, key):
        return self.get(key)

    def add(self, key, value):
        if key not in self._items:
            self._items[key] = []
        self._items[key].append(value)

    def set(self, key, value):
        if key not in self._items:
            self._items[key] = []
        if len(self._items[key]) == 0:
            self._items[key].append(value)
        else:
            self._items[key][0] = value
