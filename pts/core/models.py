# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.
"""Models for the :mod:`pts.core` app."""
from __future__ import unicode_literals
from django.db import models
from django.utils import six
from django.utils.encoding import python_2_unicode_compatible
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.core.urlresolvers import reverse
from django.conf import settings
from pts.core.utils import get_or_none
from pts.core.utils import SpaceDelimitedTextField
from pts.core.utils import verify_signature
from pts.core.utils.plugins import PluginRegistry
from pts.core.utils.email_messages import decode_header

from debian.debian_support import AptPkgVersion
from email import message_from_string
from email.utils import getaddresses
from email.iterators import typed_subpart_iterator


@python_2_unicode_compatible
class Keyword(models.Model):
    """
    Describes a keyword which can be used to tag package messages.
    """
    name = models.CharField(max_length=50, unique=True)
    default = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class EmailUserManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`EmailUser` model.
    """
    def is_user_subscribed_to(self, user_email, package_name):
        """
        Checks if the given user is subscribed to the given package.

        :param user_email: The email of the user
        :type user_email: string

        :param package_name: The name of the package
        :type package_name: string
        """
        user = get_or_none(EmailUser, email=user_email)
        if not user:
            return False
        else:
            return user.is_subscribed_to(package_name)


@python_2_unicode_compatible
class EmailUser(models.Model):
    """
    A model describing users identified by their email address.
    """
    email = models.EmailField(max_length=254, unique=True)
    default_keywords = models.ManyToManyField(Keyword)

    objects = EmailUserManager()

    def __str__(self):
        return self.email

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

    def save(self, *args, **kwargs):
        """
        Overrides the default save method to add the set of default keywords to
        the user's own default keywords after creating an instance.
        """
        new_object = not self.id
        models.Model.save(self, *args, **kwargs)
        if new_object:
            self.default_keywords = Keyword.objects.filter(default=True)


class PackageManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`PackageName` model.
    """
    def __init__(self, package_type=None, *args, **kwargs):
        super(PackageManager, self).__init__(*args, **kwargs)
        self.type = package_type

    def get_query_set(self):
        """
        Overrides the default query set of the manager to exclude any
        :class:`PackageName` objects with a type that does not match this
        manager instance's :attr:`type`.

        If the instance does not have a :attr:`type`, then all
        :class:`PackageName` instances are returned.
        """
        qs = super(PackageManager, self).get_query_set()
        if self.type is None:
            return qs
        return qs.filter(package_type=self.type)

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
        method to inject a :attr:`package_type <PackageName.package_type>` to the
        instance being created.

        The type is the type given in this manager instance's :attr:`type`
        attribute.
        """
        if 'package_type' not in kwargs and self.type is not None:
            kwargs['package_type'] = self.type

        return super(PackageManager, self).create(*args, **kwargs)

    def get_or_create(self, *args, **kwargs):
        """
        Overrides the default
        :meth:`get_or_create <django.db.models.Manager.get_or_create>`
        method to inject a :attr:`package_type <PackageName.package_type>` to the
        instance being created.

        The type is the type given in this manager instance's :attr:`type`
        attribute.
        """
        defaults = kwargs.get('defaults', {})
        if self.type is not None:
            defaults.update({'package_type': self.type})
        kwargs['defaults'] = defaults
        return super(PackageManager, self).get_or_create(*args, **kwargs)

    def all_with_subscribers(self):
        """
        A method which filters the packages and returns a QuerySet
        containing only those which have at least one subscriber.

        :rtype: :py:class:`QuerySet <django.db.models.query.QuerySet>` of
            :py:class:`PackageName` instances.
        """
        qs = self.annotate(subscriber_count=models.Count('subscriptions'))
        return qs.filter(subscriber_count__gt=0)


class BasePackageName(models.Model):
    """
    An abstract model defining common attributes and operations for package
    names.
    """
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        abstract = True


@python_2_unicode_compatible
class PackageName(BasePackageName):
    """
    A model describing package names.

    Three different types of packages are supported:

    - Source packages
    - Pseudo packages
    - Subscription-only packages

    Binary packages are a separate model since they are allowed to have the
    same name as an existing source package.
    """
    SOURCE_PACKAGE_TYPE = 0
    PSEUDO_PACKAGE_TYPE = 1
    SUBSCRIPTION_ONLY_PACKAGE_TYPE = 2
    TYPE_CHOICES = (
        (SOURCE_PACKAGE_TYPE, 'Source package'),
        (PSEUDO_PACKAGE_TYPE, 'Pseudo package'),
        (SUBSCRIPTION_ONLY_PACKAGE_TYPE, 'Subscription-only package'),
    )

    subscriptions = models.ManyToManyField(EmailUser, through='Subscription')
    #: The type of the package
    package_type = models.IntegerField(choices=TYPE_CHOICES, default=0)

    objects = PackageManager()
    source_packages = PackageManager(SOURCE_PACKAGE_TYPE)
    pseudo_packages = PackageManager(PSEUDO_PACKAGE_TYPE)
    subscription_only_packages = PackageManager(SUBSCRIPTION_ONLY_PACKAGE_TYPE)

    def __str__(self):
        return self.name


class PseudoPackageName(PackageName):
    """
    A convenience proxy model of the :class:`PackageName` model.

    It returns only those :class:`PackageName` instances whose
    :attr:`package_type <PackageName.package_type>` is
    :attr:`PSEUDO_PACKAGE_TYPE <PackageName.PSEUDO_PACKAGE_TYPE>`.
    """
    class Meta:
        proxy = True

    objects = PackageManager(PackageName.PSEUDO_PACKAGE_TYPE)

    def get_absolute_url(self):
        return reverse('pts-package-page', kwargs={
            'package_name': self.name
        })


class SourcePackageName(PackageName):
    """
    A convenience proxy model of the :class:`PackageName` model.

    It returns only those :class:`PackageName` instances whose
    :attr:`package_type <PackageName.package_type>` is
    :attr:`SOURCE_PACKAGE_TYPE <PackageName.SOURCE_PACKAGE_TYPE>`.
    """
    class Meta:
        proxy = True

    objects = PackageManager(PackageName.SOURCE_PACKAGE_TYPE)

    def get_absolute_url(self):
        return reverse('pts-package-page', kwargs={
            'package_name': self.name
        })

    @property
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

        if qs.exists():
            return max(qs, key=lambda x: AptPkgVersion(x.version))
        else:
            return None

    @property
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

        if qs.exists():
            return max(
                qs,
                key=lambda x: AptPkgVersion(x.source_package.version)
            )
        else:
            return None

    @property
    def repositories(self):
        """
        Returns all repositories which contain a source package with this name.

        :rtype: :py:class:`QuerySet <django.db.models.query.QuerySet>` of
            :py:class:`Repository` instances.
        """
        kwargs = {
            'sourcepackagerepositoryentry'
            '__source_package'
            '__source_package_name': self
        }
        return Repository.objects.filter(**kwargs).distinct()


def get_web_package(package_name):
    """
    Utility function returning either a :class:`PseudoPackageName` or a
    :class:`SourcePackageName` based on the given ``package_name``.

    If neither of them are found, it tries to find a :class:`BinaryPackageName`
    with the given name and returns the corresponding :class:`SourcePackageName`,
    if found.

    If that is not possible, ``None`` is returned.

    :rtype: :class:`PackageName` or ``None``

    :param package_name: The name for which a package should be found.
    :type package_name: string
    """
    if SourcePackageName.objects.exists_with_name(package_name):
        return SourcePackageName.objects.get(name=package_name)
    elif PseudoPackageName.objects.exists_with_name(package_name):
        return PseudoPackageName.objects.get(name=package_name)
    elif BinaryPackageName.objects.exists_with_name(package_name):
        binary_package = BinaryPackageName.objects.get(name=package_name)
        return binary_package.main_source_package_name

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
            package = PackageName.subscription_only_packages.create(
                name=package_name)
        email_user, created = EmailUser.objects.get_or_create(
            email=email)

        subscription, _ = self.get_or_create(email_user=email_user,
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
        email_user = get_or_none(EmailUser, email=email)
        if not package or not email_user:
            return False
        subscription = get_or_none(
            Subscription, email_user=email_user, package=package)
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
           clients should not count on chaining additional filters to the result.
        """
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            return []
        return email_user.subscription_set.all_active()

    def all_active(self, keyword=None):
        """
        Returns all active subscriptions, optionally filtered on having the
        given keyword.

        :rtype: ``iterable`` of :class:`Subscription` instances

        .. note::
           Since this method is not guaranteed to return a
           :py:class:`QuerySet <django.db.models.query.QuerySet>` object,
           clients should not count on chaining additional filters to the result.
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


@python_2_unicode_compatible
class Subscription(models.Model):
    """
    A model describing a subscription of a single :class:`EmailUser` to a
    single :class:`PackageName`.
    """
    email_user = models.ForeignKey(EmailUser)
    package = models.ForeignKey(PackageName)
    active = models.BooleanField(default=True)
    _keywords = models.ManyToManyField(Keyword)
    _use_user_default_keywords = models.BooleanField(default=True)

    objects = SubscriptionManager()

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
                manager = self._subscription.email_user.default_keywords
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
                user = self._subscription.email_user
                for keyword in user.default_keywords.all():
                    self._subscription._keywords.add(keyword)
                self._subscription.save()

    def __init__(self, *args, **kwargs):
        super(Subscription, self).__init__(*args, **kwargs)
        self.keywords = Subscription.KeywordsAdapter(self)

    def __str__(self):
        return str(self.email_user) + ' ' + str(self.package)


class BinaryPackageNameManager(models.Manager):
    """
    A custom :class:`Manager <django.db.models.Manager>` for the
    :class:`BinaryPackageName` model.
    """
    def exists_with_name(self, package_name):
        """
        :param package_name: A name of a package
        :type package_name: string
        :returns True: if the package with the given name exists.
        """
        return self.filter(name=package_name).exists()

    def get_by_name(self, package_name):
        """
        :returns: A binary package with the given name
        :rtype: :class:`BinaryPackage`
        """
        return self.get(name=package_name)


@python_2_unicode_compatible
class BinaryPackageName(BasePackageName):
    """
    A model representing a single binary package name.

    Binary package versions must all reference an existing instance of this
    type.
    """
    source_package = models.ForeignKey(
        SourcePackageName,
        on_delete=models.SET_NULL,
        null=True)

    objects = BinaryPackageNameManager()

    def __str__(self):
        return self.name

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


from jsonfield import JSONField
from django.core.exceptions import ValidationError


@python_2_unicode_compatible
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


@python_2_unicode_compatible
class Repository(models.Model):
    """
    A model describing Debian repositories.
    """
    name = models.CharField(max_length=50, unique=True)
    shorthand = models.CharField(max_length=10, unique=True)

    uri = models.URLField(max_length=200, verbose_name='URI')
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

    position = models.IntegerField(default=lambda: Repository.objects.count())

    objects = RepositoryManager()

    class Meta:
        verbose_name_plural = "repositories"
        ordering = (
            'position',
        )

    def __str__(self):
        return ' '.join((
            self.uri,
            self.codename,
            ' '.join(self.components)
        ))

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
        qs = self.sourcepackagerepositoryentry_set.filter(
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
        :class:`SourcePackageRepositoryEntry` should be in the keyword arguments.

        Returns the newly created :class:`SourcePackageRepositoryEntry` for the
        given :class:`SourcePackage`.

        :rtype: :class:`SourcePackageRepositoryEntry`
        """
        entry = SourcePackageRepositoryEntry.objects.create(
            repository=self,
            source_package=package,
            **kwargs
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

    @classmethod
    def release_file_url(cls, base_url, suite):
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


@python_2_unicode_compatible
class ContributorEmail(models.Model):
    """
    A model representing a package contributor's email.

    The email is separated from the rest of the information about the
    contributor, e.g. his name, in order to allow for the case where the same
    contributor has possibly differently spelled names in different packages.
    """
    email = models.EmailField(max_length=244, unique=True)

    def __str__(self):
        return self.email


@python_2_unicode_compatible
class ContributorName(models.Model):
    """
    Represents a name associated with a :class:`ContributorEmail`.

    A single contributor, as identified by his email, may have different
    written names in different contexts.
    """
    contributor_email = models.ForeignKey(ContributorEmail)
    name = models.CharField(max_length=60, blank=True)

    class Meta:
        unique_together = ('contributor_email', 'name')

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


@python_2_unicode_compatible
class SourcePackage(models.Model):
    """
    A model representing a single Debian source package.

    This means it holds any information regarding a (package_name, version)
    pair which is independent from the repository in which the package is
    found.
    """
    source_package_name = models.ForeignKey(
        SourcePackageName,
        related_name='source_package_versions')
    version = models.CharField(max_length=50)

    standards_version = models.CharField(max_length=550, blank=True)
    architectures = models.ManyToManyField(Architecture, blank=True)
    binary_packages = models.ManyToManyField(BinaryPackageName, blank=True)

    maintainer = models.ForeignKey(
        ContributorName,
        related_name='source_package',
        null=True)
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

    @property
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
        :class:`SourcePackageRepositoryEntry <pts.core.models.SourcePackageRepositoryEntry>`
        found in the instance's :attr:`repository_entries` which should be
        considered the main entry for this version.

        If the version is found in the default repository, the entry for the
        default repository is returned.

        Otherwise, the entry for the repository with the highest
        :attr:`position <pts.core.models.Repository.position>` field is
        returned.

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
                setattr(self, key, value)


@python_2_unicode_compatible
class BinaryPackage(models.Model):
    """
    The method represents a particular binary package.

    All information regarding a (binary-package-name, version) which is
    independent from the repository in which the package is found.
    """
    binary_package_name = models.ForeignKey(
        BinaryPackageName,
        related_name='binary_package_versions'
    )
    version = models.CharField(max_length=50, null=True)
    source_package = models.ForeignKey(SourcePackage)

    short_description = models.CharField(max_length=300, blank=True)
    long_description = models.TextField(blank=True)

    class Meta:
        unique_together = ('binary_package_name', 'version')

    def __str__(self):
        return 'Binary package {pkg}, version {ver}'.format(
            pkg=self.binary_package_name, ver=self.version)


@python_2_unicode_compatible
class BinaryPackageRepositoryEntry(models.Model):
    """
    A model representing repository specific information for a given binary
    package.

    It links a :class:`BinaryPackage` instance with the :class:`Repository`
    instance.
    """
    binary_package = models.ForeignKey(
        BinaryPackage,
        related_name='repository_entries'
    )
    repository = models.ForeignKey(
        Repository,
        related_name='binary_package_entries'
    )
    architecture = models.ForeignKey(Architecture)

    priority = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=50, blank=True)

    class Meta:
        unique_together = ('binary_package', 'repository', 'architecture')

    def __str__(self):
        return '{pkg} ({arch}) in the repository {repo}'.format(
            pkg=self.binary_package, arch=self.architecture, repo=self.repository)


@python_2_unicode_compatible
class SourcePackageRepositoryEntry(models.Model):
    """
    A model representing source package data that is repository specific.

    It links a :class:`SourcePackage` instance with the :class:`Repository`
    instance.
    """
    source_package = models.ForeignKey(
        SourcePackage,
        related_name='repository_entries'
    )
    repository = models.ForeignKey(Repository)

    priority = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=50, blank=True)

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
            base_url = self.repository.uri.rstrip('/')
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
            base_url = self.repository.uri.rstrip('/')
            return base_url + '/' + self.source_package.directory
        else:
            return None


@python_2_unicode_compatible
class PackageExtractedInfo(models.Model):
    """
    A model representing a quasi key-value store for package information
    extracted from other models in order to speed up its rendering on
    Web pages.
    """
    package = models.ForeignKey(PackageName)
    key = models.CharField(max_length='50')
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


@python_2_unicode_compatible
class MailingList(models.Model):
    """
    Describes a known mailing list.

    This provides PTS users to define the known mailing lists through the admin
    panel in order to support displaying their archives in the package pages
    without modifying any code.

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


@python_2_unicode_compatible
class RunningJob(models.Model):
    """
    A model used to serialize a running job state, i.e. instances of the
    :class:`JobState <pts.core.tasks.JobState>` class.
    """
    datetime_created = models.DateTimeField(auto_now_add=True)
    initial_task_name = models.CharField(max_length=50)
    additional_parameters = JSONField(null=True)
    state = JSONField(null=True)

    is_complete = models.BooleanField(default=False)

    def __str__(self):
        if self.is_complete:
            return "Completed Job (started {date})".format(
                date=self.datetime_created)
        else:
            return "Running Job (started {date})".format(
                date=self.datetime_created)


@python_2_unicode_compatible
class News(models.Model):
    """
    A model used to describe a news item regarding a package.
    """
    package = models.ForeignKey(PackageName)
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, default='text/plain')
    _db_content = models.TextField(blank=True, null=True)
    news_file = models.FileField(
        upload_to=lambda instance, filename: '/'.join((
            'news',
            instance.package.name,
            filename
        )),
        blank=True)
    created_by = models.CharField(max_length=100, blank=True)
    datetime_created = models.DateTimeField(auto_now_add=True)
    signed_by = models.ManyToManyField(
        ContributorName,
        related_name='signed_news_set')

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
            self.news_file.open('r')
            content = self.news_file.read()
            self.news_file.close()
            return content

    def save(self, *args, **kwargs):
        super(News, self).save(*args, **kwargs)

        signers = verify_signature(self.content)
        if signers is None:
            # No signature
            return

        signed_by = []
        for name, email in signers:
            signer_email, _ = ContributorEmail.objects.get_or_create(
                email=email)
            signer_name, _ = ContributorName.objects.get_or_create(
                name=name,
                contributor_email=signer_email)
            signed_by.append(signer_name)

        self.signed_by = signed_by

    def get_absolute_url(self):
        return reverse('pts-news-page', kwargs={
            'news_id': self.pk,
        })


class NewsRenderer(six.with_metaclass(PluginRegistry)):
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
        :type news: :class:`pts.core.models.News`
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


class RstNewsRenderer(NewsRenderer):
    """
    Renders news content as ReStructuredText.
    """
    content_type = 'text/x-rst'
    template_name = 'core/news-rst.html'


class EmailNewsRenderer(NewsRenderer):
    """
    Renders news content as an email message.
    """
    content_type = 'message/rfc822'
    template_name = 'core/news-email.html'

    @property
    def context(self):
        msg = message_from_string(self.news.content)
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
        USER_DEFINED_HEADERS = getattr(settings, 'PTS_EMAIL_NEWS_HEADERS', ())
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
            else:
                headers[header_name] = {'value': header_value}

        plain_text_payloads = [
            part.get_payload(decode=True)
            for part in typed_subpart_iterator(msg, 'text', 'plain')
        ]

        return {
            'headers': headers,
            'parts': plain_text_payloads,
        }


@python_2_unicode_compatible
class PackageBugStats(models.Model):
    """
    Model for bug statistics of source and pseudo packages (packages modelled
    by the :class:`PackageName` model).
    """
    package = models.OneToOneField(PackageName, related_name='bug_stats')
    stats = JSONField(blank=True)

    def __str__(self):
        return '{package} bug stats: {stats}'.format(
            package=self.package, stats=self.stats)


@python_2_unicode_compatible
class BinaryPackageBugStats(models.Model):
    """
    Model for bug statistics of binary packages (:class:`BinaryPackageName`).
    """
    package = models.OneToOneField(BinaryPackageName, related_name='bug_stats')
    stats = JSONField(blank=True)

    def __str__(self):
        return '{package} bug stats: {stats}'.format(
            package=self.package, stats=self.stats)
