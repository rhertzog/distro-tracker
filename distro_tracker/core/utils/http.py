# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Utilities for handling HTTP resource access.
"""

import json
import os
import time
from hashlib import md5

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import is_safe_url, parse_http_date

import requests
from requests.structures import CaseInsensitiveDict

from .compression import get_uncompressed_stream, guess_compression_method


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

    def get_content(self, url, compression="auto"):
        """
        Returns the content of the cached response for the given URL.

        If the file is compressed, then uncompress it, else, consider it
        as plain file.

        :param compression: Specifies the compression method used to generate
            the resource, and thus the compression method one should use to
            decompress it.
        :type compression: str

        :rtype: :class:`bytes`

        """
        if url in self:
            if compression == "auto":
                compression = guess_compression_method(url)

            with open(self._content_cache_file_path(url), 'rb') as temp_file:
                with get_uncompressed_stream(temp_file, compression) as f:
                    return f.read()

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

        :returns: The original HTTP response and a Boolean indicating whether
            the cached value was updated.
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

        verify = settings.DISTRO_TRACKER_CA_BUNDLE or True
        response = requests.get(url, headers=headers, verify=verify,
                                allow_redirects=True)

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


def get_resource_content(url, cache=None, compression="auto",
                         only_if_updated=False, force_update=False):
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
        ``DISTRO_TRACKER_CACHE_DIRECTORY`` cache directory
        is used.
    :type cache: :class:`HttpCache` or an object with an equivalent interface
    :param compression: Specifies the compression method used to generate the
        resource, and thus the compression method one should use to decompress
        it. If auto, then guess it from the url file extension.
    :type compression: str
    :param only_if_updated: if set to `True` returns None when no update is
        done. Otherwise, returns the content in any case.
    :type only_if_updated: bool
    :param force_update: if set to `True` do a new HTTP request even if we
        non-expired data in the cache.
    :type force_update: bool

    :returns: The bytes representation of the resource found at the given url
    :rtype: bytes
    """
    if cache is None:
        cache_directory_path = settings.DISTRO_TRACKER_CACHE_DIRECTORY
        cache = HttpCache(cache_directory_path)

    updated = False
    if force_update or cache.is_expired(url):
        try:
            response, updated = cache.update(url, force=force_update)
        except IOError:
            # Ignore network errors but log them
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Failed to update cache with data from %s", url,
                           exc_info=1)

    if updated:
        # Check HTTP return code
        response.raise_for_status()
    else:  # not updated
        if only_if_updated:
            return  # Stop without returning old data

    return cache.get_content(url, compression=compression)


def get_resource_text(*args, **kwargs):
    """
    Clone of :py:func:`get_resource_content` which transparently decodes
    the downloaded content into text. It supports the same parameters
    and adds the encoding parameter.

    :param encoding: Specifies an encoding to decode the resource content.
    :type encoding: str

    :returns: The textual representation of the resource found at the given url.
    :rtype: str
    """

    encoding = kwargs.pop('encoding', 'utf-8')
    content = get_resource_content(*args, **kwargs)

    if content is not None:
        return content.decode(encoding)


def safe_redirect(to, fallback, allowed_hosts=None):
    """Implements a safe redirection to `to` provided that it's safe. Else,
    goes to `fallback`. `allowed_hosts` describes the list of valid hosts for
    the call to :func:`django.utils.http.is_safe_url`.

    :param to: The URL that one should be returned to.
    :type to: str or None

    :param fallback: A safe URL to fall back on if `to` isn't safe. WARNING!
      This url is NOT checked! The developer is advised to put only an url he
      knows to be safe!
    :type fallback: str

    :param allowed_hosts: A list of "safe" hosts. If `None`, relies on the
      default behaviour of :func:`django.utils.http.is_safe_url`.
    :type allowed_hosts: list of str

    :returns: A ResponseRedirect instance containing the appropriate intel for
      the redirection.
    :rtype: :class:`django.http.HttpResponseRedirectBase`

    """

    if to and is_safe_url(to, allowed_hosts=allowed_hosts):
        return redirect(to)
    return redirect(fallback)
