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
Utilities for handling HTTP resource access.
"""

from __future__ import unicode_literals
from hashlib import md5
from django.utils import timezone
from django.utils.http import parse_http_date
from django.conf import settings
import os
import time
import json
from requests.utils import CaseInsensitiveDict
import requests


def parse_cache_control_header(header):
    """
    Parses the given Cache-Control header's values.

    :returns: The key-value pairs found in the header.
        If some key did not have an associated value in the header, ``None``
        is used instead.
    :rtype: dict
    """
    parts = header.split(',')
    cache_control = {}
    for part in parts:
        part = part.strip()
        if '=' not in part:
            cache_control[part] = None
            continue
        key, value = part.split('=', 1)
        cache_control[key] = value

    return cache_control


class HttpCache(object):
    """
    A class providing an interface to a cache of HTTP responses.
    """
    def __init__(self, cache_directory_path):
        self.cache_directory_path = cache_directory_path

    def __contains__(self, item):
        cache_file_name = self._content_cache_file_path(item)
        return os.path.exists(cache_file_name)

    def is_expired(self, url):
        """
        If the cached response for the given URL is expired based on
        Cache-Control or Expires headers, returns True.
        """
        if url not in self:
            return True
        headers = self.get_headers(url)

        # First check if the Cache-Control header has set a max-age
        if 'cache-control' in headers:
            cache_control = parse_cache_control_header(headers['cache-control'])
            if 'max-age' in cache_control:
                max_age = int(cache_control['max-age'])
                response_age = int(
                    os.stat(self._header_cache_file_path(url)).st_mtime)
                current_timestamp = int(time.time())

                return current_timestamp - response_age >= max_age

        # Alternatively, try the Expires header
        if 'expires' in headers:
            expires_date = timezone.datetime.utcfromtimestamp(
                parse_http_date(headers['expires']))
            expires_date = timezone.make_aware(expires_date, timezone.utc)
            current_date = timezone.now()

            return current_date > expires_date

        # If there is no cache freshness date consider the item expired
        return True

    def get_content(self, url):
        """
        Returns the content of the cached response for the given URL.

        :rtype: :class:`bytes`
        """
        if url in self:
            with open(self._content_cache_file_path(url), 'rb') as content_file:
                return content_file.read()

    def get_headers(self, url):
        """
        Returns the HTTP headers of the cached response for the given URL.

        :rtype: dict
        """
        if url in self:
            with open(self._header_cache_file_path(url), 'r') as header_file:
                return CaseInsensitiveDict(json.load(header_file))
        else:
            return {}

    def remove(self, url):
        """
        Removes the cached response for the given URL.
        """
        if url in self:
            os.remove(self._content_cache_file_path(url))
            os.remove(self._header_cache_file_path(url))

    def update(self, url, force=False):
        """
        Performs an update of the cached resource. This means that it validates
        that its most current version is found in the cache by doing a
        conditional GET request.

        :param force: To force the method to perform a full GET request, set
            the parameter to ``True``

        :returns: The original HTTP response and a Boolean indicating whether the
            cached value was updated.
        :rtype: two-tuple of (:class:`requests.Response`, ``Boolean``)
        """
        cached_headers = self.get_headers(url)
        headers = {}
        if not force:
            if 'last-modified' in cached_headers:
                headers['If-Modified-Since'] = cached_headers['last-modified']
            if 'etag' in cached_headers:
                headers['If-None-Match'] = cached_headers['etag']
        else:
            # Ask all possible intermediate proxies to return a fresh response
            headers['Cache-Control'] = 'no-cache'

        response = requests.get(url, headers=headers, verify=False)

        # Invalidate previously cached value if the response is not valid now
        if not response.ok:
            self.remove(url)
        elif response.status_code == 200:
            # Dump the content and headers only if a new response is generated
            with open(self._content_cache_file_path(url), 'wb') as content_file:
                content_file.write(response.content)
            with open(self._header_cache_file_path(url), 'w') as header_file:
                json.dump(dict(response.headers), header_file)

        return response, response.status_code != 304

    def _content_cache_file_path(self, url):
        return os.path.join(self.cache_directory_path, self._url_hash(url))

    def _header_cache_file_path(self, url):
        url_hash = self._url_hash(url)
        header_file_name = url_hash + '.headers'
        return os.path.join(self.cache_directory_path, header_file_name)

    def _url_hash(self, url):
        return md5(url.encode('utf-8')).hexdigest()


def get_resource_content(url, cache=None):
    """
    A helper function which returns the content of the resource found at the
    given URL.

    If the resource is already cached in the ``cache`` object and the cached
    content has not expired, the function will not do any HTTP requests and
    will return the cached content.

    If the resource is stale or not cached at all, it is from the Web.

    :param url: The URL of the resource to be retrieved
    :param cache: A cache object which should be used to look up and store
        the cached resource. If it is not provided, an instance of
        :class:`HttpCache` with a
        :data:`pts.project.local_settings.PTS_CACHE_DIRECTORY` cache directory
        is used.
    :type cache: :class:`HttpCache` or an object with an equivalent interface

    :returns: The bytes representation of the resource found at the given url
    :rtype: bytes
    """
    if cache is None:
        cache_directory_path = settings.PTS_CACHE_DIRECTORY
        cache = HttpCache(cache_directory_path)

    try:
        if cache.is_expired(url):
            cache.update(url)
        return cache.get_content(url)
    except:
        pass
