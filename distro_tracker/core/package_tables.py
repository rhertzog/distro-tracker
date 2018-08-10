# Copyright 2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Implements the core package tables shown on team pages."""
import logging
import importlib

from django.db.models import Prefetch
from django.conf import settings
from django.template import Template, Context
from django.template.loader import get_template

from distro_tracker import vendor
from distro_tracker.core.models import (
    BugDisplayManagerMixin,
    PackageData,
    PackageName,
)
from distro_tracker.core.utils import get_vcs_name, add_developer_extras
from distro_tracker.core.utils.plugins import PluginRegistry

logger = logging.getLogger(__name__)


class BaseTableField(metaclass=PluginRegistry):
    """
    A base class representing fields to be displayed on package tables.

    To create a new field for packages table, users only need to create a
    subclass and implement the necessary properties and methods.

    .. note::
       To make sure the subclass is loaded, make sure to put it in a
       ``tracker_package_tables`` module at the top level of a Django app.
    """

    def context(self, package):
        """
        Should return a dictionary representing context variables necessary for
        the package table field.
        When the field's template is rendered, it will have access to the values
        in this dictionary.
        """
        return {}

    @property
    def column_name():
        """
        The column name for the field
        """
        return ''

    @property
    def template_name(self):
        """
        If the field has a corresponding template which is used to render its
        HTML output, this property should contain the name of this template.
        """
        return None

    def render(self, package, context=None, request=None):
        """
        Render the field's HTML output for the given package.
        """
        if not hasattr(self, '_template'):
            self._template = get_template(self.template_name)
        if context is None:
            context = {self.slug: self.context(package)}
        return self._template.render(context, request)

    @property
    def prefetch_related_lookups():
        """
        Returns a list of lookups to be prefetched along with
        Table's QuerySet of packages. Elements may be either a String
        or Prefetch object
        """
        return []


class GeneralInformationTableField(BaseTableField):
    """
    This table field displays general information to identify a package.

    It displays the package's name in the cell and the following information
    on details popup
    - name
    - short description
    - version (in the default repository)
    - maintainer
    - uploaders
    - architectures
    - standards version
    - binaries
    """
    column_name = 'Package'
    slug = 'general'
    template_name = 'core/package-table-fields/general.html'
    prefetch_related_lookups = [
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='general'),
            to_attr='general_data'
        ),
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='binaries'),
            to_attr='binaries_data'
        ),
    ]

    def context(self, package):
        try:
            info = package.general_data[0]
        except IndexError:
            # There is no general info for the package
            return {
                'url': package.get_absolute_url,
                'name': package.name
            }

        general = info.value
        general['url'] = package.get_absolute_url

        # Add developer information links and any other vendor-specific extras
        general = add_developer_extras(general, url_only=True)

        try:
            info = package.binaries_data[0]
            general['binaries'] = info.value
        except IndexError:
            general['binaries'] = []

        return general


class VcsTableField(BaseTableField):
    """
    This table field displays information regarding the package VCS repository.
    It is customizable to enable vendors to add specific data
    regarding the package's vcs repository.

    The default behavior is to display the package's repository type with a
    (browser) link to it.

    A vendor can provide a
    :data:`DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE
    <distro_tracker.project.local_settings.DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE>`
    settings value which gives the path to a template which should
    be used to render the field. It is recommended that this template extends
    ``core/package-table-fields/vcs.html``, but not mandatory.
    If a custom
    :func:`get_vcs_data
    <distro_tracker.vendor.skeleton.rules.get_vcs_data>`
    function in order to provide custom data to be displayed in the field.
    Refer to the function's documentation for the format of the return value.
    If this function is defined then its return value is simply passed to the
    template and does not require any special format; the vendor's template can
    access this value in the ``field.context`` context variable and can use it
    any way it wants.

    To avoid performance issues, if :func:`get_vcs_data
    <distro_tracker.vendor.skeleton.rules.get_vcs_data>` function
    depends on data from other database tables than packages, the vendor app
    should also implement the :func:`additional_prefetch_related_lookups
    <distro_tracker.vendor.skeleton.rules.additional_prefetch_related_lookups>`
    """
    column_name = 'VCS'
    slug = 'vcs'
    _default_template_name = 'core/package-table-fields/vcs.html'
    prefetch_related_lookups = [
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='general'),
            to_attr='general_data'
        )
    ]

    @property
    def template_name(self):
        return getattr(
            settings,
            'DISTRO_TRACKER_VCS_TABLE_FIELD_TEMPLATE',
            self._default_template_name)

    def context(self, package):
        try:
            info = package.general_data[0]
        except IndexError:
            # There is no general info for the package
            return

        general = {}
        if 'vcs' in info.value:
            general['vcs'] = info.value['vcs']
            # Map the VCS type to its name.
            shorthand = general['vcs'].get('type', 'Unknown')
            general['vcs']['full_name'] = get_vcs_name(shorthand)

        result, implemented = vendor.call(
            'get_vcs_data', package)

        if implemented:
            general.update(result)

        return general


class ArchiveTableField(BaseTableField):
    """
    This table field displays information regarding the package version on
    archive.

    It displays the package's version on archive
    """
    column_name = 'Archive'
    slug = 'archive'
    template_name = 'core/package-table-fields/archive.html'
    prefetch_related_lookups = [
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='general'),
            to_attr='general_data'
        ),
        Prefetch(
            'data',
            queryset=PackageData.objects.filter(key='versions'),
            to_attr='versions'
        )
    ]

    def context(self, package):
        try:
            info = package.general_data[0]
        except IndexError:
            # There is no general info for the package
            return

        general = {}
        if 'version' in info.value:
            general['version'] = info.value['version']

        try:
            info = package.versions[0].value
            general['default_pool_url'] = info['default_pool_url']
        except IndexError:
            # There is no versions info for the package
            general['default_pool_url'] = '#'

        return general


class BugStatsTableField(BaseTableField, BugDisplayManagerMixin):
    """
    This table field displays bug statistics for the package.
    It is customizable to enable vendors to add specific data.

    The default behavior defined by :class:`BugDisplayManager
    <distro_tracker.core.models.BugDisplayManager>`
    is to display the number of bugs for a package. It also
    shows the bugs categories on popover content.

    A vendor may provide a custom way of displaying bugs data in
    packages tables by implementing :func:`get_bug_display_manager_class
    <distro_tracker.vendor.skeleton.rules.get_bug_display_manager_class>`
    function in order to provide a custom class to handle the bugs data
    presentation. Refer to the function's documentation for the format of the
    return value.

    To avoid performance issues, if additional database lookups are
    required to display custom bugs data, the vendor app
    should also implement the :func:`additional_prefetch_related_lookups
    <distro_tracker.vendor.skeleton.rules.additional_prefetch_related_lookups>`
    """
    column_name = 'Bugs'
    slug = 'bugs'
    prefetch_related_lookups = ['bug_stats']

    @property
    def template_name(self):
        return self.bug_manager.table_field_template_name

    def context(self, package):
        return self.bug_manager.table_field_context(package)


class BasePackageTable(metaclass=PluginRegistry):
    """
    A base class representing package tables which are displayed on a team page.

    To include a package table on the team page, users only need to create a
    subclass and implement the necessary properties and methods.

    .. note::
       To make sure the subclass is loaded, make sure to put it in a
       ``tracker_package_tables`` module at the top level of a Django app.

    The following vendor-specific functions can be implemented to augment
    this table:

    - :func:`get_table_fields
      <distro_tracker.vendor.skeleton.rules.get_table_fields>`
    """

    def __init__(self, scope, title=None, limit=None, tag=None):
        """
        :param scope: a convenient object that can be used to define the list
        of packages to be displayed on the table. For instance, if you want
        to consider all the packages of a specific team, you must pass that
        team through the `scope` attribute to allow the function
        :param title: a string to be displayed instead of the default title
        :param limit: an integer that can be used to define the limit number of
        packages to be displayed
        :param tag: if defined, it is used to display only packages tagged with
        the informed tag
        :func:`packages` to access it to define the packages to be presented.
        """
        self.scope = scope
        self._title = title
        self.limit = limit
        self.tag = tag

    def context(self):
        """
        Should return a dictionary representing context variables necessary for
        the package table.
        When the table's template is rendered, it will have access to the values
        in this dictionary.
        """
        return {}

    @property
    def default_title(self):
        """
        The default title of the table.
        """
        return ''

    @property
    def title(self):
        """
        The title of the table.
        """
        if self._title:
            return self._title
        else:
            return self.default_title

    @property
    def slug(self):
        """
        The slug of the table which is used to define its url.
        """
        return ''

    @property
    def relative_url(self, **kwargs):
        """
        The relative url for the table.
        """
        return '+table/' + self.slug

    @property
    def packages_with_prefetch_related(self):
        """
        Returns the list of packages with prefetched relationships defined by
        table fields
        """
        attributes_name = set()
        package_query_set = self.packages
        for field in self.table_fields:
            for l in field.prefetch_related_lookups:
                if isinstance(l, Prefetch):
                    if l.to_attr in attributes_name:
                        continue
                    else:
                        attributes_name.add(l.to_attr)
                package_query_set = package_query_set.prefetch_related(l)

        additional_data, implemented = vendor.call(
            'additional_prefetch_related_lookups'
        )
        if implemented and additional_data:
            for l in additional_data:
                package_query_set = package_query_set.prefetch_related(l)
        return package_query_set

    @property
    def packages(self):
        """
        Returns the list of packages shown in the table. One may define this
        based on the scope
        """
        return PackageName.objects.all().order_by('name')

    @property
    def column_names(self):
        """
        Returns a list of column names that will compose the table
        in the proper order
        """
        names = []
        for field in self.table_fields:
            names.append(field.column_name)
        return names

    @property
    def default_fields(self):
        """
        Returns a list of default :class:`BaseTableField` that will compose the
        table
        """
        return [
            GeneralInformationTableField,
            VcsTableField,
            ArchiveTableField,
            BugStatsTableField,
        ]

    @property
    def table_fields(self):
        """
        Returns the tuple of :class:`BaseTableField` that will compose the
        table
        """
        fields, implemented = vendor.call('get_table_fields', **{
            'table': self,
        })
        if implemented and fields:
            return tuple(fields)
        else:
            return tuple(self.default_fields)

    @property
    def rows(self):
        """
        Returns the content of the table's rows, where each row has the list
        of :class:`BaseTableField` for each package
        """
        rows = []
        packages = self.packages_with_prefetch_related
        if self.limit:
            packages = packages[:self.limit]

        template = self.get_row_template()
        fields = [f() for f in self.table_fields]
        context = {}

        for package in packages:
            context['package'] = package
            for field in fields:
                context[field.slug] = field.context(package)
            rows.append(template.render(Context(context)))

        return rows

    @property
    def number_of_packages(self):
        """
        Returns the number of packages displayed in the table
        """
        if hasattr(self.packages_with_prefetch_related, 'count'):
            return self.packages_with_prefetch_related.count()
        else:
            return 0

    @staticmethod
    def get_template_content(template_name):
        with open(get_template(template_name).origin.name) as f:
            return f.read()

    def get_row_template(self):
        template = "<tr scope='row'>\n"
        for f in self.table_fields:
            template += "<td class='center' scope='col'>"
            template += self.get_template_content(f().template_name)
            template += "</td>\n"
        template += "</tr>\n"
        return Template(template)


def create_table(slug, scope, title=None, limit=None, tag=None):
    """
    A helper function to create packages table. The table class is defined
    through the `slug`. If no children class of
    :class:`BasePackageTable` exists with the given slug, the function returns
    `None`.

    :returns: an instance of the table created with the informed params
    :rtype: :class:`BasePackageTable`
    """
    for app in settings.INSTALLED_APPS:
        try:
            module_name = app + '.' + 'tracker_package_tables'
            importlib.import_module(module_name)
        except ImportError:
            # The app does not implement package tables.
            pass

    for table_class in BasePackageTable.plugins:
        if table_class is not BasePackageTable:
            table = table_class(scope, title=title, limit=limit, tag=tag)
            if table.slug == slug:
                return table

    return None


class GeneralTeamPackageTable(BasePackageTable):
    """
    This table displays the packages information of a team in a simple fashion.
    It must receive a :class:`Team <distro_tracker.core.models.Team>` as scope
    """
    default_title = "All team packages"
    slug = 'general'

    @property
    def packages(self):
        """
        Returns the list of packages shown in the table of a team (scope)
        """
        return self.scope.packages.all().order_by('name')
