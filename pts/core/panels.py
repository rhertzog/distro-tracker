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
from django.utils import six
from pts.core.utils.plugins import PluginRegistry
from pts.core.utils import get_vcs_name
from pts import vendor
from pts.core.models import PackageExtractedInfo
from pts.core.models import MailingList


class BasePanel(six.with_metaclass(PluginRegistry)):
    """
    A base class representing panels which are displayed on a package page.

    To include a panel on the package page, the users must subclass this class
    and include the path to the new class in the project settings in order to
    have it displayed on the page.
    """
    #: A list of available positions
    # NOTE: This is a good candidate for Python3.4's Enum.
    POSITIONS = (
        'left',
        'center',
        'right',
    )

    def __init__(self, package):
        self.package = package

    @property
    def context(self):
        """
        Should return a dictionary representing context variables necessary for
        the panel.
        When the panels template is rendered, it will have access to the values
        in this dictionary.
        """
        return {}

    @property
    def position(self):
        """
        The property should be one of the available POSITIONS signalling where
        the panel should be positioned in the page.
        """
        return 'center'

    @property
    def title(self):
        """
        The title of the panel.
        """
        return ''

    @property
    def template_name(self):
        """
        If the panel has a corresponding template which is used to render its
        HTML output, this property should contain the name of this template.
        """
        return None

    @property
    def html_output(self):
        """
        If the panel does not want to use a template, it can return rendered
        HTML in this property. The HTML needs to be marked safe or else it will
        be escaped in the final output.
        """
        return None


def get_panels_for_package(package):
    """
    A convenience method which accesses the BasePanel's list of children and
    instantiates them for the given package.

    Returns a dict mapping the page position to a list of Panels which should
    be rendered in that position.
    """
    from collections import defaultdict

    panels = defaultdict(lambda: [])
    for panel_class in BasePanel.plugins:
        if panel_class is not BasePanel:
            panel = panel_class(package)
            panels[panel.position].append(panel)

    return dict(panels)


class GeneralInformationPanel(BasePanel):
    position = 'center'
    title = 'general'
    template_name = 'core/panels/general.html'

    def _get_archive_url_info(self, email):
        ml = MailingList.objects.get_by_email(email)
        if ml:
            return ml.archive_url_for_email(email)

    def _get_developer_information_url(self, email):
        info_url, implemented = vendor.call('get_developer_information_url', **{
            'developer_email': email,
        })
        if implemented and info_url:
            return info_url

    def _add_archive_urls(self, general):
        maintainer_email = general['maintainer']['email']
        general['maintainer']['archive_url'] = (
            self._get_archive_url_info(maintainer_email)
        )

        uploaders = general.get('uploaders', None)
        if not uploaders:
            return

        for uploader in uploaders:
            uploader['archive_url'] = (
                self._get_archive_url_info(uploader['email'])
            )

    def _add_developer_extras(self, general):
        maintainer_email = general['maintainer']['email']
        url = self._get_developer_information_url(maintainer_email)
        if url:
            general['maintainer']['developer_info_url'] = url
            extra, implemented = vendor.call(
                'get_maintainer_extra', maintainer_email, general['name'])
            general['maintainer']['extra'] = extra

        uploaders = general.get('uploaders', None)
        if not uploaders:
            return

        for uploader in uploaders:
            # Vendor specific extras.
            extra, implemented = vendor.call(
                'get_uploader_extra', uploader['email'], general['name'])
            if implemented and extra:
                uploader['extra'] = extra
            url = self._get_developer_information_url(uploader['email'])
            if url:
                uploader['developer_info_url'] = url

    @property
    def context(self):
        info = PackageExtractedInfo.objects.get(
            package=self.package, key='general')
        general = info.value
        # Add source package URL
        url, implemented = vendor.call('get_package_information_site_url', **{
            'package_name': general['name'],
            'source_package': True,
        })
        if implemented and url:
            general['url'] = url
        # Map the VCS type to its name.
        if 'vcs' in general and 'type' in general['vcs']:
            shorthand = general['vcs']['type']
            general['vcs']['full_name'] = get_vcs_name(shorthand)
        # Add mailing list archive URLs
        self._add_archive_urls(general)
        # Add developer information links and any other vendor-specific extras
        self._add_developer_extras(general)

        return general


class VersionsInformationPanel(BasePanel):
    position = 'left'
    title = 'versions'
    template_name = 'core/panels/versions.html'

    @property
    def context(self):
        info = PackageExtractedInfo.objects.get(
            package=self.package, key='versions')
        version_info = info.value
        package_name = info.package.name
        for item in version_info['version_list']:
            url, implemented = vendor.call('get_package_information_site_url', **{
                'package_name': package_name,
                'repository_name': item['repository_name'],
                'source_package': True,
            })
            if implemented and url:
                item['url'] = url
        # Add in any external version resource links
        external_resources, implemented = (
            vendor.call('get_external_version_information_urls',
                        self.package.name)
        )
        if implemented and external_resources:
            version_info['external_resources'] = external_resources

        return version_info


class BinariesInformationPanel(BasePanel):
    position = 'right'
    title = 'binaries'
    template_name = 'core/panels/binaries.html'

    @property
    def context(self):
        info = PackageExtractedInfo.objects.get(
            package=self.package, key='binaries')
        binaries = info.value
        for binary in binaries:
            if 'repository_name' not in binary:
                continue
            url, implemented = vendor.call('get_package_information_site_url', **{
                'package_name': binary['name'],
                'repository_name': binary['repository_name'],
                'source_package': False,
            })
            if implemented and url:
                binary['url'] = url

        return binaries
