# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Debian specific rules for various Distro-Tracker hooks."""

import os.path
import re

from django import forms
from django.conf import settings
from django.db.models import Prefetch
from django.utils.http import urlencode, urlquote_plus
from django.utils.safestring import mark_safe

import requests

from distro_tracker.core.models import (
    ActionItem,
    PackageData,
    UserEmail
)
from distro_tracker.core.package_tables import create_table
from distro_tracker.core.utils import get_decoded_message_payload, get_or_none
from distro_tracker.core.utils.http import HttpCache
from distro_tracker.debci_status.tracker_package_tables import DebciTableField
from distro_tracker.mail import mail_news
from distro_tracker.vendor.common import PluginProcessingError
from distro_tracker.vendor.debian.tracker_tasks import UpdateNewQueuePackages

from .models import DebianBugDisplayManager, DebianContributor
from .tracker_package_tables import UpstreamTableField


def _simplify_pkglist(pkglist, multi_allowed=True, default=None):
    """Replace a single-list item by its sole item. A longer list is left
    as-is (provided multi_allowed is True). An empty list returns the default
    value."""
    if len(pkglist) == 1 and pkglist[0]:
        return pkglist[0]
    elif len(pkglist) > 1 and multi_allowed:
        return pkglist
    return default


def _classify_bts_message(msg, package, keyword):
    bts_package = msg.get('X-Debian-PR-Source',
                          msg.get('X-Debian-PR-Package', ''))
    pkglist = re.split(r'\s+', bts_package.strip())
    # Don't override default package assignation when we find multiple package
    # associated to the mail, otherwise we will send multiple copies of a mail
    # that we already receive multiple times
    multi_allowed = package is None
    pkg_result = _simplify_pkglist(pkglist, multi_allowed=multi_allowed,
                                   default=package)

    # We override the package/keyword only...
    if package is None:  # When needed, because we don't have a suggestion
        override_suggestion = True
    else:  # Or when package suggestion matches the one found in the header
        override_suggestion = package == pkg_result

    if override_suggestion:
        package = pkg_result

    if override_suggestion or keyword is None:
        debian_pr_message = msg.get('X-Debian-PR-Message', '')
        if debian_pr_message.startswith('transcript'):
            keyword = 'bts-control'
        else:
            keyword = 'bts'

    return (package, keyword)


def _classify_dak_message(msg, package, keyword):
    package = msg.get('X-Debian-Package', package)
    subject = msg.get('Subject', '')
    xdak = msg.get('X-DAK', '')
    body = _get_message_body(msg)
    if re.search(r'^Accepted|ACCEPTED', subject):
        if re.search(r'^Accepted.*\(.*source.*\)', subject):
            mail_news.create_news(msg, package, create_package=True)
        if re.search(r'\.dsc\s*$', body, flags=re.MULTILINE):
            keyword = 'upload-source'
        else:
            keyword = 'upload-binary'
    else:
        keyword = 'archive'
    if xdak == 'dak rm':
        # Find all lines giving information about removed source packages
        re_rmline = re.compile(r"^\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.*)", re.M)
        source_removals = re_rmline.findall(body)
        removed_pkgver = {}
        for pkgname, version, arch in source_removals:
            removed_pkgver[pkgname] = (version, arch)
        if package not in removed_pkgver:
            package = _simplify_pkglist(list(removed_pkgver.keys()),
                                        multi_allowed=False,
                                        default=package)
        if package in removed_pkgver and "source" in removed_pkgver[package][1]:
            create_dak_rm_news(msg, package, version=removed_pkgver[package][0],
                               body=body)

    return (package, keyword)


def classify_message(msg, package, keyword):
    """Classify incoming email messages with a package and a keyword."""
    # Default values for git commit notifications
    xgitrepo = msg.get('X-GitLab-Project-Path', msg.get('X-Git-Repo'))
    if xgitrepo:
        if not package:
            if xgitrepo.endswith('.git'):
                xgitrepo = xgitrepo[:-4]
            package = os.path.basename(xgitrepo)
        if not keyword:
            keyword = 'vcs'

    xloop = msg.get_all('X-Loop', ())
    xdebian = msg.get_all('X-Debian', ())
    testing_watch = msg.get('X-Testing-Watch-Package')

    bts_match = 'owner@bugs.debian.org' in xloop
    dak_match = 'DAK' in xdebian
    buildd_match = 'buildd.debian.org' in xdebian
    autoremovals_match = 'release.debian.org/autoremovals' in xdebian

    if bts_match:  # This is a mail of the Debian bug tracking system
        package, keyword = _classify_bts_message(msg, package, keyword)
    elif dak_match:
        package, keyword = _classify_dak_message(msg, package, keyword)
    elif buildd_match:
        keyword = 'build'
        package = msg.get('X-Debian-Package', package)
    elif autoremovals_match:
        keyword = 'summary'
        package = msg.get('X-Debian-Package', package)
    elif testing_watch:
        package = testing_watch
        keyword = 'summary'
        mail_news.create_news(msg, package)

    # Converts old PTS keywords into new ones
    legacy_mapping = {
        'katie-other': 'archive',
        'buildd': 'build',
        'ddtp': 'translation',
        'cvs': 'vcs',
    }
    if keyword in legacy_mapping:
        keyword = legacy_mapping[keyword]
    return (package, keyword)


def add_new_headers(received_message, package_name, keyword, team):
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
        ('X-Debian', 'tracker.debian.org'),
    ]
    if package_name:
        new_headers.append(('X-Debian-Package', package_name))
        new_headers.append(
            ('X-PTS-Package', package_name))  # for compat with old PTS
    if keyword:
        new_headers.append(
            ('X-PTS-Keyword', keyword))       # for compat with old PTS
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
    `BTS <https://bugs.debian.org/pseudo-packages.maintainers>`_
    """
    PSEUDO_PACKAGE_LIST_URL = (
        'https://bugs.debian.org/pseudo-packages.maintainers'
    )
    cache = HttpCache(settings.DISTRO_TRACKER_CACHE_DIRECTORY)
    if not cache.is_expired(PSEUDO_PACKAGE_LIST_URL):
        return
    response, updated = cache.update(PSEUDO_PACKAGE_LIST_URL)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        raise PluginProcessingError()

    if not updated:
        return

    return [
        line.split(None, 1)[0]
        for line in response.text.splitlines()
    ]


def get_package_information_site_url(package_name, source_package=False,
                                     repository=None, version=None):
    """
    Return a link pointing to more information about a package in a
    given repository.
    """
    BASE_URL = 'https://packages.debian.org/'
    PU_URL = 'https://release.debian.org/proposed-updates/'
    SOURCE_PACKAGE_URL_TEMPLATES = {
        'repository': BASE_URL + 'source/{repo}/{package}',
        'no-repository': BASE_URL + 'src:{package}',
        'pu': PU_URL + '{targetsuite}.html#{package}_{version}',
    }
    BINARY_PACKAGE_URL_TEMPLATES = {
        'repository': BASE_URL + '{repo}/{package}',
        'no-repository': BASE_URL + '{package}',
        'pu': '',
    }

    params = {'package': package_name}
    if repository:
        suite = repository['suite'] or repository['codename']
        if suite.endswith('proposed-updates'):
            url_type = 'pu'
            params['version'] = version
            params['targetsuite'] = suite.replace('-proposed-updates', '')\
                .replace('proposed-updates', 'stable')
        else:
            url_type = 'repository'
        params['repo'] = suite
    else:
        url_type = 'no-repository'

    if source_package:
        template = SOURCE_PACKAGE_URL_TEMPLATES[url_type]
    else:
        template = BINARY_PACKAGE_URL_TEMPLATES[url_type]

    return template.format(**params)


def get_developer_information_url(developer_email):
    """
    Return a URL to extra information about a developer, by email address.
    """
    URL_TEMPLATE = 'https://qa.debian.org/developer.php?email={email}'
    return URL_TEMPLATE.format(email=urlquote_plus(developer_email))


def get_external_version_information_urls(package_name):
    """
    The function returns a list of external Web resources which provide
    additional information about the versions of a package.
    """
    return [
        {
            'url': 'https://qa.debian.org/madison.php?package={package}'.format(
                package=urlquote_plus(package_name)),
            'description': 'more versions can be listed by madison',
        },
        {
            'url': 'https://snapshot.debian.org/package/{package}/'.format(
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
    developer = get_or_none(DebianContributor,
                            email__email__iexact=developer_email)
    extra = []
    _add_dmd_entry(extra, developer_email)
    if developer and developer.agree_with_low_threshold_nmu:
        extra.append({
            'display': 'LowNMU',
            'description': 'maintainer agrees with Low Threshold NMU',
            'link': 'https://wiki.debian.org/LowThresholdNmu',
        })
    _add_dm_entry(extra, developer, package_name)
    return extra


def get_uploader_extra(developer_email, package_name=None):
    """
    The function returns a list of additional items that are to be
    included in the general panel next to an uploader. This includes:

     - Whether the uploader is a DebianMaintainer
    """
    developer = get_or_none(DebianContributor,
                            email__email__iexact=developer_email)

    extra = []
    _add_dmd_entry(extra, developer_email)
    _add_dm_entry(extra, developer, package_name)
    return extra


def _add_dmd_entry(extra, email):
    extra.append({
        'display': 'DMD',
        'description': 'UDD\'s Debian Maintainer Dashboard',
        'link': 'https://udd.debian.org/dmd/?{email}#todo'.format(
            email=urlquote_plus(email)
        )
    })


def _add_dm_entry(extra, developer, package_name):
    if package_name and developer and developer.is_debian_maintainer:
        if package_name in developer.allowed_packages:
            extra.append(
                {
                    'display': 'DM',
                    'description': 'Debian Maintainer upload allowed',
                    'link': 'https://ftp-master.debian.org/dm.txt'
                }
            )


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


def create_dak_rm_news(message, package, body=None, version=''):
    """Create a :class:`News` out of a removal email sent by DAK."""
    if not body:
        body = get_decoded_message_payload(message)
    suite = re.search(r"have been removed from (\S+):", body).group(1)
    title = "Removed {ver} from {suite}".format(ver=version, suite=suite)
    return mail_news.create_news(message, package, title=title)


def get_extra_versions(package):
    """
    :returns: The versions of the package found in the NEW queue.
    """
    try:
        info = package.data.get(key=UpdateNewQueuePackages.DATA_KEY)
    except PackageData.DoesNotExist:
        return

    version_url_template = 'https://ftp-master.debian.org/new/{pkg}_{ver}.html'
    return [
        {
            'version': ver['version'],
            'repository_shorthand': 'NEW/' + dist,
            'version_link': version_url_template.format(
                pkg=package.name, ver=ver['version']),
            'repository_link': 'https://ftp-master.debian.org/new.html',
        }
        for dist, ver in info.value.items()
    ]


def pre_login(form):
    """
    If the user has a @debian.org email associated, don't let them log
    in directly through local authentication.
    """
    username = form.cleaned_data.get('username')
    if not username:
        return
    user_email = get_or_none(UserEmail, email__iexact=username)
    emails = [username]
    if user_email and user_email.user:
        emails += [x.email for x in user_email.user.emails.all()]
    if any(email.endswith('@debian.org') for email in emails):
        raise forms.ValidationError(mark_safe(
            "Your account has a @debian.org email address associated. "
            "To log in to the package tracker, you must use a SSL client "
            "certificate generated on "
            "<a href='https://sso.debian.org/'>"
            "sso.debian.org</a> (click on the link!)."))


def post_logout(request, user, next_url=None):
    """
    If the user is authenticated via the SSO, sign them out at the SSO
    level too.
    """
    if request.META.get('REMOTE_USER'):
        if next_url is None:
            next_url = 'https://' + settings.DISTRO_TRACKER_FQDN
        elif next_url.startswith('/'):
            next_url = 'https://' + settings.DISTRO_TRACKER_FQDN + next_url
        return (
            'https://sso.debian.org/cgi-bin/dacs/dacs_signout?' + urlencode({
                'SIGNOUT_HANDLER': next_url
            })
        )


def get_table_fields(table):
    """
    The function provides additional fields which should be displayed in
    the team's packages table
    """
    return table.default_fields + [DebciTableField, UpstreamTableField]


def additional_prefetch_related_lookups():
    """
    :returns: The list with additional lookups to be prefetched along with
        default lookups defined by :class:`BaseTableField`
    """
    return [
        Prefetch(
            'action_items',
            queryset=ActionItem.objects.filter(
                item_type__type_name='vcswatch-warnings-and-errors'
            ).prefetch_related('item_type'),
        ),
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='vcswatch'),
            to_attr='vcswatch_data'
        ),
    ]


def get_vcs_data(package):
    """
    :returns: The dictionary with VCS Watch data to be displayed in
        the template defined by :data:`DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE
        <distro_tracker.project.local_settings.DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE>`
        settings.
    """
    data = {}
    try:
        item = package.vcswatch_data[0]
        data['changelog_version'] = item.value['changelog_version']
    except IndexError:
        # There is no vcs extra data for the package
        pass

    try:
        item = package.action_items.all()[0]
        data['action_item'] = item.to_dict()
        data['action_item']['url'] = item.get_absolute_url()
    except IndexError:
        # There is no action item for the package
        pass
    return data


def get_bug_display_manager_class():
    """Return the class that knows how to display data about Debian bugs."""
    return DebianBugDisplayManager


def get_tables_for_team_page(team, limit):
    """
    The function must return a list of :class:`BasePackageTable` objects
    to be displayed in the main page of teams.

    :param team: The team for which the tables must be added.
    :type package: :class:`Team <distro_tracker.core.models.Team>`
    :param int limit: The number of packages to be displayed in the tables.
    """
    return [
        create_table(slug='general', scope=team, limit=limit),
        create_table(
            slug='general', scope=team, limit=limit, tag='tag:rc-bugs'),
        create_table(
            slug='general', scope=team, limit=limit,
            tag='tag:new-upstream-version'),
        create_table(
            slug='general', scope=team, limit=limit, tag='tag:bugs'),
        create_table(
            slug='general', scope=team, limit=limit,
            tag='tag:debci-failures')
    ]
