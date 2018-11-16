# Copyright 2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Mixins to combine to create powerful tasks.

"""
import logging

from debian.debian_support import version_compare

from django.db import transaction

from distro_tracker.core.models import (
    PackageData,
    Repository,
    SourcePackage,
    SourcePackageRepositoryEntry,
)

logger = logging.getLogger('distro_tracker.tasks')


class ProcessItems(object):
    """
    Base class for all Process* mixins. Those mixins defines a list of
    items that the task should process.
    """

    def __init__(self):
        self.register_event_handler('execute-started',
                                    self.handle_fake_update_parameter)
        self.register_event_handler('execute-finished',
                                    self.items_cleanup_processed_list)
        super().__init__()

    def item_to_key(self, item):
        """
        Converts an item to process into a unique string representation
        than can be used to record the fact that the item has been processed.

        :param object item: Any kind of object.
        :return: A unique string representation of the object.
        :rtype: str
        """
        return str(item)

    def item_describe(self, item):
        """
        Converts an item into a dictionnary with the most important
        data of the item that we want to save for later when the item
        will have vanished.

        :param object item: Any kind of object.
        :return: A dictionnary describing the object.
        :rtype: dict
        """
        return {}

    def item_mark_processed(self, *args):
        """
        Mark an item as having been processed. This records the key associated
        to the item in a ``processed`` dictionnary within the persistent
        data of the task.

        :param *args: list of items to mark as having been processed
        """
        processed = self.data.setdefault('processed', {})
        for item in args:
            processed[self.item_to_key(item)] = self.item_describe(item)
        self.data_mark_modified()

    def item_needs_processing(self, item):
        """
        Verifies if the item needs to be processed or not.

        :param object item: the item to check
        :return: True if the obect is not recorded as having already been
            processed, False otherwise.
        :rtype: bool
        """
        processed = self.data.setdefault('processed', {})
        return self.item_to_key(item) not in processed

    def items_all(self):
        """
        This method returns an iterable of all the existing items, including
        those that have already been processed and those which are going to be
        processed.

        :return: All the existing items.
        :rtype: An iterable, can be an iterator or a list, set, tuple.
        """
        raise NotImplementedError("ProcessItems.items_all() must be overriden.")

    def items_to_process(self):
        """
        This method returns the items that have to be processed by the task.

        Its default implementation in :class:`ProcessItems` is to iterate over
        the items returned by :meth:`items_all` and to :func:`yield` those where
        :meth:`item_needs_processing` returns True.

        If the `force_update` parameter is set to True, then it returns all the
        items without calling :meth:`item_needs_processing`.
        """
        for item in self.items_all():
            if self.force_update or self.item_needs_processing(item):
                yield item

    def items_all_keys(self):
        """
        This method returns all the keys corresponding to valid-existing
        items.

        Its main purpose is to be able to compute the list of keys
        in the 'already-processed' list that are no-longer relevant and can be
        dropped.

        Its default implementation is to iterate over items returned by
        :meth:`items_all` and call :meth:`item_to_key` on them. This method
        can thus be overrident when there are more efficient ways to implement
        this logic.

        :return: the set of keys of the valid objects
        :rtype: set
        """
        return set([self.item_to_key(x) for x in self.items_all()])

    def items_to_cleanup(self):
        """
        This method returns an iterators returning a tuple
        (key, description) for old items that have been processed
        in the past but are no longer existing in :meth:`all_items`.

        The description is the value returned by :meth:`item_describe`
        at the time when the item has been processed. The key is the value
        returned by :meth:`item_to_key` at the time when the item has been
        processed.

        :return: (key, description)
        :rtype: tuple
        """
        processed = self.data.setdefault('processed', {})
        processed_set = set(processed.keys())
        unused_keys = processed_set.difference(self.items_all_keys())
        for key in unused_keys:
            yield (key, processed[key])

    def items_cleanup_processed_list(self):
        """
        This method drops unused keys from the list of processed items.

        To identify unused keys, it computes the difference between the
        set of keys present in the 'processed' list and the set of keys
        returned by :meth:`items_all_keys`.
        """
        processed = self.data.setdefault('processed', {})
        modified = False
        for key, _ in self.items_to_cleanup():
            del processed[key]
            modified = True
        if modified:
            self.data_mark_modified()

    def items_fake_processed_list(self):
        '''
        This method goes over all items to process and marks them as processed.
        This is useful to fake the whole update process and bootstrap an
        iterative process where we don't want the initial run to process
        all existing entries.
        '''
        for item in self.items_to_process():
            self.item_mark_processed(item)

    def handle_fake_update_parameter(self):
        '''
        This method is registered as an execute-started event handler and
        marks all items as processed even before the task has a chance to
        process them.
        '''
        if self.fake_update:
            self.items_fake_processed_list()


class ProcessModel(ProcessItems):
    """
    With this mixin, the list of items to be processed is a list of objects
    retrieved through the database model specified in the :attr:`model`
    attribute. Sub-classes should thus at least override this attribute.
    """

    #: The database model defining the list of items to process
    model = None

    def items_all(self):
        return self.items_extend_queryset(self.model.objects.all())

    def items_to_process(self):
        items = self.items_all()
        # Exclude the items already processed, unless --force-update tells us to
        # reprocess all entries
        if not self.force_update:
            processed = self.data.setdefault('processed', {})
            # XXX: might not be the right thing when primary key is not the id
            processed_keys = list(map(lambda x: int(x), processed.keys()))
            items = items.exclude(pk__in=processed_keys)
        return items

    def items_extend_queryset(self, queryset):
        """
        This method can be overriden by sub-classes to customize the queryset
        returned by :meth:`items_all`. The normal queryset is passed as
        parameter and the method should return the modified queryset.

        :param QuerySet queryset: the original queryset
        :return: the modified queryset
        :rtype: QuerySet
        """
        return queryset

    def item_to_key(self, item):
        """
        For database objects, we use the primary key as the key for the
        processed list.

        :param item: an instance of the associated model
        :return: the value of its primary key
        """
        return str(item.pk)

    def items_all_keys(self):
        # Better implementation with an optimized query
        return set(map(lambda x: str(x),
                       self.items_all().values_list('pk', flat=True)))

    def item_describe(self, item):
        data = super().item_describe(item)
        for field_name in getattr(self, 'fields_to_save', []):
            field = getattr(item, field_name)
            if callable(field):
                field = field()
            data[field_name] = field
        return data


class ProcessSourcePackage(ProcessModel):
    """
    Process all :class:`~distro_tracker.core.models.SourcePackage` objects.
    """
    model = SourcePackage
    fields_to_save = ('name', 'version')


class ProcessSrcRepoEntry(ProcessModel):
    """
    Process all
    :class:`~distro_tracker.core.models.SourcePackageRepositoryEntry`.
    """

    model = SourcePackageRepositoryEntry

    def items_extend_queryset(self, queryset):
        return queryset.select_related(
            'source_package__source_package_name', 'repository')

    def item_describe(self, item):
        data = super().item_describe(item)
        data['name'] = item.source_package.name
        data['version'] = item.source_package.version
        data['repository'] = item.repository.shorthand
        data['repository_id'] = item.repository.id
        return data


class ProcessSrcRepoEntryInDefaultRepository(ProcessSrcRepoEntry):
    """
    Process
    :class:`~distro_tracker.core.models.SourcePackageRepositoryEntry`.
    from the default repository.
    """

    def items_extend_queryset(self, queryset):
        queryset = super().items_extend_queryset(queryset)
        return queryset.filter(repository__default=True)


class ProcessMainRepoEntry(ProcessItems):
    """
    Process the main
    :class:`~distro_tracker.core.models.SourcePackageRepositoryEntry`
    for each package. The main entry is defined as being the one existing in the
    default repository. If there's no default entry for a given package, then
    it's the entry with the biggest version that is taken. If there are still
    two entries, then we take the one in the repository with the biggest
    "position".
    """

    def __init__(self):
        super().__init__()
        self.main_entries = None
        self.register_event_handler('execute-started',
                                    self.clear_main_entries_cache)
        self.register_event_handler('execute-finished',
                                    self.clear_main_entries_cache)
        self.register_event_handler('execute-failed',
                                    self.clear_main_entries_cache)

    def clear_main_entries_cache(self):
        self.main_entries = None

    def items_all(self):
        if self.main_entries is not None:
            return self.main_entries.values()

        main_entries = {}

        def register_entry(entry):
            name = entry.source_package.name
            version = entry.source_package.version
            if name not in main_entries:
                main_entries[name] = entry
            else:
                selected_version = main_entries[name].source_package.version
                if version_compare(selected_version, version) < 0:
                    main_entries[name] = entry
                elif version_compare(selected_version, version) == 0:
                    # If both versions are equal, we use the repository with the
                    # biggest position
                    if (entry.repository.position >
                            main_entries[name].repository.position):
                        main_entries[name] = entry

        # First identify entries from the default repository
        qs = SourcePackageRepositoryEntry.objects.filter(
            repository__default=True).select_related(
                'source_package__source_package_name',
                'repository')

        for entry in qs:
            register_entry(entry)

        # Then again for all the other remaining packages
        qs = SourcePackageRepositoryEntry.objects.exclude(
            source_package__source_package_name__name__in=main_entries.keys()
        ).select_related(
            'source_package__source_package_name',
            'repository'
        )
        for entry in qs:
            register_entry(entry)

        self.main_entries = main_entries
        return self.main_entries.values()

    def item_to_key(self, item):
        return str(item.id)

    def item_describe(self, item):
        return {
            'name': item.source_package.name,
            'version': item.source_package.version,
            'repository': item.repository.shorthand,
        }


class ProcessRepositoryUpdates(ProcessSrcRepoEntry):
    """
    Watch repositories and generates updates operations to be processed.

    :meth:`items_to_process` returns repository entries but you can query
    :meth:`is_new_source_package` on the associated source package to know
    if the source package was already present in another repository in the
    previous run or not.

    There's a new :meth:`iter_removals_by_repository` to find out packages
    which have been dropped from the repository.
    """

    def __init__(self):
        super().__init__()
        self.register_event_handler('execute-started',
                                    self.compute_known_packages)

    def compute_known_packages(self):
        """
        Goes over the list of formerly processed items and builds lists to
        quickly lookup wether a given package is new or not.
        """
        self.pkglist = {
            'all': {},
        }
        self.srcpkglist = {
            'all': {},
        }
        for data in self.data.get('processed', {}).values():
            key = '%s_%s' % (data['name'], data['version'])
            self.pkglist['all'][data['name']] = True
            self.srcpkglist['all'][key] = True
            repo_pkglist = self.pkglist.setdefault(data['repository_id'], {})
            repo_srcpkglist = self.srcpkglist.setdefault(data['repository_id'],
                                                         {})
            repo_pkglist[data['name']] = True
            repo_srcpkglist[key] = True

    def is_new_source_package(self, srcpkg):
        """
        Returns True if the source package was not present in the former run,
        False otherwise.

        The existence of the source package is deducted from the list of already
        processed entries (with the help of :meth:`compute_known_packages` which
        is called at the start of the :meth:`execute` method.

        :param srcpkg: the source package
        :type srcpkg: :class:`~distro_tracker.core.models.SourcePackage`
        :returns: True if never seen, False otherwise
        :rtype: bool
        """
        key = '%s_%s' % (srcpkg.name, srcpkg.version)
        return key not in self.srcpkglist['all']

    def iter_removals_by_repository(self):
        """
        Returns an iterator to process all package removals that happened in all
        the repositories. The iterator yields tuples with the package name (as
        a string) and the repository object.
        """
        for repository in Repository.objects.all():
            if repository.id not in self.pkglist:
                continue
            qs = repository.source_packages.all()
            new_pkglist = set(
                qs.values_list('source_package_name__name', flat=True))
            for package in self.pkglist[repository.id]:
                if package not in new_pkglist:
                    yield (package, repository)


class PackageTagging(object):
    """
    A task mixin that helps to maintain a set of package tags:
    by untagging packages that no longer should be tagged and by
    tagging packages that should.

    Subclasses must define:
    - `TAG_NAME`: defines the key for PackageData to be updated. One must define
    keys matching `tag:.*`
    - `TAG_DISPLAY_NAME`: defines the display name for the tag
    - `TAG_COLOR_TYPE`: defines the color type to be used while rendering
    content related to the tag. It must be defined based on the tag severity.
    One may use one of the following options: success, danger, warning, or info.
    - `TAG_DESCRIPTION`: defines a help text to be displayed with a 'title'
    attribute
    - `TAG_TABLE_TITLE`: the title of the table showing all the packages
    with this tag

    Also, subclasses must implement the :func:`packages_to_tag` function to
    define the list of packages that must be tagged.
    """
    TAG_NAME = None
    TAG_DISPLAY_NAME = ''
    TAG_COLOR_TYPE = ''
    TAG_DESCRIPTION = ''
    TAG_TABLE_TITLE = ''

    def packages_to_tag(self):
        """
        Subclasses must override this method to return the list of packages
        that must be tagged with the tag defined by `TAG_NAME`
        """
        return []

    def execute_package_tagging(self):
        with transaction.atomic():
            # Clear previous TaggedItems
            PackageData.objects.filter(key=self.TAG_NAME).delete()

            items = []
            value = {
                'display_name': self.TAG_DISPLAY_NAME,
                'color_type': self.TAG_COLOR_TYPE,
                'description': self.TAG_DESCRIPTION,
                'table_title': self.TAG_TABLE_TITLE
            }
            for package in self.packages_to_tag():
                tag = PackageData(
                    package=package, key=self.TAG_NAME, value=value)
                items.append(tag)
            PackageData.objects.bulk_create(items)
