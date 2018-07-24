# -*- coding: utf-8 -*-

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
Debian-specific models.
"""

import re

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.http import urlencode
from jsonfield import JSONField

from distro_tracker.core.models import (
    BinaryPackageBugStats,
    BugDisplayManager,
    PackageBugStats,
    PackageName,
    SourcePackageName,
)
from distro_tracker.core.utils import SpaceDelimitedTextField, get_or_none
from distro_tracker.core.utils.packages import package_hashdir


class DebianContributor(models.Model):
    """
    Model containing additional Debian-specific information about contributors.
    """
    email = models.OneToOneField('django_email_accounts.UserEmail',
                                 on_delete=models.CASCADE)
    agree_with_low_threshold_nmu = models.BooleanField(default=False)
    is_debian_maintainer = models.BooleanField(default=False)
    allowed_packages = SpaceDelimitedTextField(blank=True)

    def __str__(self):
        return 'Debian contributor <{email}>'.format(email=self.email)


class LintianStats(models.Model):
    """
    Model for lintian stats of packages.
    """
    package = models.OneToOneField(PackageName, related_name='lintian_stats',
                                   on_delete=models.CASCADE)
    stats = JSONField()

    def __str__(self):
        return 'Lintian stats for package {package}'.format(
            package=self.package)

    def get_lintian_url(self, full=False):
        """
        Returns the lintian URL for the package matching the
        :class:`LintianStats
        <distro_tracker.vendor.debian.models.LintianStats>`.

        :param full: Whether the URL should include the full lintian report or
            only the errors and warnings.
        :type full: Boolean
        """
        package = get_or_none(SourcePackageName, pk=self.package.pk)
        if not package:
            return ''
        maintainer_email = ''
        if package.main_version:
            maintainer = package.main_version.maintainer
            if maintainer:
                maintainer_email = maintainer.email
        # Adapt the maintainer URL to the form expected by lintian.debian.org
        lintian_maintainer_email = re.sub(
            r"""[àáèéëêòöøîìùñ~/\(\)" ']""",
            '_',
            maintainer_email)

        report = 'full' if full else 'maintainer'

        return (
            'https://lintian.debian.org/{report}/'
            '{maintainer}.html#{pkg}'.format(
                report=report,
                maintainer=lintian_maintainer_email,
                pkg=self.package)
        )


class PackageTransition(models.Model):
    package = models.ForeignKey(PackageName, related_name='package_transitions',
                                on_delete=models.CASCADE)
    transition_name = models.CharField(max_length=50)
    status = models.CharField(max_length=50, blank=True, null=True)
    reject = models.BooleanField(default=False)

    def __str__(self):
        return "Transition {name} ({status}) for package {pkg}".format(
            name=self.transition_name, status=self.status, pkg=self.package)


class PackageExcuses(models.Model):
    package = models.OneToOneField(PackageName, related_name='excuses',
                                   on_delete=models.CASCADE)
    excuses = JSONField()

    def __str__(self):
        return "Excuses for the package {pkg}".format(pkg=self.package)


class BuildLogCheckStats(models.Model):
    package = models.OneToOneField(
        SourcePackageName,
        related_name='build_logcheck_stats',
        on_delete=models.CASCADE)
    stats = JSONField()

    def __str__(self):
        return "Build logcheck stats for {pkg}".format(pkg=self.package)


class UbuntuPackage(models.Model):
    package = models.OneToOneField(
        PackageName,
        related_name='ubuntu_package',
        on_delete=models.CASCADE)
    version = models.TextField(max_length=100)
    bugs = JSONField(null=True, blank=True)
    patch_diff = JSONField(null=True, blank=True)

    def __str__(self):
        return "Ubuntu package info for {pkg}".format(pkg=self.package)


class DebianBugDisplayManager(BugDisplayManager):
    table_field_template_name = 'debian/package-table-fields/bugs.html'
    panel_template_name = 'debian/bugs.html'
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
        'patch': {
            'display_name': 'patch',
            'description': 'Patch',
        },
        'help': {
            'display_name': 'help',
            'description': 'Help needed',
        },
        'newcomer': {
            'display_name': 'NC',
            'description': 'newcomer',
            'link': 'https://wiki.debian.org/BTS/NewcomerTag',
        }
    }

    def get_bug_tracker_url(self, package_name, package_type, category_name):
        """
        Returns a URL to the BTS for the given package for the given bug
        category name.

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
        - ``fixed-merged`` - bugs tagged as fixed and pending, including the
          merged ones

        :param package_name: The name of the package for which the BTS link
            should be provided.
        :param package_type: The type of the package for which the BTS link
            should be provided. For Debian this is one of: ``source``,
            ``pseudo``, ``binary``.
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
            urlencode(query_parameters)
        )

    def get_bugs_categories_list(self, stats, package):
        # Some bug categories should not be included in the count.
        exclude_from_count = ('help', 'newcomer')

        categories = []
        total, total_merged = 0, 0
        # From all known bug stats, extract only the ones relevant for the panel
        for category in stats:
            category_name = category['category_name']
            if category_name not in self.category_descriptions.keys():
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
            category_stats.update(self.category_descriptions[category_name])
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
            url = self.get_bug_tracker_url(
                package.name, 'source', category['category_name'])
            category['url'] = url

            # URL for the merged category
            if 'merged' in category:
                url_merged = self.get_bug_tracker_url(
                    package.name, 'source',
                    category['category_name'] + '-merged'
                )
                category['merged']['url'] = url_merged

        return categories

    def table_field_context(self, package):
        """
        :returns: The context data for package's bug stats with RC bugs data to
        be highlighted in the template, as well as providing proper links for
        Debian BTS.
        """
        try:
            stats = package.bug_stats.stats
        except ObjectDoesNotExist:
            stats = []

        data = {}
        data['bugs'] = self.get_bugs_categories_list(stats, package)

        total = 0
        for category in data['bugs']:
            if category['category_name'] == 'all':
                total = category['bug_count']
                break
        data['all'] = total
        data['bts_url'] = self.get_bug_tracker_url(
            package.name, 'source', 'all')

        # Highlights RC bugs and set text color based on the bug category
        data['text_color'] = 'text-default'
        for bug in data['bugs']:
            if bug['category_name'] == 'rc' and bug['bug_count'] > 0:
                data['text_color'] = 'text-danger'
                data['rc_bugs'] = bug['bug_count']
            elif bug['category_name'] == 'normal' and bug['bug_count'] > 0:
                if data['text_color'] != 'text-danger':
                    data['text_color'] = 'text-warning'
            elif bug['category_name'] == 'patch' and bug['bug_count'] > 0:
                if (data['text_color'] != 'text-warning' and
                        data['text_color'] != 'text-danger'):
                    data['text_color'] = 'text-info'
        return data

    def panel_context(self, package):
        """
        Returns bug statistics which are to be displayed in the bugs panel
        (:class:`BugsPanel <distro_tracker.core.panels.BugsPanel>`).

        Debian wants to include the merged bug count for each bug category
        (but only if the count is different than non-merged bug count) so this
        function is used in conjunction with a custom bug panel template which
        displays this bug count in parentheses next to the non-merged count.

        Each bug category count (merged and non-merged) is linked to a URL in
        the BTS which displays more information about the bugs found in that
        category.

        A verbose name is included for each of the categories.

        The function includes a URL to a bug history graph which is displayed in
        the rendered template.
        """
        bug_stats = get_or_none(PackageBugStats, package=package)

        if bug_stats:
            stats = bug_stats.stats
        else:
            stats = []

        categories = self.get_bugs_categories_list(stats, package)

        # Debian also includes a custom graph of bug history
        graph_url = (
            'https://qa.debian.org/data/bts/graphs/'
            '{package_hash}/{package_name}.png'
        )

        # Final context variables which are available in the template
        return {
            'categories': categories,
            'graph_url': graph_url.format(
                package_hash=package_hashdir(package.name),
                package_name=package.name),
        }

    def get_binary_bug_stats(self, binary_name):
        """
        Returns the bug statistics for the given binary package.

        Debian's implementation filters out some of the stored bug category
        stats. It also provides a different, more verbose, display name for each
        of them. The included categories and their names are:

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
