# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Implements the core panels shown on package pages."""
from __future__ import unicode_literals
from django.utils import six
from django.utils.safestring import mark_safe
from pts.core.utils.plugins import PluginRegistry
from pts.core.utils import get_vcs_name
from pts import vendor
from pts.core.models import PackageExtractedInfo
from pts.core.models import MailingList


class BasePanel(six.with_metaclass(PluginRegistry)):
    """
    A base class representing panels which are displayed on a package page.

    To include a panel on the package page, users only need to create a
    subclass and implement the necessary properties and methods.
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
        When the panel's template is rendered, it will have access to the values
        in this dictionary.
        """
        return {}

    @property
    def position(self):
        """
        The property should be one of the available :attr:`POSITIONS` signalling
        where the panel should be positioned in the page.
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
    A convenience method which accesses the :class:`BasePanel`'s list of
    children and instantiates them for the given package.

    :returns: A dict mapping the page position to a list of Panels which should
        be rendered in that position.
    :rtype: dict
    """
    from collections import defaultdict

    panels = defaultdict(lambda: [])
    for panel_class in BasePanel.plugins:
        if panel_class is not BasePanel:
            panel = panel_class(package)
            panels[panel.position].append(panel)

    return dict(panels)


class GeneralInformationPanel(BasePanel):
    """
    This panel displays general information regarding a package.

    - name
    - version (in the default repository)
    - maintainer
    - uploaders
    - architectures
    - standards version
    - VCS

    Several vendor-specific functions can be implemented which augment this
    panel:

    - :func:`get_developer_information_url <pts.vendor.skeleton.rules.get_developer_information_url>`
    - :func:`get_maintainer_extra <pts.vendor.skeleton.rules.get_maintainer_extra>`
    - :func:`get_uploader_extra <pts.vendor.skeleton.rules.get_uploader_extra>`
    """
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
    """
    This panel displays the versions of the package in each of the repositories
    it is found in.

    Several vendor-specific functions can be implemented which augment this
    panel:

    - :func:`get_package_information_site_url <pts.vendor.skeleton.rules.get_package_information_site_url>`
    - :func:`get_external_version_information_urls <pts.vendor.skeleton.rules.get_external_version_information_urls>`
    """
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
    """
    This panel displays a list of binary package names which a given source
    package produces.

    If implemented, the
    :func:`get_package_information_site_url <pts.vendor.skeleton.rules.get_package_information_site_url>`
    provides the link used for each binary package name.
    """
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


class PanelItem(object):
    """
    The base class for all items embeddable in panels.

    Lets the users define the panel item's content in two ways:

    - A template and a context accessible to the template as item.context
      variable
    - Define the HTML output directly. This string needs to be marked safe,
      otherwise it will be HTML encoded in the output.
    """
    #: The template to render when this item should be rendered
    template_name = None
    #: Context to be available when the template is rendered
    context = None
    #: HTML output to be placed in the page when the item should be rendered
    html_output = None


class TemplatePanelItem(PanelItem):
    """
    A subclass of :class:`PanelItem` which gives a more convenient interface
    for defining items rendered by a template + context.
    """
    def __init__(self, template_name, context=None):
        self.template_name = template_name
        self.context = context


class HtmlPanelItem(PanelItem):
    """
    A subclass of :class:`PanelItem` which gives a more convenient interface
    for defining items which already provide HTML text.
    Takes care of marking the given text as safe.
    """
    def __init__(self, html):
        self._html = mark_safe(html)

    @property
    def html_output(self):
        return self._html


class PanelItemProvider(six.with_metaclass(PluginRegistry)):
    """
    A base class for classes which produce :class:`PanelItem` instances.

    Each panel which wishes to allow clients to register item providers needs
    a separate subclass of this class.
    """
    @classmethod
    def all_panel_item_providers(cls):
        """
        Returns all subclasses of the given :class:`PanelItemProvider`
        subclass.

        Makes it possible for each :class:`ListPanel` to have its own separate
        set of providers derived from its base ItemProvider.
        """
        return [
            item_provider
            for item_provider in cls.plugins
            if issubclass(item_provider, cls)
        ]

    def __init__(self, package):
        self.package = package

    def get_panel_items(self):
        """
        The main method which needs to return a list of :class:`PanelItem`
        instances which the provider wants rendered in the panel.
        """
        return []


class ListPanelMeta(PluginRegistry):
    """
    A meta class for the :class:`ListPanel`. Makes sure that each subclass of
    :class:`ListPanel` has a new :class:`PanelItemProvider` subclass.
    """
    def __init__(cls, name, bases, attrs):
        super(ListPanelMeta, cls).__init__(name, bases, attrs)
        if name != 'NewBase':
            cls.ItemProvider = type(
                str('{name}ItemProvider'.format(name=name)),
                (PanelItemProvider,),
                {}
            )


class ListPanel(BasePanel, six.with_metaclass(ListPanelMeta)):
    """
    The base class for panels which would like to present an extensible list of
    items.

    The subclasses only need to add the :attr:`position <BasePanel.position>`
    and :attr:`title <BasePanel.title>` attributes, the rendering is handled
    automatically, based on the registered list of item providers for the
    panel.

    Clients can add items to the panel by implementing a subclass of the
    :class:`ListPanel.ItemProvider` class.

    It is possible to change the :attr:`template_name <BasePanel.template_name>`
    too, but making sure all the same context variable names are used in the
    custom template.
    """
    template_name = 'core/panels/list-panel.html'

    def get_items(self):
        """
        Returns a list of :class:`PanelItem` instances for the current panel
        instance. This means the items are prepared for the package given to
        the panel instance.
        """
        panel_providers = self.ItemProvider.all_panel_item_providers()
        items = []
        for panel_provider_class in panel_providers:
            panel_provider = panel_provider_class(self.package)
            items.extend(panel_provider.get_panel_items())
        return items

    @property
    def context(self):
        return {
            'items': self.get_items()
        }
# This should be a sort of "abstract" panel which should never be rendered on
# its own, so it is removed from the list of registered panels.
ListPanel.unregister_plugin()


class LinksPanel(ListPanel):
    """
    This panel displays a list of important links for a given source package.

    Clients can add items to the panel by implementing a subclass of the
    :class:`LinksPanel.ItemProvider` class.
    """
    position = 'right'
    title = 'Links'

    class SimpleLinkItem(HtmlPanelItem):
        """
        A convenience :class:`PanelItem` which renders a simple link in the
        panel, by having the text, url and, optionally, the tooltip text
        given in the constructor.
        """
        TEMPLATE = '<a href="{url}">{text}</a>'
        TEMPLATE_TOOLTIP = (
            '<a href="{url}"'
            ' class="has-tooltip"'
            ' data-toggle="tooltip"'
            ' title="{tooltip}">'
            '{text}'
            '</a>'
        )

        def __init__(self, text, url, tooltip=None):
            if tooltip:
                template = self.TEMPLATE_TOOLTIP
            else:
                template = self.TEMPLATE
            html = template.format(text=text, url=url, tooltip=tooltip)
            super(LinksPanel.SimpleLinkItem, self).__init__(html)


class GeneralInfoLinkPanelItems(LinksPanel.ItemProvider):
    """
    Provides the :class:`LinksPanel` with links derived from general package
    information.

    For now, this is only the homepage of the package, if available.
    """
    def get_panel_items(self):
        items = []
        if self.package.main_version.homepage:
            items.append(
                LinksPanel.SimpleLinkItem(
                    'Homepage',
                    self.package.main_version.homepage
                ),
            )
        return items
