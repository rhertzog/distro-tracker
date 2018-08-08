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

from distro_tracker.core.models import (
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
        return item.pk

    def items_all_keys(self):
        # Better implementation with an optimized query
        return set(self.items_all().values_list('pk', flat=True))

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

    def item_describe(self, item):
        data = super().item_describe(item)
        data['name'] = item.source_package.name
        data['version'] = item.source_package.version
        data['repository'] = item.repository.shorthand
        return data


class ProcessSrcRepoEntryInDefaultRepository(ProcessSrcRepoEntry):
    """
    Process
    :class:`~distro_tracker.core.models.SourcePackageRepositoryEntry`.
    from the default repository.
    """

    def items_extend_queryset(self, queryset):
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
        return item.id

    def item_describe(self, item):
        return {
            'name': item.source_package.name,
            'version': item.source_package.version,
            'repository': item.repository.shorthand,
        }
