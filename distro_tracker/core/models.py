# Copyright 2013-2017 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Models for the :mod:`distro_tracker.core` app."""
import hashlib
import logging
import os
import random
import re
import string
import warnings
from datetime import timedelta
from email.iterators import typed_subpart_iterator
from email.utils import getaddresses, parseaddr

from debian import changelog as debian_changelog
from debian.debian_support import AptPkgVersion

from django.conf import settings
from django.core.exceptions import (
    MultipleObjectsReturned,
    ObjectDoesNotExist,
    ValidationError
)
from django.core.files.base import ContentFile
from django.db import connection, models
from django.db.models import Q
from django.db.utils import IntegrityError
from django.template.defaultfilters import slugify
from django.template.exceptions import TemplateDoesNotExist
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_text
from django.utils.functional import cached_property
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from jsonfield import JSONField

from distro_tracker import vendor
from distro_tracker.core.utils import (
    SpaceDelimitedTextField,
    distro_tracker_render_to_string,
    get_or_none,
    now,
    verify_signature
)
from distro_tracker.core.utils.email_messages import (
    decode_header,
    get_decoded_message_payload,
    message_from_bytes
)
from distro_tracker.core.utils.linkify import linkify
from distro_tracker.core.utils.misc import get_data_checksum
from distro_tracker.core.utils.packages import package_hashdir
from distro_tracker.core.utils.plugins import PluginRegistry

from django_email_accounts.models import UserEmail

DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS = \
    settings.DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS

logger_input = logging.getLogger('distro_tracker.input')


class Keyword(models.Model):
    """
    Describes a keyword which can be used to tag package messages.
    """
    name = models.CharField(max_length=50, unique=True)
    default = models.BooleanField(default=False)
    description = models.CharField(max_length=256, blank=True)

    def __str__(self):
        return self.name


class EmailSettings(models.Model):
    """
    Settings for an email
    """
    user_email = models.OneToOneField(UserEmail, on_delete=models.CASCADE)
    default_keywords = models.ManyToManyField(Keyword)

    def __str__(self):
        return self.email

    @cached_property
    def email(self):
        return self.user_email.email

    @cached_property
    def user(self):
        return self.user_email.user

    def save(self, *args, **kwargs):
        """
        Overrides the default save method to add the set of default keywords to
        the user's own default keywords after creating an instance.
        """
        new_object = not self.id
        models.Model.save(self, *args, **kwargs)
        if new_object:
            self.default_keywords.set(Keyword.objects.filter(default=True))

    def is_subscribed_to(self, package):
        """
        Checks if the user is subscribed to the given package.

        :param package: The package (or package name)
        :type package: :class:`Package` or string
        """
        if not isinstance(package, PackageName):
            package = get_or_none(PackageName, name=package)
            if not package:
                return False

        return package in (
            subscription.package
            for subscription in self.subscription_set.all_active()
        )

    def unsubscribe_all(self):
        """
        Terminates all of the user's subscriptions.
        """
        self.subscription_set.all().delete()


class PackageManagerQuerySet(models.query.QuerySet):
    """
    A custom :class:`PackageManagerQuerySet <django.db.models.query.QuerySet>`
    for the :class:`PackageManager` manager. It is needed in order to change
    the bulk delete behavior.
    """
    def delete(self):
        """
        In the bulk delete, the only cases when an item should be deleted is:
         - when the bulk delete is made directly from the PackageName class

        Else, the field corresponding to the package type you want to delete
        should be set to False.
        """
        if self.model.objects.type is None:
            # Means the bulk delete is done from the PackageName class
            super(PackageManagerQuerySet, self).delete()
        else:
            # Called from a proxy class: here, this is only a soft delete
            self.update(**{self.model.objects.type: False})


class PackageManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`PackageName` model.
    """
    def __init__(self, package_type=None, *args, **kwargs):
        super(PackageManager, self).__init__(*args, **kwargs)
        self.type = package_type

    def get_queryset(self):
        """
        Overrides the default query set of the manager to exclude any
        :class:`PackageName` objects with a type that does not match this
        manager instance's :attr:`type`.

        If the instance does not have a :attr:`type`, then all
        :class:`PackageName` instances are returned.
        """
        qs = PackageManagerQuerySet(self.model, using=self._db)
        if self.type is None:
            return qs
        return qs.filter(**{
            self.type: True,
        })

    def exists_with_name(self, package_name):
        """
        :param package_name: The name of the package
        :type package_name: string
        :returns True: If a package with the given name exists.
        """
        return self.filter(name=package_name).exists()

    def create(self, *args, **kwargs):
        """
        Overrides the default :meth:`create <django.db.models.Manager.create>`
        method to inject a :attr:`package_type <PackageName.package_type>` to
        the instance being created.

        The type is the type given in this manager instance's :attr:`type`
        attribute.
        """
        if self.type not in kwargs and self.type is not None:
            kwargs[self.type] = True

        return super(PackageManager, self).create(*args, **kwargs)

    def get_or_create(self, *args, **kwargs):
        """
        Overrides the default
        :meth:`get_or_create <django.db.models.Manager.get_or_create>`
        to set the correct package type.

        The type is the type given in this manager instance's :attr:`type`
        attribute.
        """
        defaults = kwargs.get('defaults', {})
        if self.type is not None:
            defaults.update({self.type: True})
        kwargs['defaults'] = defaults
        entry, created = PackageName.default_manager.get_or_create(*args,
                                                                   **kwargs)
        if self.type and getattr(entry, self.type) is False:
            created = True
            setattr(entry, self.type, True)
            entry.save()
        if isinstance(entry, self.model):
            return entry, created
        else:
            return self.get(pk=entry.pk), created

    def all_with_subscribers(self):
        """
        A method which filters the packages and returns a QuerySet
        containing only those which have at least one subscriber.

        :rtype: :py:class:`QuerySet <django.db.models.query.QuerySet>` of
            :py:class:`PackageName` instances.
        """
        qs = self.annotate(subscriber_count=models.Count('subscriptions'))
        return qs.filter(subscriber_count__gt=0)

    def get_by_name(self, package_name):
        """
        :returns: A package with the given name
        :rtype: :class:`PackageName`
        """
        return self.get(name=package_name)


class PackageName(models.Model):
    """
    A model describing package names.

    Three different types of packages are supported:

    - Source packages
    - Binary packages
    - Pseudo packages

    PackageName associated to no source/binary/pseudo packages are
    referred to as "Subscription-only packages".
    """
    name = models.CharField(max_length=100, unique=True)
    source = models.BooleanField(default=False)
    binary = models.BooleanField(default=False)
    pseudo = models.BooleanField(default=False)

    subscriptions = models.ManyToManyField(EmailSettings,
                                           through='Subscription')

    objects = PackageManager()
    source_packages = PackageManager('source')
    binary_packages = PackageManager('binary')
    pseudo_packages = PackageManager('pseudo')
    default_manager = models.Manager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('dtracker-package-page', kwargs={
            'package_name': self.name,
        })

    def get_package_type_display(self):
        if self.source:
            return 'Source package'
        elif self.binary:
            return 'Binary package'
        elif self.pseudo:
            return 'Pseudo package'
        else:
            return 'Subscription-only package'

    def get_action_item_for_type(self, action_item_type):
        """
        :param: The name of the :class:`ActionItemType` of the
            :class:`ActionItem` which is to be returned or an
            :class:`ActionItemType` instance.
        :type param: :class:`ActionItemType` or :class:`string`

        :returns: An action item with the given type name which is associated
            to this :class:`PackageName` instance. ``None`` if the package
            has no action items of that type.
        :rtype: :class:`ActionItem` or ``None``
        """
        if isinstance(action_item_type, ActionItemType):
            action_item_type = action_item_type.type_name
        return next((
            item
            for item in self.action_items.all()
            if item.item_type.type_name == action_item_type),
            None)

    def delete(self, *args, **kwargs):
        """
        Custom delete method so that PackageName proxy classes
        do not remove the underlying PackageName. Instead they update
        their corresponding "type" field to False so that they
        no longer find the package name.

        The delete method on PackageName keeps its default behaviour.
        """
        if self.__class__.objects.type:
            setattr(self, self.__class__.objects.type, False)
            self.save()
        else:
            super(PackageName, self).delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        if not re.match('[0-9a-z][-+.0-9a-z]+$', self.name):
            raise ValidationError(format_html(
                'Invalid package name: {}',
                self.name,
            ))
        models.Model.save(self, *args, **kwargs)


class PseudoPackageName(PackageName):
    """
    A convenience proxy model of the :class:`PackageName` model.

    It returns only those :class:`PackageName` instances whose
    :attr:`pseudo <PackageName.pseudo>` attribute is True.
    """
    class Meta:
        proxy = True

    objects = PackageManager('pseudo')


class BinaryPackageName(PackageName):
    """
    A convenience proxy model of the :class:`PackageName` model.

    It returns only those :class:`PackageName` instances whose
    :attr:`binary <PackageName.binary>` attribute is True.
    """
    class Meta:
        proxy = True

    objects = PackageManager('binary')

    def get_absolute_url(self):
        # Take the URL of its source package
        main_source_package = self.main_source_package_name
        if main_source_package:
            return main_source_package.get_absolute_url()
        else:
            return None

    @property
    def main_source_package_name(self):
        """
        Returns the main source package name to which this binary package
        name is mapped.

        The "main source package" is defined as follows:

        - If the binary package is found in the default repository, the returned
          source package name is the one which has the highest version.
        - If the binary package is not found in the default repository, the
          returned source package name is the one of the source package with
          the highest version.

        :rtype: string

        This is used for redirecting users who try to access a Web page for
        by giving this binary's name.
        """
        default_repo_sources_qs = self.sourcepackage_set.filter(
            repository_entries__repository__default=True)
        if default_repo_sources_qs.exists():
            qs = default_repo_sources_qs
        else:
            qs = self.sourcepackage_set.all()

        if qs.exists():
            source_package = max(qs, key=lambda x: AptPkgVersion(x.version))
            return source_package.source_package_name
        else:
            return None


class SourcePackageName(PackageName):
    """
    A convenience proxy model of the :class:`PackageName` model.

    It returns only those :class:`PackageName` instances whose
    :attr:`source <PackageName.source>` attribute is True.
    """
    class Meta:
        proxy = True

    objects = PackageManager('source')

    @cached_property
    def main_version(self):
        """
        Returns the main version of this :class:`SourcePackageName` instance.
        :rtype: string

        It is defined as either the highest version found in the default
        repository, or if the package is not found in the default repository at
        all, the highest available version.
        """
        default_repository_qs = self.source_package_versions.filter(
            repository_entries__repository__default=True)
        if default_repository_qs.exists():
            qs = default_repository_qs
        else:
            qs = self.source_package_versions.all()

        qs.select_related()
        try:
            return max(qs, key=lambda x: AptPkgVersion(x.version))
        except ValueError:
            return None

    @cached_property
    def main_entry(self):
        """
        Returns the :class:`SourcePackageRepositoryEntry` which represents the
        package's entry in either the default repository (if the package is
        found there) or in the first repository (as defined by the repository
        order) which has the highest available package version.
        """
        default_repository_qs = SourcePackageRepositoryEntry.objects.filter(
            repository__default=True,
            source_package__source_package_name=self
        )
        if default_repository_qs.exists():
            qs = default_repository_qs
        else:
            qs = SourcePackageRepositoryEntry.objects.filter(
                source_package__source_package_name=self)

        qs = qs.select_related()
        try:
            return max(
                qs,
                key=lambda x: AptPkgVersion(x.source_package.version)
            )
        except ValueError:
            return None

    @cached_property
    def repositories(self):
        """
        Returns all repositories which contain a source package with this name.

        :rtype: :py:class:`QuerySet <django.db.models.query.QuerySet>` of
            :py:class:`Repository` instances.
        """
        kwargs = {
            'source_entries'
            '__source_package'
            '__source_package_name': self
        }
        return Repository.objects.filter(**kwargs).distinct()

    def short_description(self):
        """
        Returns the most recent short description for a source package. If there
        is a binary package whose name matches the source package, its
        description will be used. If not, the short description for the first
        binary package will be used.
        """
        if not self.main_version:
            return ''

        binary_packages = self.main_version.binarypackage_set.all()

        for pkg in binary_packages:
            if pkg.binary_package_name.name == self.name:
                return pkg.short_description

        if len(binary_packages) == 1:
            return binary_packages[0].short_description

        return ''


def get_web_package(package_name):
    """
    Utility function mapping a package name to its most adequate Python
    representation (among :class:`SourcePackageName`,
    :class:`PseudoPackageName`, :class:`PackageName` and ``None``).

    The rules are simple: a source package is returned as SourcePackageName,
    a pseudo-package is returned as PseudoPackageName, a binary package
    is turned into the corresponding SourcePackageName (which might have a
    different name!).

    If the package name is known but is none of the above, it's only returned
    if it has associated :class:`News` since that proves that it used to be
    a former source package.

    If that is not the case, then ``None`` is returned. You can use a "src:"
    or "bin:" prefix to the package name to restrict the lookup among source
    packages or binary packages, respectively.

    :rtype: :class:`PackageName` or ``None``

    :param package_name: The name for which a package should be found.
    :type package_name: string
    """

    search_among = (
        SourcePackageName,
        PseudoPackageName,
        BinaryPackageName,
        PackageName
    )

    if package_name.startswith("src:"):
        package_name = package_name[4:]
        search_among = (SourcePackageName, PackageName)
    elif package_name.startswith("bin:"):
        package_name = package_name[4:]
        search_among = (BinaryPackageName,)

    for cls in search_among:
        if cls.objects.exists_with_name(package_name):
            pkg = cls.objects.get(name=package_name)
            if cls is BinaryPackageName:
                return pkg.main_source_package_name
            elif cls is PackageName:
                # This is not a current source or binary package, but if it has
                # associated news, then it's likely a former source package
                # where we can display something useful
                if pkg.news_set.count():
                    return pkg
            else:
                return pkg

    return None


class SubscriptionManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`Subscription` class.
    """
    def create_for(self, package_name, email, active=True):
        """
        Creates a new subscription based on the given arguments.

        :param package_name: The name of the subscription package
        :type package_name: string

        :param email: The email address of the user subscribing to the package
        :type email: string

        :param active: Indicates whether the subscription should be activated
            as soon as it is created.

        :returns: The subscription for the given ``(email, package_name)`` pair.
        :rtype: :class:`Subscription`
        """
        package = get_or_none(PackageName, name=package_name)
        if not package:
            # If the package did not previously exist, create a
            # "subscriptions-only" package.
            package = PackageName.objects.create(
                name=package_name)
        user_email, _ = UserEmail.objects.get_or_create(email=email)
        email_settings, _ = EmailSettings.objects.get_or_create(
            user_email=user_email)

        subscription, _ = self.get_or_create(email_settings=email_settings,
                                             package=package)
        subscription.active = active
        subscription.save()

        return subscription

    def unsubscribe(self, package_name, email):
        """
        Unsubscribes the given email from the given package.

        :param email: The email of the user
        :param package_name: The name of the package the user should be
            unsubscribed from

        :returns True: If the user was successfully unsubscribed
        :returns False: If the user was not unsubscribed, e.g. the subscription
            did not even exist.
        """
        package = get_or_none(PackageName, name=package_name)
        user_email = get_or_none(UserEmail, email__iexact=email)
        email_settings = get_or_none(EmailSettings, user_email=user_email)
        if not package or not user_email or not email_settings:
            return False
        subscription = get_or_none(
            Subscription, email_settings=email_settings, package=package)
        if subscription:
            subscription.delete()
        return True

    def get_for_email(self, email):
        """
        Returns a list of active subscriptions for the given user.

        :param email: The email address of the user
        :type email: string

        :rtype: ``iterable`` of :class:`Subscription` instances

        .. note::
           Since this method is not guaranteed to return a
           :py:class:`QuerySet <django.db.models.query.QuerySet>` object,
           clients should not count on chaining additional filters to the
           result.
        """
        user_email = get_or_none(UserEmail, email__iexact=email)
        email_settings = get_or_none(EmailSettings, user_email=user_email)
        if not user_email or not email_settings:
            return []
        return email_settings.subscription_set.all_active()

    def all_active(self, keyword=None):
        """
        Returns all active subscriptions, optionally filtered on having the
        given keyword.

        :rtype: ``iterable`` of :class:`Subscription` instances

        .. note::
           Since this method is not guaranteed to return a
           :py:class:`QuerySet <django.db.models.query.QuerySet>` object,
           clients should not count on chaining additional filters to the
           result.
        """
        actives = self.filter(active=True)
        if keyword:
            keyword = get_or_none(Keyword, name=keyword)
            if not keyword:
                return self.none()
            actives = [
                subscription
                for subscription in actives
                if keyword in subscription.keywords.all()
            ]
        return actives


class Subscription(models.Model):
    """
    A model describing a subscription of a single :class:`EmailSettings` to a
    single :class:`PackageName`.
    """
    email_settings = models.ForeignKey(EmailSettings, on_delete=models.CASCADE)
    package = models.ForeignKey(PackageName, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)
    _keywords = models.ManyToManyField(Keyword)
    _use_user_default_keywords = models.BooleanField(default=True)

    objects = SubscriptionManager()

    class Meta:
        unique_together = ('email_settings', 'package')

    class KeywordsAdapter(object):
        """
        An adapter for accessing a :class:`Subscription`'s keywords.

        When a :class:`Subscription` is initially created, it uses the default
        keywords of the user. Only after modifying the subscription-specific
        keywords, should it use a different set of keywords.

        This class allows the clients of the class:`Subscription` class to
        access the :attr:`keywords <Subscription.keywords>` field without
        having to think about whether the subscription is using the user's
        keywords or not, rather the whole process is handled automatically and
        seamlessly.
        """
        def __init__(self, subscription):
            #: Keep a reference to the original subscription object
            self._subscription = subscription

        def __getattr__(self, name):
            # Methods which modify the set should cause it to become unlinked
            # from the user.
            if name in ('add', 'remove', 'create', 'clear', 'bulk_create'):
                self._unlink_from_user()
            return getattr(self._get_manager(), name)

        def _get_manager(self):
            """
            Helper method which returns the appropriate manager depending on
            whether the subscription is still using the user's keywords or not.
            """
            if self._subscription._use_user_default_keywords:
                manager = self._subscription.email_settings.default_keywords
            else:
                manager = self._subscription._keywords
            return manager

        def _unlink_from_user(self):
            """
            Helper method which unlinks the subscription from the user's
            default keywords.
            """
            if self._subscription._use_user_default_keywords:
                # Do not use the user's keywords anymore
                self._subscription._use_user_default_keywords = False
                # Copy the user's keywords
                email_settings = self._subscription.email_settings
                for keyword in email_settings.default_keywords.all():
                    self._subscription._keywords.add(keyword)
                self._subscription.save()

    def __init__(self, *args, **kwargs):
        super(Subscription, self).__init__(*args, **kwargs)
        self.keywords = Subscription.KeywordsAdapter(self)

    def __str__(self):
        return str(self.email_settings.user_email) + ' ' + str(self.package)


class Architecture(models.Model):
    """
    A model describing a single architecture.
    """
    name = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.name


class RepositoryManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`Repository` model.
    """
    def get_default(self):
        """
        Returns the default :class:`Repository` instance.

        If there is no default repository, returns an empty
        :py:class:`QuerySet <django.db.models.query.QuerySet>`

        :rtype: :py:class:`QuerySet <django.db.models.query.QuerySet>`
        """
        return self.filter(default=True)


class Repository(models.Model):
    """
    A model describing Debian repositories.
    """
    name = models.CharField(max_length=50, unique=True)
    shorthand = models.CharField(max_length=10, unique=True)

    uri = models.CharField(max_length=200, verbose_name='URI')
    public_uri = models.URLField(
        max_length=200,
        blank=True,
        verbose_name='public URI'
    )
    suite = models.CharField(max_length=50)
    codename = models.CharField(max_length=50, blank=True)
    components = SpaceDelimitedTextField()
    architectures = models.ManyToManyField(Architecture, blank=True)
    default = models.BooleanField(default=False)

    optional = models.BooleanField(default=True)
    binary = models.BooleanField(default=True)
    source = models.BooleanField(default=True)

    source_packages = models.ManyToManyField(
        'SourcePackage',
        through='SourcePackageRepositoryEntry'
    )

    position = models.IntegerField(default=0)

    objects = RepositoryManager()

    class Meta:
        verbose_name_plural = "repositories"
        ordering = (
            'position',
        )

    def __str__(self):
        return self.name

    @classmethod
    def find(cls, identifier):
        """
        Looks up a repository, trying first with a match on "name"; if
        that fails, sequentially try "shorthand", "codename" and "suite".

        Matching by "codename" and "suite" will only be used if they return
        a single match.

        If no match is found, then raises a ValueError.
        """
        try:
            return Repository.objects.get(name=identifier)
        except ObjectDoesNotExist:
            pass

        try:
            return Repository.objects.get(shorthand=identifier)
        except ObjectDoesNotExist:
            pass

        try:
            return Repository.objects.get(codename=identifier)
        except (ObjectDoesNotExist, MultipleObjectsReturned):
            pass

        try:
            return Repository.objects.get(suite=identifier)
        except (ObjectDoesNotExist, MultipleObjectsReturned):
            pass

        raise ValueError("%s does not uniquely identifies a repository" %
                         identifier)

    @property
    def sources_list_entry(self):
        """
        Returns the sources.list entries based on the repository's attributes.

        :rtype: string
        """
        entry_common = (
            '{uri} {suite} {components}'.format(
                uri=self.uri,
                suite=self.suite,
                components=' '.join(self.components)
            )
        )
        src_entry = 'deb-src ' + entry_common
        if not self.binary:
            return src_entry
        else:
            bin_entry = 'deb [arch={archs}] ' + entry_common
            archs = ','.join(map(str, self.architectures.all()))
            bin_entry = bin_entry.format(archs=archs)
            return '\n'.join((src_entry, bin_entry))

    @property
    def component_urls(self):
        """
        Returns a list of URLs which represent full URLs for each of the
        components of the repository.

        :rtype: list
        """
        base_url = self.uri.rstrip('/')
        return [
            base_url + '/' + self.suite + '/' + component
            for component in self.components
        ]

    def get_source_package_entry(self, package_name):
        """
        Returns the canonical :class:`SourcePackageRepositoryEntry` with the
        given name, if found in the repository.

        This means the instance with the highest
        :attr:`version <SourcePackage.version>` is returned.

        If there is no :class:`SourcePackageRepositoryEntry` for the given name
        in this repository, returns ``None``.

        :param package_name: The name of the package for which the entry should
            be returned
        :type package_name: string or :class:`SourcePackageName`

        :rtype: :class:`SourcePackageRepositoryEntry` or ``None``
        """
        if isinstance(package_name, SourcePackageName):
            package_name = package_name.name
        qs = self.source_entries.filter(
            source_package__source_package_name__name=package_name)
        qs = qs.select_related()
        try:
            return max(
                qs,
                key=lambda x: AptPkgVersion(x.source_package.version))
        except ValueError:
            return None

    def add_source_package(self, package, **kwargs):
        """
        The method adds a new class:`SourcePackage` to the repository.

        :param package: The source package to add to the repository
        :type package: :class:`SourcePackage`

        The parameters needed for the corresponding
        :class:`SourcePackageRepositoryEntry` should be in the keyword
        arguments.

        Returns the newly created :class:`SourcePackageRepositoryEntry` for the
        given :class:`SourcePackage`.

        :rtype: :class:`SourcePackageRepositoryEntry`
        """

        entry = SourcePackageRepositoryEntry.objects.create(
            repository=self,
            source_package=package,
            **kwargs,
        )
        return entry

    def has_source_package_name(self, source_package_name):
        """
        Checks whether this :class:`Repository` contains a source package with
        the given name.

        :param source_package_name: The name of the source package
        :type source_package_name: string

        :returns True: If it contains at least one version of the source package
            with the given name.
        :returns False: If it does not contain any version of the source package
            with the given name.
        """
        qs = self.source_packages.filter(
            source_package_name__name=source_package_name)
        return qs.exists()

    def has_source_package(self, source_package):
        """
        Checks whether this :class:`Repository` contains the given
        :class:`SourcePackage`.

        :returns True: If it does contain the given :class:`SourcePackage`
        :returns False: If it does not contain the given :class:`SourcePackage`
        """
        return self.source_packages.filter(id=source_package.id).exists()

    def has_binary_package(self, binary_package):
        """
        Checks whether this :class:`Repository` contains the given
        :class:`BinaryPackage`.

        :returns True: If it does contain the given :class:`SourcePackage`
        :returns False: If it does not contain the given :class:`SourcePackage`
        """
        qs = self.binary_entries.filter(binary_package=binary_package)
        return qs.exists()

    def add_binary_package(self, package, **kwargs):
        """
        The method adds a new class:`BinaryPackage` to the repository.

        :param package: The binary package to add to the repository
        :type package: :class:`BinaryPackage`

        The parameters needed for the corresponding
        :class:`BinaryPackageRepositoryEntry` should be in the keyword
        arguments.

        Returns the newly created :class:`BinaryPackageRepositoryEntry` for the
        given :class:`BinaryPackage`.

        :rtype: :class:`BinaryPackageRepositoryEntry`
        """
        return BinaryPackageRepositoryEntry.objects.create(
            repository=self,
            binary_package=package,
            **kwargs
        )

    @staticmethod
    def release_file_url(base_url, suite):
        """
        Returns the URL of the Release file for a repository with the given
        base URL and suite name.

        :param base_url: The base URL of the repository
        :type base_url: string

        :param suite: The name of the repository suite
        :type suite: string

        :rtype: string
        """
        base_url = base_url.rstrip('/')
        return base_url + '/dists/{suite}/Release'.format(
            suite=suite)

    def clean(self):
        """
        A custom model :meth:`clean <django.db.models.Model.clean>` method
        which enforces that only one :class:`Repository` can be set as the
        default.
        """
        super(Repository, self).clean()
        if self.default:
            # If this instance is not trying to set default to True, it is safe
            qs = Repository.objects.filter(default=True).exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "Only one repository can be set as the default")

    def is_development_repository(self):
        """Returns a boolean indicating whether the repository is used for
        development.

        A development repository is a repository where new
        versions of packages tend to be uploaded. The list of development
        repositories can be provided in the list
        DISTRO_TRACKER_DEVEL_REPOSITORIES (it should contain codenames and/or
        suite names). If that setting does not exist, then the default
        repository is assumed to be the only development repository.

        :rtype: bool
        """
        if hasattr(settings, 'DISTRO_TRACKER_DEVEL_REPOSITORIES'):
            for repo in settings.DISTRO_TRACKER_DEVEL_REPOSITORIES:
                if self.codename == repo or self.suite == repo:
                    return True
        else:
            return self.default
        return False

    def get_flags(self):
        """
        Returns a dict of existing flags and values. If no existing flag it
        returns the default value.
        """
        d = {}
        for flag, defvalue in RepositoryFlag.FLAG_DEFAULT_VALUES.items():
            d[flag] = defvalue
        for flag in self.flags.all():
            d[flag.name] = flag.value
        return d


class RepositoryFlag(models.Model):
    """
    Boolean options associated to repositories.
    """
    FLAG_NAMES = (
        ('hidden', 'Hidden repository'),
    )
    FLAG_DEFAULT_VALUES = {
        'hidden': False,
    }

    repository = models.ForeignKey(Repository, related_name='flags',
                                   on_delete=models.CASCADE)
    name = models.CharField(max_length=50, choices=FLAG_NAMES)
    value = models.BooleanField(default=False)

    class Meta:
        unique_together = ('repository', 'name')


class RepositoryRelation(models.Model):
    """
    Relations between two repositories. The relations are to be interpreted
    like "<repository> is a <relation> of <target_repository>".
    """
    RELATION_NAMES = (
        ('derivative', 'Derivative repository (target=parent)'),
        ('overlay', 'Overlay of target repository'),
    )

    repository = models.ForeignKey(Repository, related_name='relations',
                                   on_delete=models.CASCADE)
    name = models.CharField(max_length=50, choices=RELATION_NAMES)
    target_repository = models.ForeignKey(
        Repository, related_name='reverse_relations', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('repository', 'name')


class ContributorName(models.Model):
    """
    Represents a contributor.

    A single contributor, identified by email address, may have
    different written names in different contexts.
    """
    contributor_email = models.ForeignKey(UserEmail, on_delete=models.CASCADE)
    name = models.CharField(max_length=60, blank=True)

    class Meta:
        unique_together = ('contributor_email', 'name')

    @cached_property
    def email(self):
        return self.contributor_email.email

    def __str__(self):
        return "{name} <{email}>".format(
            name=self.name,
            email=self.contributor_email)

    def to_dict(self):
        """
        Returns a dictionary representing a :class:`ContributorName`
        instance.

        :rtype: dict
        """
        return {
            'name': self.name,
            'email': self.contributor_email.email,
        }


class SourcePackage(models.Model):
    """
    A model representing a single Debian source package.

    This means it holds any information regarding a (package_name, version)
    pair which is independent from the repository in which the package is
    found.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    source_package_name = models.ForeignKey(
        SourcePackageName,
        related_name='source_package_versions',
        on_delete=models.CASCADE)
    version = models.CharField(max_length=200)

    standards_version = models.CharField(max_length=550, blank=True)
    architectures = models.ManyToManyField(Architecture, blank=True)
    binary_packages = models.ManyToManyField(BinaryPackageName, blank=True)

    maintainer = models.ForeignKey(
        ContributorName,
        related_name='source_package',
        null=True,
        on_delete=models.CASCADE)
    uploaders = models.ManyToManyField(
        ContributorName,
        related_name='source_packages_uploads_set'
    )

    dsc_file_name = models.CharField(max_length=255, blank=True)
    directory = models.CharField(max_length=255, blank=True)
    homepage = models.URLField(max_length=255, blank=True)
    vcs = JSONField()

    class Meta:
        unique_together = ('source_package_name', 'version')

    def __str__(self):
        return '{pkg}, version {ver}'.format(
            pkg=self.source_package_name, ver=self.version)

    @cached_property
    def name(self):
        """
        A convenience property returning the name of the package as a string.

        :rtype: string
        """
        return self.source_package_name.name

    @cached_property
    def main_entry(self):
        """
        Returns the
        :class:`SourcePackageRepositoryEntry
        <distro_tracker.core.models.SourcePackageRepositoryEntry>`
        found in the instance's :attr:`repository_entries` which should be
        considered the main entry for this version.

        If the version is found in the default repository, the entry for the
        default repository is returned.

        Otherwise, the entry for the repository with the highest
        :attr:`position <distro_tracker.core.models.Repository.position>`
        field is returned.

        If the source package version is not found in any repository,
        ``None`` is returned.
        """
        default_repository_entry_qs = self.repository_entries.filter(
            repository__default=True)
        try:
            return default_repository_entry_qs[0]
        except IndexError:
            pass

        # Return the entry in the repository with the highest position number
        try:
            return self.repository_entries.order_by('-repository__position')[0]
        except IndexError:
            return None

    def get_changelog_entry(self):
        """
        Retrieve the changelog entry which corresponds to this package version.

        If there is no changelog associated with the version returns ``None``

        :rtype: :class:`string` or ``None``
        """
        # If there is no changelog, return immediately
        try:
            extracted_changelog = \
                self.extracted_source_files.get(name='changelog')
        except ExtractedSourceFile.DoesNotExist:
            return

        extracted_changelog.extracted_file.open()
        # Let the File context manager close the file
        with extracted_changelog.extracted_file as changelog_file:
            changelog_content = changelog_file.read()

        changelog = debian_changelog.Changelog(changelog_content.splitlines())
        # Return the entry corresponding to the package version, or ``None``
        return next((
            force_text(entry).strip()
            for entry in changelog
            if entry.version == self.version),
            None)

    def update(self, **kwargs):
        """
        The method updates all of the instance attributes based on the keyword
        arguments.

        >>> src_pkg = SourcePackage()
        >>> src_pkg.update(version='1.0.0', homepage='http://example.com')
        >>> str(src_pkg.version)
        '1.0.0'
        >>> str(src_pkg.homepage)
        'http://example.com'
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                attr = getattr(self, key)
                if hasattr(attr, 'set'):
                    attr.set(value)
                else:
                    setattr(self, key, value)


class BinaryPackage(models.Model):
    """
    The method represents a particular binary package.

    All information regarding a (binary-package-name, version) which is
    independent from the repository in which the package is found.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    binary_package_name = models.ForeignKey(
        BinaryPackageName,
        related_name='binary_package_versions',
        on_delete=models.CASCADE
    )
    version = models.CharField(max_length=200)
    source_package = models.ForeignKey(SourcePackage, on_delete=models.CASCADE)

    short_description = models.CharField(max_length=300, blank=True)
    long_description = models.TextField(blank=True)

    class Meta:
        unique_together = ('binary_package_name', 'version')

    def __str__(self):
        return 'Binary package {pkg}, version {ver}'.format(
            pkg=self.binary_package_name, ver=self.version)

    def update(self, **kwargs):
        """
        The method updates all of the instance attributes based on the keyword
        arguments.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @cached_property
    def name(self):
        """Returns the name of the package"""
        return self.binary_package_name.name


class BinaryPackageRepositoryEntryManager(models.Manager):
    def filter_by_package_name(self, names):
        """
        :returns: A set of :class:`BinaryPackageRepositoryEntry` instances
            which are associated to a binary package with one of the names
            given in the ``names`` parameter.
        :rtype: :class:`QuerySet <django.db.models.query.QuerySet>`
        """
        return self.filter(binary_package__binary_package_name__name__in=names)


class BinaryPackageRepositoryEntry(models.Model):
    """
    A model representing repository specific information for a given binary
    package.

    It links a :class:`BinaryPackage` instance with the :class:`Repository`
    instance.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    binary_package = models.ForeignKey(
        BinaryPackage,
        related_name='repository_entries',
        on_delete=models.CASCADE,
    )
    repository = models.ForeignKey(
        Repository,
        related_name='binary_entries',
        on_delete=models.CASCADE,
    )
    architecture = models.ForeignKey(Architecture, on_delete=models.CASCADE)

    priority = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=50, blank=True)

    objects = BinaryPackageRepositoryEntryManager()

    class Meta:
        unique_together = ('binary_package', 'repository', 'architecture')

    def __str__(self):
        return '{pkg} ({arch}) in the repository {repo}'.format(
            pkg=self.binary_package, arch=self.architecture,
            repo=self.repository)

    @property
    def name(self):
        """The name of the binary package"""
        return self.binary_package.name

    @cached_property
    def version(self):
        """The version of the binary package"""
        return self.binary_package.version


class SourcePackageRepositoryEntryManager(models.Manager):
    def filter_by_package_name(self, names):
        """
        :returns: A set of :class:`SourcePackageRepositoryEntry` instances
            which are associated to a source package with one of the names
            given in the ``names`` parameter.
        :rtype: :class:`QuerySet <django.db.models.query.QuerySet>`
        """
        return self.filter(source_package__source_package_name__name__in=names)


class SourcePackageRepositoryEntry(models.Model):
    """
    A model representing source package data that is repository specific.

    It links a :class:`SourcePackage` instance with the :class:`Repository`
    instance.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    source_package = models.ForeignKey(
        SourcePackage,
        related_name='repository_entries',
        on_delete=models.CASCADE,
    )
    repository = models.ForeignKey(Repository, related_name='source_entries',
                                   on_delete=models.CASCADE)

    component = models.CharField(max_length=50, blank=True)

    objects = SourcePackageRepositoryEntryManager()

    class Meta:
        unique_together = ('source_package', 'repository')

    def __str__(self):
        return "Source package {pkg} in the repository {repo}".format(
            pkg=self.source_package,
            repo=self.repository)

    @property
    def dsc_file_url(self):
        """
        Returns the URL where the .dsc file of this entry can be found.

        :rtype: string
        """
        if self.source_package.directory and self.source_package.dsc_file_name:
            base_url = self.repository.public_uri.rstrip('/') or \
                self.repository.uri.rstrip('/')
            return '/'.join((
                base_url,
                self.source_package.directory,
                self.source_package.dsc_file_name,
            ))
        else:
            return None

    @property
    def directory_url(self):
        """
        Returns the URL of the package's directory.

        :rtype: string
        """
        if self.source_package.directory:
            base_url = self.repository.public_uri.rstrip('/') or \
                self.repository.uri.rstrip('/')
            return base_url + '/' + self.source_package.directory
        else:
            return None

    @property
    def name(self):
        """The name of the source package"""
        return self.source_package.name

    @cached_property
    def version(self):
        """
        Returns the version of the associated source package.
        """
        return self.source_package.version


def _extracted_source_file_upload_path(instance, filename):
    return '/'.join((
        'packages',
        package_hashdir(instance.source_package.name),
        instance.source_package.name,
        os.path.basename(filename) + '-' + instance.source_package.version
    ))


class ExtractedSourceFile(models.Model):
    """
    Model representing a single file extracted from a source package archive.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    source_package = models.ForeignKey(
        SourcePackage,
        related_name='extracted_source_files',
        on_delete=models.CASCADE)
    extracted_file = models.FileField(
        upload_to=_extracted_source_file_upload_path)
    name = models.CharField(max_length=100)
    date_extracted = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('source_package', 'name')

    def __str__(self):
        return 'Extracted file {extracted_file} of package {package}'.format(
            extracted_file=self.extracted_file, package=self.source_package)


class PackageData(models.Model):
    """
    A model representing a quasi key-value store for package information
    extracted from other models in order to speed up its rendering on
    Web pages.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    package = models.ForeignKey(PackageName,
                                on_delete=models.CASCADE,
                                related_name="data")
    key = models.CharField(max_length=50)
    value = JSONField()

    def __str__(self):
        return '{key}: {value} for package {package}'.format(
            key=self.key, value=self.value, package=self.package)

    class Meta:
        unique_together = ('key', 'package')


class MailingListManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`MailingList` class.
    """
    def get_by_email(self, email):
        """
        Returns a :class:`MailingList` instance which matches the given email.
        This means that the email's domain matches exactly the MailingList's
        domain field.
        """
        if '@' not in email:
            return None
        domain = email.rsplit('@', 1)[1]

        qs = self.filter(domain=domain)
        if qs.exists():
            return qs[0]
        else:
            return None


def validate_archive_url_template(value):
    """
    Custom validator for :class:`MailingList`'s
    :attr:`archive_url_template <MailingList.archive_url_template>` field.

    :raises ValidationError: If there is no {user} parameter in the value.
    """
    if '{user}' not in value:
        raise ValidationError(
            "The archive URL template must have a {user} parameter")


class MailingList(models.Model):
    """
    Describes a known mailing list.

    This provides Distro Tracker users to define the known mailing lists
    through the admin panel in order to support displaying their archives in the
    package pages without modifying any code.

    Instances should have the :attr:`archive_url_template` field set to the
    template which archive URLs should follow where a mandatory parameter is
    {user}.
    """

    name = models.CharField(max_length=100)
    domain = models.CharField(max_length=255, unique=True)
    archive_url_template = models.CharField(max_length=255, validators=[
        validate_archive_url_template,
    ])

    objects = MailingListManager()

    def __str__(self):
        return self.name

    def archive_url(self, user):
        """
        Returns the archive URL for the given user.

        :param user: The user for whom the archive URL should be returned
        :type user: string

        :rtype: string
        """
        return self.archive_url_template.format(user=user)

    def archive_url_for_email(self, email):
        """
        Returns the archive URL for the given email.

        Similar to :meth:`archive_url`, but extracts the user name from the
        email first.

        :param email: The email of the user for whom the archive URL should be
            returned
        :type user: string

        :rtype: string
        """
        if '@' not in email:
            return None
        user, domain = email.rsplit('@', 1)

        if domain != self.domain:
            return None

        return self.archive_url(user)


class NewsManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`News` model.
    """
    def create(self, **kwargs):
        """
        Overrides the default create method to allow for easier creation of
        News with different content backing (DB or file).

        If there is a ``content`` parameter in the kwargs, the news content is
        saved to the database.

        If there is a ``file_content`` parameter in the kwargs, the news content
        is saved to a file.

        If none of those parameters are given, the method works as expected.
        """
        if 'content' in kwargs:
            db_content = kwargs.pop('content')
            kwargs['_db_content'] = db_content
        if 'file_content' in kwargs:
            file_content = kwargs.pop('file_content')
            kwargs['news_file'] = ContentFile(file_content, name='news-file')

        return super(NewsManager, self).create(**kwargs)


def news_upload_path(instance, filename):
    """Compute the path where to store a news."""
    return '/'.join((
        'news',
        package_hashdir(instance.package.name),
        instance.package.name,
        filename
    ))


class News(models.Model):
    """
    A model used to describe a news item regarding a package.
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    package = models.ForeignKey(PackageName, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, default='text/plain')
    _db_content = models.TextField(blank=True, null=True)
    news_file = models.FileField(upload_to=news_upload_path, blank=True)
    created_by = models.CharField(max_length=100, blank=True)
    datetime_created = models.DateTimeField(auto_now_add=True)
    signed_by = models.ManyToManyField(
        ContributorName,
        related_name='signed_news_set')

    objects = NewsManager()

    def __str__(self):
        return self.title

    @cached_property
    def content(self):
        """
        Returns either the content of the message saved in the database or
        retrieves it from the news file found in the filesystem.

        The property is cached so that a single instance of :class:`News` does
        not have to read a file every time its content is accessed.
        """
        if self._db_content:
            return self._db_content
        elif self.news_file:
            self.news_file.open('rb')
            content = self.news_file.read()
            self.news_file.close()
            return content

    def save(self, *args, **kwargs):
        super(News, self).save(*args, **kwargs)

        signers = verify_signature(self.get_signed_content())
        if signers is None:
            # No signature
            return

        signed_by = []
        for name, email in signers:
            try:
                signer_email, _ = UserEmail.objects.get_or_create(
                    email=email)
                signer_name, _ = ContributorName.objects.get_or_create(
                    name=name,
                    contributor_email=signer_email)
                signed_by.append(signer_name)
            except ValidationError:
                logger_input.warning('News "%s" has signature with '
                                     'invalid email (%s).', self.title, email)

        self.signed_by.set(signed_by)

    def get_signed_content(self):
        return self.content

    def get_absolute_url(self):
        return reverse('dtracker-news-page', kwargs={
            'news_id': self.pk,
            'slug': slugify(self.title)
        })


class EmailNewsManager(NewsManager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`EmailNews` model.
    """
    def create_email_news(self, message, package, **kwargs):
        """
        The method creates a news item from the given email message.

        If a title of the message is not given, it automatically generates it
        based on the sender of the email.

        :param message: The message based on which a news item should be
            created.
        :type message: :class:`Message <email.message.Message>`
        :param package: The package to which the news item refers
        :type: :class:`PackageName`
        """
        create_kwargs = EmailNews.get_email_news_parameters(message)
        # The parameters given to the method directly by the client have
        # priority over what is extracted from the email message.
        create_kwargs.update(kwargs)

        return self.create(package=package, **create_kwargs)

    def get_queryset(self):
        return super(EmailNewsManager, self).get_queryset().filter(
            content_type='message/rfc822')


class EmailNews(News):
    objects = EmailNewsManager()

    class Meta:
        proxy = True

    def get_signed_content(self):
        msg = message_from_bytes(self.content)
        return get_decoded_message_payload(msg)

    @staticmethod
    def get_email_news_parameters(message):
        """
        Returns a dict representing default values for some :class:`EmailNews`
        fields based on the given email message.
        """
        kwargs = {}
        from_email = decode_header(message.get('From', 'unknown'))

        kwargs['created_by'], _ = parseaddr(from_email)
        if 'Subject' in message:
            kwargs['title'] = decode_header(message['Subject'])
        else:
            kwargs['title'] = \
                'Email news from {sender}'.format(sender=from_email)
        if hasattr(message, 'as_bytes'):
            kwargs['file_content'] = message.as_bytes()
        else:
            kwargs['file_content'] = message.as_string()
        kwargs['content_type'] = 'message/rfc822'

        return kwargs


class NewsRenderer(metaclass=PluginRegistry):
    """
    Base class which is used to register subclasses to render a :class:`News`
    instance's contents into an HTML page.

    Each :class:`News` instance has a :attr:`News.content_type` field which
    is used to select the correct renderer for its type.
    """
    #: Each :class:`NewsRenderer` subclass sets a content type that it can
    #: render into HTML
    content_type = None
    #: A renderer can define a template name which will be included when its
    #: output is required
    template_name = None

    #: The context is made available to the renderer's template, if available.
    #: By default this is only the news instance which should be rendered.
    @property
    def context(self):
        return {
            'news': self.news
        }
    #: Pure HTML which is included when the renderer's output is required.
    #: Must be marked safe with :func:`django.utils.safestring.mark_safe`
    #: or else it will be HTML encoded!
    html_output = None

    def __init__(self, news):
        """
        :type news: :class:`distro_tracker.core.models.News`
        """
        self.news = news

    @classmethod
    def get_renderer_for_content_type(cls, content_type):
        """
        Returns one of the :class:`NewsRenderer` subclasses which implements
        rendering the given content type. If there is more than one such class,
        it is undefined which one is returned from this method. If there is
        not renderer for the given type, ``None`` is returned.

        :param content_type: The Content-Type for which a renderer class should
            be returned.
        :type content_type: string

        :rtype: :class:`NewsRenderer` subclass or ``None``
        """
        for news_renderer in cls.plugins:
            if news_renderer.content_type == content_type:
                return news_renderer

        return None

    def render_to_string(self):
        """
        :returns: A safe string representing the rendered HTML output.
        """
        if self.template_name:
            return mark_safe(distro_tracker_render_to_string(
                self.template_name,
                {'ctx': self.context, }))
        elif self.html_output:
            return mark_safe(self.html_output)
        else:
            return ''


class PlainTextNewsRenderer(NewsRenderer):
    """
    Renders a text/plain content type by placing the text in a <pre> HTML block
    """
    content_type = 'text/plain'
    template_name = 'core/news-plain.html'


class HtmlNewsRenderer(NewsRenderer):
    """
    Renders a text/html content type by simply emitting it to the output.

    When creating news with a text/html type, you must be careful to properly
    santize any user-provided data or risk security vulnerabilities.
    """
    content_type = 'text/html'

    @property
    def html_output(self):
        return mark_safe(self.news.content)


class EmailNewsRenderer(NewsRenderer):
    """
    Renders news content as an email message.
    """
    content_type = 'message/rfc822'
    template_name = 'core/news-email.html'

    @cached_property
    def context(self):
        msg = message_from_bytes(self.news.content)
        # Extract headers first
        DEFAULT_HEADERS = (
            'From',
            'To',
            'Subject',
        )
        EMAIL_HEADERS = (
            'from',
            'to',
            'cc',
            'bcc',
            'resent-from',
            'resent-to',
            'resent-cc',
            'resent-bcc',
        )
        USER_DEFINED_HEADERS = getattr(settings,
                                       'DISTRO_TRACKER_EMAIL_NEWS_HEADERS', ())
        ALL_HEADERS = [
            header.lower()
            for header in DEFAULT_HEADERS + USER_DEFINED_HEADERS
        ]

        headers = {}
        for header_name, header_value in msg.items():
            if header_name.lower() not in ALL_HEADERS:
                continue
            header_value = decode_header(header_value)
            if header_name.lower() in EMAIL_HEADERS:
                headers[header_name] = {
                    'emails': [
                        {
                            'email': email,
                            'name': name,
                        }
                        for name, email in getaddresses([header_value])
                    ]
                }
                if header_name.lower() == 'from':
                    from_name = headers[header_name]['emails'][0]['name']
            else:
                headers[header_name] = {'value': header_value}

        signers = list(self.news.signed_by.select_related())
        if signers and signers[0].name == from_name:
            signers = []

        plain_text_payloads = []
        for part in typed_subpart_iterator(msg, 'text', 'plain'):
            message = linkify(escape(get_decoded_message_payload(part)))
            plain_text_payloads.append(message)

        return {
            'headers': headers,
            'parts': plain_text_payloads,
            'signed_by': signers,
        }


class PackageBugStats(models.Model):
    """
    Model for bug statistics of source and pseudo packages (packages modelled
    by the :class:`PackageName` model).
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    package = models.OneToOneField(PackageName, related_name='bug_stats',
                                   on_delete=models.CASCADE)
    stats = JSONField(blank=True)

    def __str__(self):
        return '{package} bug stats: {stats}'.format(
            package=self.package, stats=self.stats)


class BinaryPackageBugStats(models.Model):
    """
    Model for bug statistics of binary packages (:class:`BinaryPackageName`).
    """
    id = models.BigAutoField(primary_key=True)  # noqa
    package = models.OneToOneField(BinaryPackageName,
                                   related_name='binary_bug_stats',
                                   on_delete=models.CASCADE)
    stats = JSONField(blank=True)

    def __str__(self):
        return '{package} bug stats: {stats}'.format(
            package=self.package, stats=self.stats)


class ActionItemTypeManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`ActionItemType` model.
    """
    def create_or_update(self, type_name, full_description_template):
        """
        Method either creates the template with the given name and description
        template or makes sure to update an existing instance of that name
        to have the given template.

        :param type_name: The name of the :class:`ActionItemType` instance to
            create.
        :type type_name: string
        :param full_description_template: The description template that the
            returned :class:`ActionItemType` instance should have.
        :type full_description_template: string

        :returns: :class:`ActionItemType` instance
        """
        item_type, created = self.get_or_create(type_name=type_name, defaults={
            'full_description_template': full_description_template
        })
        if created:
            return item_type
        # If it wasn't just created check if the template needs to be updated
        if item_type.full_description_template != full_description_template:
            item_type.full_description_template = full_description_template
            item_type.save()

        return item_type


class ActionItemType(models.Model):
    type_name = models.TextField(max_length=100, unique=True)
    full_description_template = models.CharField(
        max_length=255, blank=True, null=True)

    objects = ActionItemTypeManager()

    def __str__(self):
        return self.type_name


class ActionItemManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`ActionItem` model.
    """
    def delete_obsolete_items(self, item_types, non_obsolete_packages):
        """
        The method removes :class:`ActionItem` instances which have one of the
        given types and are not associated to one of the non obsolete packages.

        :param item_types: A list of action item types to be considered for
            removal.
        :type item_types: list of :class:`ActionItemType` instances
        :param non_obsolete_packages: A list of package names whose items are
            not to be removed.
        :type non_obsolete_packages: list of strings
        """
        if len(item_types) == 1:
            qs = self.filter(item_type=item_types[0])
        else:
            qs = self.filter(item_type__in=item_types)
        qs = qs.exclude(package__name__in=non_obsolete_packages)
        qs.delete()


class ActionItem(models.Model):
    """
    Model for entries of the "action needed" panel.
    """
    #: All available severity levels
    SEVERITY_WISHLIST = 0
    SEVERITY_LOW = 1
    SEVERITY_NORMAL = 2
    SEVERITY_HIGH = 3
    SEVERITY_CRITICAL = 4
    SEVERITIES = (
        (SEVERITY_WISHLIST, 'wishlist'),
        (SEVERITY_LOW, 'low'),
        (SEVERITY_NORMAL, 'normal'),
        (SEVERITY_HIGH, 'high'),
        (SEVERITY_CRITICAL, 'critical'),
    )
    id = models.BigAutoField(primary_key=True)  # noqa
    package = models.ForeignKey(PackageName, related_name='action_items',
                                on_delete=models.CASCADE)
    item_type = models.ForeignKey(ActionItemType, related_name='action_items',
                                  on_delete=models.CASCADE)
    short_description = models.TextField()
    severity = models.IntegerField(choices=SEVERITIES, default=SEVERITY_NORMAL)
    created_timestamp = models.DateTimeField(auto_now_add=True)
    last_updated_timestamp = models.DateTimeField(auto_now=True)
    extra_data = JSONField(blank=True, null=True)

    objects = ActionItemManager()

    class Meta:
        unique_together = ('package', 'item_type')

    def __str__(self):
        return '{package} - {desc} ({severity})'.format(
            package=self.package,
            desc=self.short_description,
            severity=self.get_severity_display())

    def get_absolute_url(self):
        return reverse('dtracker-action-item', kwargs={
            'item_pk': self.pk,
        })

    @property
    def type_name(self):
        return self.item_type.type_name

    @property
    def full_description_template(self):
        return self.item_type.full_description_template

    @cached_property
    def full_description(self):
        if not self.full_description_template:
            return ''
        try:
            return mark_safe(
                distro_tracker_render_to_string(
                    self.full_description_template,
                    {'item': self, }))
        except TemplateDoesNotExist:
            return ''

    def to_dict(self):
        return {
            'short_description': self.short_description,
            'package': {
                'name': self.package.name,
                'id': self.package.id,
            },
            'type_name': self.item_type.type_name,
            'full_description': self.full_description,
            'severity': {
                'name': self.get_severity_display(),
                'level': self.severity,
                'label_type': {
                    0: 'info',
                    3: 'warning',
                    4: 'danger',
                }.get(self.severity, 'default')
            },
            'created': self.created_timestamp.strftime('%Y-%m-%d'),
            'updated': self.last_updated_timestamp.strftime('%Y-%m-%d'),
        }


class ConfirmationException(Exception):
    """
    An exception which is raised when the :py:class:`ConfirmationManager`
    is unable to generate a unique key for a given identifier.
    """
    pass


class ConfirmationManager(models.Manager):
    """
    A custom manager for the :py:class:`Confirmation` model.
    """
    def generate_key(self, identifier):
        """
        Generates a random key for the given identifier.

        :param identifier: A string representation of an identifier for the
            confirmation instance.
        """
        chars = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(chars) for _ in range(16))
        random_string = random_string.encode('ascii')
        salt = hashlib.sha1(random_string).hexdigest()
        hash_input = (salt + identifier).encode('ascii')
        return hashlib.sha1(hash_input).hexdigest()

    def create_confirmation(self, identifier='', **kwargs):
        """
        Creates a :py:class:`Confirmation` object with the given identifier and
        all the given keyword arguments passed.

        :param identifier: A string representation of an identifier for the
            confirmation instance.
        :raises distro_tracker.mail.models.ConfirmationException: If it is
            unable to generate a unique key.
        """
        MAX_TRIES = 10
        errors = 0
        while errors < MAX_TRIES:
            confirmation_key = self.generate_key(identifier)
            try:
                return self.create(confirmation_key=confirmation_key, **kwargs)
            except IntegrityError:
                errors += 1

        raise ConfirmationException(
            'Unable to generate a confirmation key for {identifier}'.format(
                identifier=identifier))

    def clean_up_expired(self):
        """
        Removes all expired confirmation keys.
        """
        for confirmation in self.all():
            if confirmation.is_expired():
                confirmation.delete()

    def get(self, *args, **kwargs):
        """
        Overrides the default :py:class:`django.db.models.Manager` method so
        that expired :py:class:`Confirmation` instances are never
        returned.

        :rtype: :py:class:`Confirmation` or ``None``
        """
        instance = super(ConfirmationManager, self).get(*args, **kwargs)
        return instance if not instance.is_expired() else None


class Confirmation(models.Model):
    """
    An abstract model allowing its subclasses to store and create confirmation
    keys.
    """
    confirmation_key = models.CharField(max_length=40, unique=True)
    date_created = models.DateTimeField(auto_now_add=True)

    objects = ConfirmationManager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.confirmation_key

    def is_expired(self):
        """
        :returns True: if the confirmation key has expired
        :returns False: if the confirmation key is still valid
        """
        delta = timezone.now() - self.date_created
        return delta.days >= DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS


class SourcePackageDeps(models.Model):
    id = models.BigAutoField(primary_key=True)  # noqa
    source = models.ForeignKey(SourcePackageName,
                               related_name='source_dependencies',
                               on_delete=models.CASCADE)
    dependency = models.ForeignKey(SourcePackageName,
                                   related_name='source_dependents',
                                   on_delete=models.CASCADE)
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    build_dep = models.BooleanField(default=False)
    binary_dep = models.BooleanField(default=False)
    details = JSONField()

    class Meta:
        unique_together = ('source', 'dependency', 'repository')

    def __str__(self):
        return '{} depends on {}'.format(self.source, self.dependency)


class TeamManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`Team` model.
    """
    def create_with_slug(self, **kwargs):
        """
        A variant of the create method which automatically populates the
        instance's slug field by slugifying the name.
        """
        if 'slug' not in kwargs:
            kwargs['slug'] = slugify(kwargs['name'])
        if 'maintainer_email' in kwargs:
            if not isinstance(kwargs['maintainer_email'], UserEmail):
                kwargs['maintainer_email'] = UserEmail.objects.get_or_create(
                    email=kwargs['maintainer_email'])[0]

        return self.create(**kwargs)


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(
        unique=True,
        verbose_name='Identifier',
        help_text='Used in the URL (/teams/<em>identifier</em>/) and in the '
                  'associated email address '
                  'team+<em>identifier</em>@<em>domain</em>.',
    )
    maintainer_email = models.ForeignKey(
        UserEmail,
        null=True,
        blank=True,
        on_delete=models.SET_NULL)
    description = models.TextField(blank=True, null=True)
    url = models.URLField(max_length=255, blank=True, null=True)
    public = models.BooleanField(default=True)

    owner = models.ForeignKey(
        'accounts.User',
        null=True,
        on_delete=models.SET_NULL,
        related_name='owned_teams')

    packages = models.ManyToManyField(
        PackageName,
        related_name='teams')
    members = models.ManyToManyField(
        UserEmail,
        related_name='teams',
        through='TeamMembership')

    objects = TeamManager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('dtracker-team-page', kwargs={
            'slug': self.slug,
        })

    def add_members(self, users, muted=False):
        """
        Adds the given users to the team.

        It automatically creates the intermediary :class:`TeamMembership`
        models.

        :param users: The users to be added to the team.
        :type users: an ``iterable`` of :class:`UserEmail` instances

        :param muted: If set to True, the membership will be muted before the
            user excplicitely unmutes it.
        :type active: bool

        :returns: :class:`TeamMembership` instances for each user added to
            the team
        :rtype: list
        """
        users = [
            user
            if isinstance(user, UserEmail) else
            UserEmail.objects.get_or_create(email=user)[0]
            for user in users
        ]
        return [
            self.team_membership_set.create(user_email=user, muted=muted)
            for user in users
        ]

    def remove_members(self, users):
        """
        Removes the given users from the team.

        :param users: The users to be removed from the team.
        :type users: an ``iterable`` of :class:`UserEmail` instances
        """
        self.team_membership_set.filter(user_email__in=users).delete()

    def user_is_member(self, user):
        """
        Checks whether the given user is a member of the team.
        :param user: The user which should be checked for membership
        :type user: :class:`distro_tracker.accounts.models.User`
        """
        return (
            user == self.owner or
            self.members.filter(pk__in=user.emails.all()).exists()
        )


class TeamMembership(models.Model):
    """
    Represents the intermediary model for the many-to-many association of
    team members to a :class:`Team`.
    """
    user_email = models.ForeignKey(UserEmail, related_name='membership_set',
                                   on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name='team_membership_set',
                             on_delete=models.CASCADE)

    muted = models.BooleanField(default=False)
    default_keywords = models.ManyToManyField(Keyword)
    has_membership_keywords = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user_email', 'team')

    def __str__(self):
        return '{} member of {}'.format(self.user_email, self.team)

    def is_muted(self, package_name):
        """
        Checks if the given package is muted in the team membership.
        A package is muted if the team membership itself is muted as a whole or
        if :class:`MembershipPackageSpecifics` for the package indicates that
        the package is muted.

        :param package_name: The name of the package.
        :type package_name: :class:`PackageName` or :class:`str`
        """
        if not isinstance(package_name, PackageName):
            package_name = get_or_none(PackageName, name=package_name)
        if self.muted:
            return True
        try:
            package_specifics = self.membership_package_specifics.get(
                package_name=package_name)
        except MembershipPackageSpecifics.DoesNotExist:
            return False

        return package_specifics.muted

    def set_mute_package(self, package_name, mute):
        """
        Sets whether the given package should be considered muted for the team
        membership.
        """
        if not isinstance(package_name, PackageName):
            package_name = PackageName.objects.get(package_name)
        package_specifics, _ = self.membership_package_specifics.get_or_create(
            package_name=package_name)
        package_specifics.muted = mute
        package_specifics.save()

    def mute_package(self, package_name):
        """
        The method mutes only the given package in the user's team membership.

        :param package_name: The name of the package.
        :type package_name: :class:`PackageName` or :class:`str`
        """
        self.set_mute_package(package_name, True)

    def unmute_package(self, package_name):
        """
        The method unmutes only the given package in the user's team membership.

        :param package_name: The name of the package.
        :type package_name: :class:`PackageName` or :class:`str`
        """
        self.set_mute_package(package_name, False)

    def set_keywords(self, package_name, keywords):
        """
        Sets the membership-specific keywords for the given package.

        :param package_name: The name of the package for which the keywords
            should be set
        :type package_name: :class:`PackageName` or :class:`str`
        :param keywords: The keywords to be set for the membership-specific
            keywords for the given package.
        :type keywords: an ``iterable`` of keyword names - as strings
        """
        if not isinstance(package_name, PackageName):
            package_name = PackageName.objects.get(package_name)
        new_keywords = Keyword.objects.filter(name__in=keywords)
        membership_package_specifics, _ = (
            self.membership_package_specifics.get_or_create(
                package_name=package_name))
        membership_package_specifics.set_keywords(new_keywords)

    def set_membership_keywords(self, keywords):
        """
        Sets the membership default keywords.

        :param keywords: The keywords to be set for the membership
        :type keywords: an ``iterable`` of keyword names - as strings
        """
        new_keywords = Keyword.objects.filter(name__in=keywords)
        self.default_keywords.set(new_keywords)
        self.has_membership_keywords = True
        self.save()

    def get_membership_keywords(self):
        if self.has_membership_keywords:
            return self.default_keywords.order_by('name')
        else:
            return self.user_email.emailsettings.default_keywords.order_by(
                'name')

    def get_keywords(self, package_name):
        """
        Returns the keywords that are associated to a particular package of
        this team membership.

        The first set of keywords that exists in the order given below is
        returned:

        - Membership package-specific keywords
        - Membership default keywords
        - UserEmail default keywords

        :param package_name: The name of the package for which the keywords
            should be returned
        :type package_name: :class:`PackageName` or :class:`str`

        :return: The keywords which should be used when forwarding mail
            regarding the given package to the given user for the team
            membership.
        :rtype: :class:`QuerySet <django.db.models.query.QuerySet>` of
            :class:`Keyword` instances.
        """
        if not isinstance(package_name, PackageName):
            package_name = get_or_none(PackageName, name=package_name)

        try:
            membership_package_specifics = \
                self.membership_package_specifics.get(
                    package_name=package_name)
            if membership_package_specifics._has_keywords:
                return membership_package_specifics.keywords.all()
        except MembershipPackageSpecifics.DoesNotExist:
            pass

        if self.has_membership_keywords:
            return self.default_keywords.all()

        email_settings, _ = \
            EmailSettings.objects.get_or_create(user_email=self.user_email)
        return email_settings.default_keywords.all()


class MembershipPackageSpecifics(models.Model):
    """
    Represents a model for keeping information regarding a pair of
    (membership, package) instances.
    """
    membership = models.ForeignKey(
        TeamMembership,
        related_name='membership_package_specifics',
        on_delete=models.CASCADE)
    package_name = models.ForeignKey(PackageName, on_delete=models.CASCADE)

    keywords = models.ManyToManyField(Keyword)
    _has_keywords = models.BooleanField(default=False)

    muted = models.BooleanField(default=False)

    class Meta:
        unique_together = ('membership', 'package_name')

    def __str__(self):
        return "Membership ({}) specific keywords for {} package".format(
            self.membership, self.package_name)

    def set_keywords(self, keywords):
        self.keywords.set(keywords)
        self._has_keywords = True
        self.save()


class MembershipConfirmation(Confirmation):
    membership = models.ForeignKey(TeamMembership, on_delete=models.CASCADE)

    def __str__(self):
        return "Confirmation for {}".format(self.membership)


class BugDisplayManager(object):
    """
    A class that aims at implementing the logic to handle the multiple ways
    of displaying bugs data. More specifically, it defines the logic for:
    * rendering :class:`BugsPanel <distro_tracker.core.panels.BugsPanel>`
    * rendering :class:`BugStatsTableField
    <distro_tracker.core.package_tables.BugStatsTableField>`
    """
    table_field_template_name = 'core/package-table-fields/bugs.html'
    panel_template_name = 'core/panels/bugs.html'

    def table_field_context(self, package):
        """
        This function is used by the
        :class:`BugStatsTableField
        <distro_tracker.core.package_tables.BugStatsTableField>`
        to display the bug information for packages in tables.

        It should return a dict with the following keys:

        * ``bugs`` - a list of dicts where each element describes a single
          bug category for the given package. Each dict has to provide at
          minimum the following keys:

          * ``category_name`` - the name of the bug category
          * ``bug_count`` - the number of known bugs for the given package and
            category

        * ``all`` - the total number of bugs for that package
        """
        stats = {}
        try:
            stats['bugs'] = package.bug_stats.stats
        except ObjectDoesNotExist:
            stats['bugs'] = []

        # Also adds a total of all those bugs
        total = sum(category['bug_count'] for category in stats['bugs'])
        stats['all'] = total

        return stats

    def panel_context(self, package):
        """
        This function is used by the
        :class:`BugsPanel <distro_tracker.core.panels.BugsPanel>`
        to display the bug information for a given package.

        It should return a list of dicts where each element describes a
        single bug category for the given package. Each dict has to provide at
        minimum the following keys:

        * ``category_name``: the name of the bug category
        * ``bug_count``: the number of known bugs for the given package and
          category
        """
        try:
            stats = package.bug_stats.stats
        except ObjectDoesNotExist:
            return

        # Also adds a total of all those bugs
        total = sum(category['bug_count'] for category in stats)
        stats.insert(0, {
            'category_name': 'all',
            'bug_count': total,
        })
        return stats

    def get_bug_tracker_url(self, package_name, package_type, category_name):
        pass

    def get_binary_bug_stats(self, binary_name):
        """
        This function is used by the
        :class:`BinariesInformationPanel
        <distro_tracker.core.panels.BinariesInformationPanel>`
        to display the bug information next to the binary name.

        It should return a list of dicts where each element describes a single
        bug category for the given package.

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
        stats = get_or_none(
            BinaryPackageBugStats, package__name=binary_name)
        if stats is not None:
            return stats.stats

        return


class BugDisplayManagerMixin(object):
    """
    Mixin to another class to provide access to an object of class
    :class:`BugDisplayManager <distro_tracker.core.models.BugDisplayManager>`.
    """
    @property
    def bug_manager(self):
        """
        This function returns the appropriate class for managing
        the presentation of bugs data.
        """
        if not hasattr(self, '_bug_class'):
            bug_manager_class, implemented = vendor.call(
                'get_bug_display_manager_class')
            if implemented:
                self._bug_manager = bug_manager_class()
            else:
                self._bug_manager = BugDisplayManager()
        return self._bug_manager


class TaskData(models.Model):
    """
    Stores runtime data about tasks to help schedule them and store
    list of things to process once they have been identified.
    """
    task_name = models.CharField(max_length=250, unique=True,
                                 blank=False, null=False)
    task_is_pending = models.BooleanField(default=False)
    run_lock = models.DateTimeField(default=None, null=True)
    last_attempted_run = models.DateTimeField(default=None, null=True)
    last_completed_run = models.DateTimeField(default=None, null=True)
    data = JSONField()
    data_checksum = models.CharField(max_length=40, default=None, null=True)
    version = models.IntegerField(default=0, null=False)

    def save(self, update_checksum=False, *args, **kwargs):
        """
        Like the usual 'save' method except that you can pass a supplementary
        keyword parameter to update the 'data_checksum' field.

        :param bool update_checksum: Computes the checksum of the 'data' field
            and stores it in the 'data_checksum' field.
        """
        if update_checksum:
            self.data_checksum = get_data_checksum(self.data)
        return super(TaskData, self).save(*args, **kwargs)

    def versioned_update(self, **kwargs):
        """
        Update the fields as requested through the keyword parameters
        but do it in a way that avoids corruption through concurrent writes.
        We rely on the 'version' field to update the data only if the version
        in the database matches the version we loaded.

        :return: True if the update worked, False otherwise
        :rtype: bool
        """
        kwargs['version'] = self.version + 1
        if 'data' in kwargs and 'data_checksum' not in kwargs:
            kwargs['data_checksum'] = get_data_checksum(kwargs['data'])
        updated = TaskData.objects.filter(
            pk=self.pk, version=self.version).update(**kwargs)
        if updated:
            self.refresh_from_db(fields=kwargs.keys())
        return True if updated else False

    def get_run_lock(self, timeout=1800):
        """
        Try to grab the run lock associated to the task. Once acquired, the
        lock will be valid for the number of seconds specified in the 'timeout'
        parameter.

        :param int timeout: the number of seconds of validity of the lock
        :return: True if the lock has been acquired, False otherwise.
        :rtype: bool
        """
        timestamp = now()
        locked_until = timestamp + timedelta(seconds=timeout)
        # By matching on run_lock=NULL we ensure that we have the right
        # to take the lock. If the lock is already taken, the update query
        # will not match any line.
        updated = TaskData.objects.filter(
            Q(run_lock=None) | Q(run_lock__lt=timestamp),
            id=self.id
        ).update(run_lock=locked_until)
        self.refresh_from_db(fields=['run_lock'])
        return True if updated else False

    def extend_run_lock(self, delay=1800):
        """
        Extend the duration of the lock for the given delay. Calling this
        method when the lock is not yet acquired will raise an exception.

        Note that you should always run this outside of any transaction so
        that the new expiration time is immediately visible, otherwise
        it might only be committed much later when the transaction ends.
        The

        :param int delay: the number of seconds to add to lock expiration date
        """
        if connection.in_atomic_block:
            m = 'extend_run_lock() should be called outside of any transaction'
            warnings.warn(RuntimeWarning(m))

        self.run_lock += timedelta(seconds=delay)
        self.save(update_fields=['run_lock'])
