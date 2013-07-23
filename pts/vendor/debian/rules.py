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
import re
import requests
from django.conf import settings
from pts.core.utils import get_decoded_message_payload
from pts.core.utils import get_or_none
from pts.core.utils.http import HttpCache
from .models import DebianContributor
from pts.vendor.common import PluginProcessingError


def get_keyword(local_part, msg):
    """
    The function should return a keyword which matches the message or ``None``
    if it does not match any keyword or the vendor does not provide any custom
    keyword matching.

    Debian provides matching for the following keywords:
     - bts-control
     - bts
     - upload-source
     - upload-binary
     - archive

    :param local_part: The local part of the email address to which the message
        was sent
    :type local_part: string

    :param msg: The original received package message
    :type msg: :py:class:`Message <email.message.Message>`
    """
    re_accepted_installed = re.compile('^Accepted|INSTALLED|ACCEPTED')
    re_comments_regarding = re.compile(r'^Comments regarding .*\.changes$')

    body = _get_message_body(msg)
    xloop = msg.get_all('X-Loop', ())
    subject = msg.get('Subject', '')
    xdak = msg.get_all('X-DAK', '')
    debian_pr_message = msg.get('X-Debian-PR-Message', '')

    owner_match = 'owner@bugs.debian.org' in xloop

    if owner_match and debian_pr_message.startswith('transcript'):
        return 'bts-control'
    elif owner_match and debian_pr_message:
        return 'bts'
    elif xdak and re_accepted_installed.match(subject):
        if re.search(r'\.dsc\s*$', body, flags=re.MULTILINE):
            return 'upload-source'
        else:
            return 'upload-binary'
    elif xdak or re_comments_regarding.match(subject):
        return 'archive'


def add_new_headers(received_message, package_name, keyword):
    """
    Debian adds the following new headers:
     - X-Debian-Package
     - X-Debian

    :param received_message: The original received package message
    :type received_message: :py:class:`email.message.Message`

    :param package_name: The name of the package for which the message was
        intended
    :type package_name: string

    :param keyword: The keyword with which the message is tagged.
    :type keyword: string
    """
    new_headers = [
        ('X-Debian-Package', package_name),
        ('X-Debian', 'PTS'),
    ]
    return new_headers


def approve_default_message(msg):
    """
    Debian approves a default message only if it has a X-Bugzilla-Product
    header.

    :param msg: The original received package message
    :type msg: :py:class:`email.message.Message`
    """
    return 'X-Bugzilla-Product' in msg


def _get_message_body(msg):
    """
    Returns the message body, joining together all parts into one string.

    :param msg: The original received package message
    :type msg: :py:class:`email.message.Message`
    """
    return '\n'.join(get_decoded_message_payload(part)
                     for part in msg.walk() if not part.is_multipart())


def get_pseudo_package_list():
    """
    Existing pseudo packages for Debian are obtained from
    `BTS <http://bugs.debian.org/pseudo-packages.maintainers>`_
    """
    PSEUDO_PACKAGE_LIST_URL = (
        'http://bugs.debian.org/pseudo-packages.maintainers'
    )
    cache = HttpCache(settings.PTS_CACHE_DIRECTORY)
    if not cache.is_expired(PSEUDO_PACKAGE_LIST_URL):
        return
    response, updated = cache.update(PSEUDO_PACKAGE_LIST_URL)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise PluginProcessingError()

    if not updated:
        return

    return [
        line.split(None, 1)[0]
        for line in response.text.splitlines()
    ]


def get_package_information_site_url(package_name,
                                     source_package=False,
                                     repository_name=None):
    BASE_URL = 'http://packages.debian.org/'
    SOURCE_PACKAGE_URL_TEMPLATES = {
        'repository': BASE_URL + 'source/{repo}/{package}',
        'no-repository': BASE_URL + 'src:{package}',
    }
    BINARY_PACKAGE_URL_TEMPLATES = {
        'repository': BASE_URL + '{repo}/{package}',
        'no-repository': BASE_URL + '{package}',
    }

    params = {'package': package_name}
    if repository_name:
        url_type = 'repository'
        params['repo'] = repository_name
    else:
        url_type = 'no-repository'

    if source_package:
        template = SOURCE_PACKAGE_URL_TEMPLATES[url_type]
    else:
        template = BINARY_PACKAGE_URL_TEMPLATES[url_type]

    return template.format(**params)


def get_developer_information_url(developer_email):
    """
    The function returns a URL which displays extra information about a
    developer, given his email.
    """
    URL_TEMPLATE = 'http://qa.debian.org/developer.php?email={email}'
    return URL_TEMPLATE.format(email=developer_email)


def get_external_version_information_urls(package_name):
    """
    The function returns a list of external Web resources which provide
    additional information about the versions of a package.
    """
    return [
        {
            'url': 'http://qa.debian.org/madison.php?package={package}'.format(
                package=package_name),
            'description': 'more versions can be listed by madison',
        },
        {
            'url': 'http://snapshot.debian.org/package/{package}/'.format(
                package=package_name),
            'description': 'old versions available from snapshot.debian.org',
        }
    ]


def get_maintainer_extra(developer_email, package_name=None):
    """
    The function returns a list of additional items that are to be
    included in the general panel next to the maintainer. This includes:
     
     - Whether the maintainer agrees with lowthreshold NMU
     - Whether the maintainer is a Debian Maintainer
    """
    developer = get_or_none(DebianContributor, email__email=developer_email)
    if not developer:
        # Debian does not have any extra information to include in this case.
        return None
    extra = []
    if developer.agree_with_low_threshold_nmu:
        extra.append({
            'display': 'LowNMU',
            'description': 'maintainer agrees with Low Threshold NMU',
            'link': 'http://wiki.debian.org/LowThresholdNmu',
        })
    if package_name and developer.is_debian_maintainer:
        if package_name in developer.allowed_packages:
            extra.append({
                'display': 'dm',
            })
    return extra


def get_uploader_extra(developer_email, package_name=None):
    """
    The function returns a list of additional items that are to be
    included in the general panel next to an uploader. This includes:
     
     - Whether the uploader is a DebianMaintainer
    """
    if package_name is None:
        return

    developer = get_or_none(DebianContributor, email__email=developer_email)
    if not developer:
        return

    if developer.is_debian_maintainer:
        if package_name in developer.allowed_packages:
            return [{
                'display': 'dm',
            }]


def allow_package(stanza):
    """
    The function provides a way for vendors to exclude some packages from being
    saved in the database.

    In Debian's case, this is done for packages where the ``Extra-Source-Only``
    is set since those packages are in the repository only for various
    compliance reasons.

    :param stanza: The raw package entry from a ``Sources`` file.
    :type stanza: case-insensitive dict
    """
    return 'Extra-Source-Only' not in stanza
