# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements the core panels shown on package pages."""
from __future__ import unicode_literals
from django.conf import settings
from django.utils.functional import cached_property
from django.core.exceptions import ObjectDoesNotExist
from django.utils import six
from django.utils.safestring import mark_safe
from distro_tracker.core.utils.plugins import PluginRegistry
from distro_tracker.core.utils import get_vcs_name
from distro_tracker.core.utils import get_or_none
from distro_tracker import vendor
from distro_tracker.core.models import SourcePackageName
from distro_tracker.core.models import PseudoPackageName
from distro_tracker.core.models import ActionItem
from distro_tracker.core.models import PackageExtractedInfo
from distro_tracker.core.models import MailingList
from distro_tracker.core.models import News
from distro_tracker.core.models import BinaryPackageBugStats
from debian.debian_support import AptPkgVersion
from collections import defaultdict

import importlib
import logging
logger = logging.getLogger(__name__)


class BasePanel(six.with_metaclass(PluginRegistry)):

    """
    A base class representing panels which are displayed on a package page.

    To include a panel on the package page, users only need to create a
    subclass and implement the necessary properties and methods.

    .. note::
       To make sure the subclass is loaded, make sure to put it in a
       ``tracker_panels`` module at the top level of a Django app.
    """
    #: A list of available positions
    # NOTE: This is a good candidate for Python3.4's Enum.
    POSITIONS = (
        'left',
        'center',
        'right',
    )

    def __init__(self, package, request):
        self.package = package
        self.request = request

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

    @property
    def panel_importance(self):
        """
        Returns and integer giving the importance of a package.
        The panels in a single column are always positioned in decreasing
        importance order.
        """
        return 0

    @property
    def has_content(self):
        """
        Returns a bool indicating whether the panel actually has any content to
        display for the package.
        """
        return True


def get_panels_for_package(package, request):
    """
    A convenience method which accesses the :class:`BasePanel`'s list of
    children and instantiates them for the given package.

    :returns: A dict mapping the page position to a list of Panels which should
        be rendered in that position.
    :rtype: dict
    """
    # First import panels from installed apps.
    for app in settings.INSTALLED_APPS:
        try:
            module_name = app + '.' + 'tracker_panels'
            importlib.import_module(module_name)
        except ImportError:
            # The app does not implement package panels.
            pass

    panels = defaultdict(lambda: [])
    for panel_class in BasePanel.plugins:
        if panel_class is not BasePanel:
            panel = panel_class(package, request)
            if panel.has_content:
                panels[panel.position].append(panel)

    # Each columns' panels are sorted in the order of decreasing importance
    return dict({
        key: list(sorted(value, key=lambda x: -x.panel_importance))
        for key, value in panels.items()
    })


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

    - :func:`get_developer_information_url
      <distro_tracker.vendor.skeleton.rules.get_developer_information_url>`
    - :func:`get_maintainer_extra
      <distro_tracker.vendor.skeleton.rules.get_maintainer_extra>`
    - :func:`get_uploader_extra
      <distro_tracker.vendor.skeleton.rules.get_uploader_extra>`
    """
    position = 'left'
    title = 'general'
    template_name = 'core/panels/general.html'

    def _get_archive_url_info(self, email):
        ml = MailingList.objects.get_by_email(email)
        if ml:
            return ml.archive_url_for_email(email)

    def _get_developer_information_url(self, email):
        info_url, implemented = vendor.call(
            'get_developer_information_url', **{'developer_email': email, })
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

    @cached_property
    def context(self):
        try:
            info = PackageExtractedInfo.objects.get(
                package=self.package, key='general')
        except PackageExtractedInfo.DoesNotExist:
            # There is no general info for the package
            return

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

    @property
    def has_content(self):
        return bool(self.context)


class VersionsInformationPanel(BasePanel):

    """
    This panel displays the versions of the package in each of the repositories
    it is found in.

    Several vendor-specific functions can be implemented which augment this
    panel:

    - :func:`get_package_information_site_url
      <distro_tracker.vendor.skeleton.rules.get_package_information_site_url>`
    - :func:`get_external_version_information_urls
      <distro_tracker.vendor.skeleton.rules.get_external_version_information_urls>`
    """
    position = 'left'
    title = 'versions'
    template_name = 'core/panels/versions.html'

    @cached_property
    def context(self):
        try:
            info = PackageExtractedInfo.objects.get(
                package=self.package, key='versions')
        except PackageExtractedInfo.DoesNotExist:
            info = None

        context = {}

        if info:
            version_info = info.value
            package_name = info.package.name
            for item in version_info.get('version_list', ()):
                url, implemented = vendor.call(
                    'get_package_information_site_url',
                    **
                    {'package_name': package_name,
                     'repository': item.get(
                         'repository'),
                     'source_package': True,
                     'version':
                     item.get('version'), })
                if implemented and url:
                    item['url'] = url

            context['version_info'] = version_info

        # Add in any external version resource links
        external_resources, implemented = (
            vendor.call('get_external_version_information_urls',
                        self.package.name)
        )
        if implemented and external_resources:
            context['external_resources'] = external_resources

        # Add any vendor-provided versions
        vendor_versions, implemented = vendor.call(
            'get_extra_versions', self.package)
        if implemented and vendor_versions:
            context['vendor_versions'] = vendor_versions

        return context

    @property
    def has_content(self):
        return (bool(self.context.get('version_info', None)) or
                bool(self.context.get('vendor_versions', None)))


class VersionedLinks(BasePanel):

    """
    A panel displaying links specific for source package versions.

    The panel exposes an endpoint which allows for extending the displayed
    content. This is achieved by implementing a
    :class:`VersionedLinks.LinkProvider` subclass.
    """
    position = 'left'
    title = 'versioned links'
    template_name = 'core/panels/versioned-links.html'

    class LinkProvider(six.with_metaclass(PluginRegistry)):

        """
        A base class for classes which should provide a list of version
        specific links.

        Subclasses need to define the :attr:`icons` property and implement the
        :meth:`get_link_for_icon` method.
        """
        #: A list of strings representing icons for links that the class
        #: provides.
        #: Each string is an HTML representation of the icon.
        #: If the string should be considered safe and rendered in the
        #: resulting template without HTML encoding it, it should be marked
        #: with :func:`django.utils.safestring.mark_safe`.
        #: It requires each icon to be a string to discourage using complex
        #: markup for icons. Using a template is possible by making
        #: :attr:`icons` a property and rendering the template as string before
        #: returning it in the list.
        icons = []

        def get_link_for_icon(self, package, icon_index):
            """
            Return a URL for the given package version which should be used for
            the icon at the given index in the :attr:`icons` property.
            If no link can be given for the icon, ``None`` should be returned
            instead.

            :type package: :class:`SourcePackage
                <distro_tracker.core.models.SourcePackage>`
            :type icon_index: int

            :rtype: :class:`string` or ``None``
            """
            return None

        def get_links(self, package):
            """
            For each of the icons returned by the :attr:`icons` property,
            returns a URL specific for the given package.

            The order of the URLs must match the order of the icons (matching
            links and icons need to have the same index). Consequently, the
            length of the returned list is the same as the length of the
            :attr:`icons` property.

            If no link can be given for some icon, ``None`` should be put
            instead.

            This method has a default implementation which calls the
            :meth:`get_link_for_icon` for each icon defined in the :attr:`icons`
            property. This should be enough for all intents and purposes and
            the method should not need to be overridden by subclasses.

            :param package: The source package instance for which links should
                be provided
            :type package: :class:`SourcePackage
                <distro_tracker.core.models.SourcePackage>`

            :returns: List of URLs for the package
            :rtype: list
            """
            return [
                self.get_link_for_icon(package, index)
                for index, icon in enumerate(self.icons)
            ]

        @classmethod
        def get_providers(cls):
            """
            Helper classmethod returning a list of instances of all registered
            :class:`VersionedLinks.LinkProvider` subclasses.
            """
            return [
                klass()
                for klass in cls.plugins
                if klass is not cls
            ]

    def __init__(self, *args, **kwargs):
        super(VersionedLinks, self).__init__(*args, **kwargs)
        #: All icons that the panel displays for each version.
        #: Icons must be the same for each version.
        self.ALL_ICONS = [
            icon
            for link_provider in VersionedLinks.LinkProvider.get_providers()
            for icon in link_provider.icons
        ]

    @cached_property
    def context(self):
        # Only process source files
        if not isinstance(self.package, SourcePackageName):
            return
        # Make sure we display the versions in a version-number increasing
        # order
        versions = sorted(
            self.package.source_package_versions.all(),
            key=lambda x: AptPkgVersion(x.version)
        )

        versioned_links = []
        for package in versions:
            if all([src_repo_entry.repository.get_flags()['hidden']
                    for src_repo_entry in package.repository_entries.all()]):
                # All associated repositories are hidden
                continue
            links = [
                link
                for link_provider in VersionedLinks.LinkProvider.get_providers()
                for link in link_provider.get_links(package)
            ]
            versioned_links.append({
                'number': package.version,
                'links': [
                    {
                        'icon_html': icon,
                        'url': link,
                    }
                    for icon, link in zip(self.ALL_ICONS, links)
                ]
            })

        return versioned_links

    @property
    def has_content(self):
        # Do not display the panel if there are no icons or the package has no
        # versions.
        return bool(self.ALL_ICONS) and bool(self.context)


class DscLinkProvider(VersionedLinks.LinkProvider):
    icons = [
        mark_safe(
            '<i title=".dsc, use dget on this link to retrieve source package"'
            '   class="icon-download-alt"></i>'),
    ]

    def get_link_for_icon(self, package, index):
        if index >= len(self.icons):
            return None
        if package.main_entry:
            return package.main_entry.dsc_file_url


class BinariesInformationPanel(BasePanel):

    """
    This panel displays a list of binary package names which a given source
    package produces.

    If there are existing bug statistics for some of the binary packages, a
    list of bug counts is also displayed.

    If implemented, the following functions can augment the information of
    this panel:

    - :func:`get_package_information_site_url
      <distro_tracker.vendor.skeleton.rules.get_package_information_site_url>`
      provides the link used for each binary package name.
    - :func:`get_binary_package_bug_stats
      <distro_tracker.vendor.skeleton.rules.get_binary_package_bug_stats>`
      provides bug statistics for a given binary package in terms of a list of
      bug counts for different categories. If this is implemented, the panel
      will display only the categories returned by this function, not all stats
      found in the database.
    - :func:`get_bug_tracker_url
      <distro_tracker.vendor.skeleton.rules.get_bug_tracker_url>`
      provides a link to an external bug tracker based on the name of a package
      and the bug category.
    """
    position = 'left'
    title = 'binaries'
    template_name = 'core/panels/binaries.html'

    def _get_binary_bug_stats(self, binary_name):
        bug_stats, implemented = vendor.call(
            'get_binary_package_bug_stats', binary_name)
        if not implemented:
            # The vendor does not provide a custom list of bugs, so the default
            # is to display all bug info known for the package.
            stats = get_or_none(
                BinaryPackageBugStats, package__name=binary_name)
            if stats is not None:
                bug_stats = stats.stats

        if bug_stats is None:
            return
        # Try to get the URL to the bug tracker for the given categories
        for category in bug_stats:
            url, implemented = vendor.call(
                'get_bug_tracker_url',
                binary_name,
                'binary',
                category['category_name'])
            if not implemented:
                continue
            category['url'] = url
        # Include the total bug count and corresponding tracker URL
        all_bugs_url, implemented = vendor.call(
            'get_bug_tracker_url', binary_name, 'binary', 'all')
        return {
            'total_count': sum(
                category['bug_count'] for category in bug_stats),
            'all_bugs_url': all_bugs_url,
            'categories': bug_stats,
            }

    @cached_property
    def context(self):
        try:
            info = PackageExtractedInfo.objects.get(
                package=self.package, key='binaries')
        except PackageExtractedInfo.DoesNotExist:
            return

        binaries = info.value
        for binary in binaries:
            # For each binary try to include known bug stats
            bug_stats = self._get_binary_bug_stats(binary['name'])
            if bug_stats is not None:
                binary['bug_stats'] = bug_stats

            # For each binary try to include a link to an external package-info
            # site.
            if 'repository' in binary:
                url, implemented = vendor.call(
                    'get_package_information_site_url', **{
                        'package_name': binary['name'],
                        'repository': binary['repository'],
                        'source_package': False,
                    }
                )
                if implemented and url:
                    binary['url'] = url

        return binaries

    @property
    def has_content(self):
        return bool(self.context)


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


class ListPanel(six.with_metaclass(ListPanelMeta, BasePanel)):

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
            try:
                new_panel_items = panel_provider.get_panel_items()
            except:
                logger.exception(
                    'Panel provider {provider}: error generating items.'.format(
                        provider=panel_provider.__class__))
                continue
            if new_panel_items is not None:
                items.extend(new_panel_items)
        return items

    @cached_property
    def context(self):
        return {
            'items': self.get_items()
        }

    @property
    def has_content(self):
        return bool(self.context['items'])

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
    title = 'links'

    class SimpleLinkItem(HtmlPanelItem):

        """
        A convenience :class:`PanelItem` which renders a simple link in the
        panel, by having the text, url and, optionally, the tooltip text
        given in the constructor.
        """
        TEMPLATE = '<a href="{url}">{text}</a>'
        TEMPLATE_TOOLTIP = '<a href="{url}" title="{title}">{text}</a>'

        def __init__(self, text, url, title=None):
            if title:
                template = self.TEMPLATE_TOOLTIP
            else:
                template = self.TEMPLATE
            html = template.format(text=text, url=url, title=title)
            super(LinksPanel.SimpleLinkItem, self).__init__(html)


class GeneralInfoLinkPanelItems(LinksPanel.ItemProvider):

    """
    Provides the :class:`LinksPanel` with links derived from general package
    information.

    For now, this is only the homepage of the package, if available.
    """

    def get_panel_items(self):
        items = []
        if hasattr(self.package, 'main_version') and self.package.main_version \
                and self.package.main_version.homepage:
            items.append(
                LinksPanel.SimpleLinkItem(
                    'homepage',
                    self.package.main_version.homepage,
                    'upstream web homepage'
                ),
            )
        return items


class NewsPanel(BasePanel):
    _DEFAULT_NEWS_LIMIT = 30
    panel_importance = 1
    NEWS_LIMIT = getattr(
        settings,
        'DISTRO_TRACKER_NEWS_PANEL_LIMIT',
        _DEFAULT_NEWS_LIMIT)

    template_name = 'core/panels/news.html'
    title = 'news'

    @cached_property
    def context(self):
        news = News.objects.prefetch_related('signed_by')
        news = news.filter(package=self.package).order_by('-datetime_created')
        news = list(news[:self.NEWS_LIMIT])
        more_pages = len(news) == self.NEWS_LIMIT
        return {
            'news': news,
            'has_more': more_pages
        }

    @property
    def has_content(self):
        return bool(self.context['news'])


class BugsPanel(BasePanel):

    """
    The panel displays bug statistics for the package.

    This panel is highly customizable to make sure that Distro Tracker can be
    integrated with any bug tracker.

    The default for the package is to display the bug count for all bug
    categories found in the
    :class:`PackageBugStats <distro_tracker.core.models.PackageBugStats>`
    instance which corresponds to the package. The sum of all bugs from
    all categories is also displayed as the first row of the panel.

    A vendor can choose to implement the
    :func:`get_bug_panel_stats
    <distro_tracker.vendor.skeleton.rules.get_bug_panel_stats>`
    function in order to provide a custom list of bug categories to be
    displayed in the panel. This is useful if, for example, the vendor does
    not want to display the count of all bug categories.
    Refer to the function's documentation for the format of the return value.

    Finally, for vendors which require an even higher degree of customization,
    it is possible to provide a
    :data:`DISTRO_TRACKER_BUGS_PANEL_TEMPLATE
    <distro_tracker.project.local_settings.DISTRO_TRACKER_BUGS_PANEL_TEMPLATE>`
    settings value which gives the path to a template which should be used to
    render the panel. It is recommended that this template extends
    ``core/panels/bugs.html``, but not mandatory. If a custom
    :func:`get_bug_panel_stats
    <distro_tracker.vendor.skeleton.rules.get_bug_panel_stats>`
    function is also defined then its return value is simply passed to the
    and does not require any special format; the vendor's template can access
    this value in the ``panel.context`` context variable and can use it any way
    it wants.

    This customization should be used only by vendors whose bug statistics have
    a significantly different format than the expected ``category: count``
    format.
    """
    position = 'right'
    title = 'bugs'
    panel_importance = 1
    _default_template_name = 'core/panels/bugs.html'

    @property
    def template_name(self):
        return getattr(
            settings,
            'DISTRO_TRACKER_BUGS_PANEL_TEMPLATE',
            self._default_template_name)

    @cached_property
    def context(self):
        result, implemented = vendor.call(
            'get_bug_panel_stats', self.package.name)
        # implemented = False
        if not implemented:
            # If the vendor does not provide custom categories to be displayed
            # in the panel, the default is to make each stored category a
            # separate entry.
            try:
                stats = self.package.bug_stats.stats
            except ObjectDoesNotExist:
                return
            # Also adds a total of all those bugs
            total = sum(category['bug_count'] for category in stats)
            stats.insert(0, {
                'category_name': 'all',
                'bug_count': total,
            })
            result = stats

        # Either the vendor decided not to provide any info for this package
        # or there is no known info.
        if not result:
            return []

        return result

    @property
    def has_content(self):
        return bool(self.context)


class ActionNeededPanel(BasePanel):

    """
    The panel displays a list of
    :class:`ActionItem <distro_tracker.core.models.ActionItem>`
    model instances which are associated with the package.

    This means that all other modules can create action items which are
    displayed for a package in this panel by creating instances of that class.
    """
    title = 'action needed'
    template_name = 'core/panels/action-needed.html'
    panel_importance = 5
    position = 'center'

    @cached_property
    def context(self):
        action_items = ActionItem.objects.filter(package=self.package)
        action_items = action_items.order_by(
            '-severity', '-last_updated_timestamp')

        return {
            'items': action_items,
        }

    @property
    def has_content(self):
        return bool(self.context['items'])


class DeadPackageWarningPanel(BasePanel):
    """
    The panel displays a warning when the package has been dropped
    from development repositories, and another one when the package no longer
    exists in any repository.
    """
    title = 'package is gone'
    template_name = 'core/panels/package-is-gone.html'
    panel_importance = 9
    position = 'center'

    @property
    def has_content(self):
        if isinstance(self.package, SourcePackageName):
            for repo in self.package.repositories:
                if repo.is_development_repository():
                    return False
            return True
        elif isinstance(self.package, PseudoPackageName):
            return False
        else:
            return True

    @cached_property
    def context(self):
        if isinstance(self.package, SourcePackageName):
            disappeared = len(self.package.repositories) == 0
        else:
            disappeared = True
        return {
            'disappeared': disappeared,
            'removals_url': getattr(settings, 'DISTRO_TRACKER_REMOVALS_URL',
                                    ''),
        }
