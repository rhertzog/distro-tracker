# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
import re
import urllib
import requests
from django import forms
from django.utils.http import urlencode, urlquote
from django.utils.safestring import mark_safe
from django.conf import settings
from distro_tracker.core.models import PackageBugStats
from distro_tracker.core.models import EmailNews
from distro_tracker.core.models import PackageName
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import BinaryPackageBugStats
from distro_tracker.core.models import PackageExtractedInfo
from distro_tracker.core.models import UserEmail
from distro_tracker.core.utils import get_decoded_message_payload
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils.http import HttpCache
from distro_tracker.core.utils.packages import package_hashdir
from distro_tracker.mail import mail_news
from .models import DebianContributor
from distro_tracker.vendor.common import PluginProcessingError
from distro_tracker.vendor.debian.tracker_tasks import UpdateNewQueuePackages


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
    package = _simplify_pkglist(pkglist, multi_allowed=multi_allowed,
                                default=package)
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
        re_rmline = re.compile(r"^\s*(\S+)\s*\|\s*(\S+)\s*\|.*source", re.M)
        source_removals = re_rmline.findall(body)
        pkglist = []
        for pkgname, version in source_removals:
            pkglist.append(pkgname)
            create_dak_rm_news(msg, pkgname, version=version, body=body)
        package = _simplify_pkglist(pkglist, default=package)

    return (package, keyword)


def classify_message(msg, package, keyword):
    xloop = msg.get_all('X-Loop', ())
    xdebian = msg.get_all('X-Debian', ())
    testing_watch = msg.get('X-Testing-Watch-Package')

    bts_match = 'owner@bugs.debian.org' in xloop
    dak_match = 'DAK' in xdebian

    if bts_match:  # This is a mail of the Debian bug tracking system
        package, keyword = _classify_bts_message(msg, package, keyword)
    elif dak_match:
        package, keyword = _classify_dak_message(msg, package, keyword)
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
        ('X-PTS-Package', package_name),  # for compat with old PTS
        ('X-PTS-Keyword', keyword),       # for compat with old PTS
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
    The function returns a URL which displays extra information about a
    developer, given his email.
    """
    URL_TEMPLATE = 'https://qa.debian.org/developer.php?email={email}'
    return URL_TEMPLATE.format(email=urlquote(developer_email))


def get_external_version_information_urls(package_name):
    """
    The function returns a list of external Web resources which provide
    additional information about the versions of a package.
    """
    return [
        {
            'url': 'https://qa.debian.org/madison.php?package={package}'.format(
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
            'link': 'https://wiki.debian.org/LowThresholdNmu',
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


def get_bug_tracker_url(package_name, package_type, category_name):
    """
    Returns a URL to the BTS for the given package for the given bug category
    name.

    The following categories are recognized for Debian's implementation:

    - ``all`` - all bugs for the package
    - ``all-merged`` - all bugs, including the merged ones
    - ``rc`` - release critical bugs
    - ``rc-merged`` - release critical bugs, including the merged ones
    - ``normal`` - bugs tagged as normal and important
    - ``normal`` - bugs tagged as normal and important, including the merged
      ones
    - ``wishlist`` - bugs tagged as wishlist and minor
    - ``wishlist-merged`` - bugs tagged as wishlist and minor, including the
      merged ones
    - ``fixed`` - bugs tagged as fixed and pending
    - ``fixed-merged`` - bugs tagged as fixed and pending, including the merged
      ones

    :param package_name: The name of the package for which the BTS link should
        be provided.
    :param package_type: The type of the package for which the BTS link should
        be provided. For Debian this is one of: ``source``, ``pseudo``,
        ``binary``.
    :param category_name: The name of the bug category for which the BTS
        link should be provided. It is one of the categories listed above.

    :rtype: :class:`string` or ``None`` if there is no BTS bug for the given
        category.
    """
    URL_PARAMETERS = {
        'all': (
            ('repeatmerged', 'no'),
        ),
        'rc': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'critical'),
            ('sev-inc', 'grave'),
            ('sev-inc', 'serious'),
            ('repeatmerged', 'no'),
        ),
        'normal': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'important'),
            ('sev-inc', 'normal'),
            ('repeatmerged', 'no'),
        ),
        'wishlist': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'minor'),
            ('sev-inc', 'wishlist'),
            ('repeatmerged', 'no'),
        ),
        'fixed': (
            ('archive', 'no'),
            ('pend-inc', 'pending-fixed'),
            ('pend-inc', 'fixed'),
            ('repeatmerged', 'no'),
        ),
        'patch': (
            ('include', 'tags:patch'),
            ('exclude', 'tags:pending'),
            ('pend-exc', 'done'),
            ('repeatmerged', 'no'),
        ),
        'help': (
            ('tag', 'help'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
        ),
        'newcomer': (
            ('tag', 'newcomer'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
        ),
        'all-merged': (
            ('repeatmerged', 'yes'),
        ),
        'rc-merged': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'critical'),
            ('sev-inc', 'grave'),
            ('sev-inc', 'serious'),
            ('repeatmerged', 'yes'),
        ),
        'normal-merged': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'important'),
            ('sev-inc', 'normal'),
            ('repeatmerged', 'yes'),
        ),
        'wishlist-merged': (
            ('archive', 'no'),
            ('pend-exc', 'pending-fixed'),
            ('pend-exc', 'fixed'),
            ('pend-exc', 'done'),
            ('sev-inc', 'minor'),
            ('sev-inc', 'wishlist'),
            ('repeatmerged', 'yes'),
        ),
        'fixed-merged': (
            ('archive', 'no'),
            ('pend-inc', 'pending-fixed'),
            ('pend-inc', 'fixed'),
            ('repeatmerged', 'yes'),
        ),
        'patch-merged': (
            ('include', 'tags:patch'),
            ('exclude', 'tags:pending'),
            ('pend-exc', 'done'),
            ('repeatmerged', 'yes'),
        ),
    }
    if category_name not in URL_PARAMETERS:
        return

    domain = 'https://bugs.debian.org/'
    query_parameters = URL_PARAMETERS[category_name]

    if package_type == 'source':
        query_parameters += (('src', package_name),)
    elif package_type == 'binary':
        if category_name == 'all':
            # All bugs for a binary package don't follow the same pattern as
            # the rest of the URLs.
            return domain + package_name
        query_parameters += (('which', 'pkg'),)
        query_parameters += (('data', package_name),)

    return (
        domain +
        'cgi-bin/pkgreport.cgi?' +
        urllib.urlencode(query_parameters)
    )


def get_bug_panel_stats(package_name):
    """
    Returns bug statistics which are to be displayed in the bugs panel
    (:class:`BugsPanel <distro_tracker.core.panels.BugsPanel>`).

    Debian wants to include the merged bug count for each bug category
    (but only if the count is different than non-merged bug count) so this
    function is used in conjunction with a custom bug panel template which
    displays this bug count in parentheses next to the non-merged count.

    Each bug category count (merged and non-merged) is linked to a URL in the
    BTS which displays more information about the bugs found in that category.

    A verbose name is included for each of the categories.

    The function includes a URL to a bug history graph which is displayed in
    the rendered template.
    """
    bug_stats = get_or_none(PackageBugStats, package__name=package_name)
    if not bug_stats:
        return

    # Map category names to their bug panel display names and descriptions
    category_descriptions = {
        'rc': {
            'display_name': 'RC',
            'description': 'Release Critical',
        },
        'normal': {
            'display_name': 'I&N',
            'description': 'Important and Normal',
        },
        'wishlist': {
            'display_name': 'M&W',
            'description': 'Minor and Wishlist',
        },
        'fixed': {
            'display_name': 'F&P',
            'description': 'Fixed and Pending',
        },
        'newcomer': {
            'display_name': 'newcomer',
            'description': 'newcomer',
            'link': 'https://wiki.debian.org/qa.debian.org/GiftTag',
        }
    }
    # Some bug categories should not be included in the count.
    exclude_from_count = ('newcomer',)

    stats = bug_stats.stats
    categories = []
    total, total_merged = 0, 0
    # From all known bug stats, extract only the ones relevant for the panel
    for category in stats:
        category_name = category['category_name']
        if category_name not in category_descriptions.keys():
            continue
        # Add main bug count
        category_stats = {
            'category_name': category['category_name'],
            'bug_count': category['bug_count'],
        }
        # Add merged bug count
        if 'merged_count' in category:
            if category['merged_count'] != category['bug_count']:
                category_stats['merged'] = {
                    'bug_count': category['merged_count'],
                }
        # Add descriptions
        category_stats.update(category_descriptions[category_name])
        categories.append(category_stats)

        # Keep a running total of all and all-merged bugs
        if category_name not in exclude_from_count:
            total += category['bug_count']
            total_merged += category.get('merged_count', 0)

    # Add another "category" with the bug totals.
    all_category = {
        'category_name': 'all',
        'display_name': 'all',
        'bug_count': total,
    }
    if total != total_merged:
        all_category['merged'] = {
            'bug_count': total_merged,
        }
    # The totals are the first displayed row.
    categories.insert(0, all_category)

    # Add URLs for all categories
    for category in categories:
        # URL for the non-merged category
        url = get_bug_tracker_url(
            package_name, 'source', category['category_name'])
        category['url'] = url

        # URL for the merged category
        if 'merged' in category:
            url_merged = get_bug_tracker_url(
                package_name, 'source', category['category_name'] + '-merged')
            category['merged']['url'] = url_merged

    # Debian also includes a custom graph of bug history
    graph_url = (
        'https://qa.debian.org/data/bts/graphs/'
        '{package_hash}/{package_name}.png'
    )

    # Final context variables which are available in the template
    return {
        'categories': categories,
        'graph_url': graph_url.format(
            package_hash=package_hashdir(package_name),
            package_name=package_name),
    }


def get_binary_package_bug_stats(binary_name):
    """
    Returns the bug statistics for the given binary package.

    Debian's implementation filters out some of the stored bug category stats.
    It also provides a different, more verbose, display name for each of them.
    The included categories and their names are:

    - rc - critical, grave serious
    - normal - important and normal
    - wishlist - wishlist and minor
    - fixed - pending and fixed
    """
    stats = get_or_none(BinaryPackageBugStats, package__name=binary_name)
    if stats is None:
        return
    category_descriptions = {
        'rc': {
            'display_name': 'critical, grave and serious',
        },
        'normal': {
            'display_name': 'important and normal',
        },
        'wishlist': {
            'display_name': 'wishlist and minor',
        },
        'fixed': {
            'display_name': 'pending and fixed',
        },
    }

    def extend_category(category, extra_parameters):
        category.update(extra_parameters)
        return category

    # Filter the bug stats to only include some categories and add a custom
    # display name for each of them.
    return [
        extend_category(category,
                        category_descriptions[category['category_name']])
        for category in stats.stats
        if category['category_name'] in category_descriptions.keys()
    ]


def create_dak_rm_news(message, package, body=None, version=''):
    if not body:
        body = get_decoded_message_payload(message)
    suite = re.search(r"have been removed from (\S+):", body).group(1)
    title = "Removed {ver} from {suite}".format(ver=version, suite=suite)
    return mail_news.create_news(message, package, title=title)


def _create_news_from_dak_email(message):
    x_dak = message['X-DAK']
    katie = x_dak.split()[1]

    if katie != 'rm':
        # Only rm mails are processed.
        return

    body = get_decoded_message_payload(message)
    if not body:
        # The content cannot be decoded.
        return
    # Find all lines giving information about removed source packages
    re_rmline = re.compile(r"^\s*(\S+)\s*\|\s*(\S+)\s*\|.*source", re.M)
    source_removals = re_rmline.findall(body)
    # Add a news item for each source removal.
    created_news = []
    for removal in source_removals:
        package_name, version = removal
        created_news.append(
            create_dak_rm_news(message, package_name, body=body,
                               version=version))
    return created_news


def create_news_from_email_message(message):
    """
    In Debian's implementation, this function creates news when the received
    mail's origin is either the testing watch or katie.
    """
    subject = message.get("Subject", None)
    if not subject:
        return
    subject_words = subject.split()

    # Source upload?
    if len(subject_words) > 1 and subject_words[0] in ('Accepted', 'Installed'):
        if 'source' not in subject:
            # Only source uploads should be considered.
            return
        package_name = subject_words[1]
        package, _ = PackageName.objects.get_or_create(name=package_name)
        return [EmailNews.objects.create_email_news(message, package)]
    # DAK rm?
    elif 'X-DAK' in message:
        return _create_news_from_dak_email(message)
    # Testing Watch?
    elif 'X-Testing-Watch-Package' in message:
        package_name = message['X-Testing-Watch-Package']
        package = get_or_none(SourcePackageName, name=package_name)
        if not package:
            # This package is not tracked
            return
        title = message.get('Subject', '')
        if not title:
            title = 'Testing Watch Message'
        return [
            EmailNews.objects.create_email_news(
                title=title,
                message=message,
                package=package,
                created_by='Britney')
        ]


def get_extra_versions(package):
    """
    :returns: The versions of the package found in the NEW queue.
    """
    try:
        info = package.packageextractedinfo_set.get(
            key=UpdateNewQueuePackages.EXTRACTED_INFO_KEY)
    except PackageExtractedInfo.DoesNotExist:
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
    If the user has a @debian.org email associated, don't let him log in
    directly through local authentication.
    """
    username = form.cleaned_data.get('username')
    user_email = get_or_none(UserEmail, email=username)
    emails = [username]
    if user_email and user_email.user:
        emails += [x.email for x in user_email.user.emails.all()]
    if any(email.endswith('@debian.org') for email in emails):
        raise forms.ValidationError(mark_safe(
            "Your account has a @debian.org email address associated. "
            "To log in to the package tracker, you must use a SSL client "
            "certificate generated on "
            "<a href='https://sso.debian.org/spkac/enroll/'>"
            "sso.debian.org</a> (click on the link!)."))


def post_logout(request, user, next_url=None):
    """
    If the user is authenticated via the SSO, sign him out at the SSO level too.
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
