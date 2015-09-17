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
A skeleton of all vendor-specific function that can be implemented.
"""
from __future__ import unicode_literals


def get_keyword(suggested_keyword, msg):
    """
    The function should return a keyword which matches the message or ``None``
    if it does not match any keyword or the vendor does not provide any custom
    keyword matching.

    :param suggested_keyword: The local part of the email address to which the
        message was sent
    :type suggested_keyword: string

    :param msg: The original received package message
    :type msg: :py:class:`Message <email.message.Message>`
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


def allow_package(stanza):
    """
    The function provides a way for vendors to exclude some packages from being
    saved in the database.

    :param stanza: The raw package entry from a ``Sources`` file.
    :type stanza: case-insensitive dict
    """
    pass


def get_bug_tracker_url(package_name, package_type, category_name):
    """
    The function provides a way for vendors to give a URL to a bug tracker
    based on a package name, its type and the bug category name.

    This function is used by
    :class:`BugsPanel <distro_tracker.core.panels.BugsPanel>` to
    include a link to the bug tracking site on top of the known bug statistics.

    :param package_name: The name of the package for which the bug tracker URL
        should be provided.
    :param package_type: The type of the package for which the bug tracker URL
        should be provided. It is one of: ``source``, ``pseudo`` or ``binary``.
    :param category_name: The name of the bug tracker category for which the
        URL should be provided.

    :returns: The bug tracker URL for the package and given category.
    :rtype: string or ``None`` if the vendor does not have a bug tracker URL
        for the given parameters.
    """
    pass


def get_bug_panel_stats(package_name):
    """
    The function provides a way for vendors to customize the bug categories
    displayed in the :class:`BugsPanel <distro_tracker.core.panels.BugsPanel>`.

    This is useful if the vendor does not want to have all categories which are
    stored in the
    :class:`PackageBugStats <distro_tracker.core.models.PackageBugStats>`
    displayed on the package page.

    In this case the return value must be a list of dicts where each element
    describes a single bug category for the given package.

    Each dict has to provide at minimum the following keys:

    - ``category_name`` - the name of the bug category
    - ``bug_count`` - the number of known bugs for the given package and
      category

    Optionally, the following keys can be provided:

    - ``display_name`` - a name for the bug category which is displayed in the
      list. If this is not provided, the ``category_name`` is used instead.
    - ``description`` - text further explaining the category which shows up in a
      tooltip when mousing over the display name.

    Another use case is when the vendor provides a custom
    :data:`DISTRO_TRACKER_BUGS_PANEL_TEMPLATE
    <distro_tracker.project.local_settings.DISTRO_TRACKER_BUGS_PANEL_TEMPLATE>`
    in which case the return value is passed to the template in the
    ``panel.context`` context variable and does not need to follow any special
    format.
    """
    pass


def get_binary_package_bug_stats(binary_name):
    """
    The function provides a way for vendors to provide customized bug stats
    for binary packages.

    This function is used by the
    :class:`BinariesInformationPanel
    <distro_tracker.core.panels.BinariesInformationPanel>`
    to display the bug information next to the binary name.

    It should return a list of dicts where each element describes a single bug
    category for the given package.

    Each dict has to provide at minimum the following keys:

    - ``category_name`` - the name of the bug category
    - ``bug_count`` - the number of known bugs for the given package and
      category

    Optionally, the following keys can be provided:

    - ``display_name`` - a name for the bug category. It is used by the
      :class:`BinariesInformationPanel
      <distro_tracker.core.panels.BinariesInformationPanel>`
      to display a tooltip when mousing over the bug count number.
    """
    pass


def create_news_from_email_message(message):
    """
    The function provides a way for vendors to customize the news created from
    received emails.

    The function should create a :class:`distro_tracker.core.models.News` model
    instance for any news items it wishes to generate out of the received email
    message.  The content type of the created :class:`News
    <distro_tracker.core.models.News>` does not have to be ``message/rfc822`` if
    the created news is only based on information found in the message. It
    should be set to ``message/rfc822`` if the content of the news is set to the
    content of the email message to make sure it is rendered appropriately.

    The function :func:`distro_tracker.mail.mail_news.process.create_news` can
    be used to create simple news from the message after determining that it
    should in fact be created.

    The function should return a list of created
    :class:`News <distro_tracker.core.models.News>`
    instances or ``None`` if it did not create any.
    """
    pass


def get_extra_versions(package):
    """
    The function provides additional versions which should be displayed in the
    versions panel.

    Each version to be displayed should be a dict with the following keys:

    - version
    - repository_shorthand
    - version_link - optional
    - repository_link - optional

    The return value should be a list of such versions or ``None`` if the vendor
    does not wish to provide any additional versions.

    :param package: The package for which additional versions should be
        provided.
    :type package: :class:`PackageName <distro_tracker.core.models.PackageName>`
    """
    pass
