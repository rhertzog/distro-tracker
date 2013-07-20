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
A skeleton of all vendor-specific function that can be implemented.
"""
from __future__ import unicode_literals


def get_keyword(local_part, msg):
    """
    Takes a local_part of the email
    address to which a message was sent and an
    :py:class:`Message <email.message.Message>` object.
    Should return a keyword which matches the message or None if it does not
    match any keyword.
    """
    pass


def add_new_headers(received_message, package_name, keyword):
    """
    The function should return a list of two-tuples (header_name, header_value)
    which are extra headers that should be added to package messages before
    they are forwarded to subscribers.

    If no extra headers are wanted return an empty list or ``None``

    :param received_message: The original received package message
    :type received_message: :py:class:`email.message.Message`

    :param package_name: The name of the package for which the message was
        intended
    :type package_name: string

    :param keyword: The keyword with which the message is tagged.
    :type keyword: string
    """
    pass


def approve_default_message(msg):
    """
    The function should return a ``Boolean`` indicating whether this message
    should be forwarded to subscribers which are subscribed to default
    keyword messages.

    :param msg: The original received package message
    :type msg: :py:class:`email.message.Message`
    """
    pass


def get_pseudo_package_list():
    """
    The function should return a list of pseudo-packages (their names) which
    are to be considered valid pseudo-packages.
    Any existing pseudo-packages which are no longer found in this list will be
    "demoted" to subscription-only packages, instead of being deleted.

    If there should be no update to the list, the function should return
    ``None``.
    """
    pass


def get_package_information_site_url(package_name,
                                     source_package=False,
                                     repository_name=None):
    """
    The function should return a URL to a package information Web page for
    the given package and repository. The repository parameter is optional.

    If no URL exists for the given parameters, returns ``None``.

    :param package_name: The name of the package for which the URL of the
        package information Web page should be given.
    :type package_name: string

    :param source_package: If ``True`` the function should consider the given
        package a source package, otherwise it should be considered a binary
        package.
    :type source_package: ``Boolean``

    :param repository_name: The name of the repository for which the package
        information should be provided.
    """
    pass


def get_developer_information_url(developer_email):
    """
    The function should return a URL which displays extra information about a
    developer, given his email.

    The function should return ``None`` if the vendor does not provide
    additional developer information or if it does not have the information for
    the particular developer email.

    In this case, on the package page, a <mailto> link will be provided,
    instead of the additional information.

    .. note::
       This function can be used by other modules apart from the general panel

    :param developer_email: The email of the developer for which a URL to a
        site with additional information should be given.
    :type developer_email: string
    """
    pass


def get_external_version_information_urls(package_name):
    """
    The function should return a list of external Web resources which provide
    additional information about the versions of a package.
    Each element of the list should be a dictionary with the keys:
    - url
    - description

    The function should return ``None`` if the vendor does not want to provide
    extra version information URLs.

    :param package_name: The name of the package for which external version
        information URLs should be provided.
    :type package_name: string
    """
    pass


def get_maintainer_extra(developer_email, package_name=None):
    """
    The function should return a list of additional items that are to be
    included in the general panel next to the maintainer.

    Each item needs to be a dictionary itself and can contain the following
    keys:
    - display
    - description
    - url

    .. note::
       Only the ``display`` key is mandatory.

    The function should return ``None`` if the vendor does not wish to include
    any extra items.

    :param developer_email: The email of the maintainer for which extra
        information is requested.
    :param package_name: The name of the package where the contributor is the
        maintainer and for which extra information should be provided.
        This parameter is included in case vendors want to provide different
        information based on the package page where the information will be
        displayed.
    """
    pass


def get_uploader_extra(developer_email, package_name=None):
    """
    The function should return a list of additional items that are to be
    included in the general panel next to an uploader.

    Each item needs to be a dictionary itself and can contain the following
    keys:
    - display
    - description
    - url

    .. note::
       Only the ``display`` key is mandatory.

    The function should return ``None`` if the vendor does not wish to include
    any extra items.

    :param developer_email: The email of the uploader for which extra
        information is requested.
    :param package_name: The name of the package where the contributor is an
        uploader and for which extra information should be provided.
        This parameter is included in case vendors want to provide different
        information based on the package page where the information will be
        displayed.
    """
    pass
