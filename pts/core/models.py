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
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.core.urlresolvers import reverse
from pts.core.utils import get_or_none
from pts.core.utils import SpaceDelimitedTextField

from debian.debian_support import AptPkgVersion


@python_2_unicode_compatible
class Keyword(models.Model):
    name = models.CharField(max_length=50, unique=True)
    default = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class EmailUserManager(models.Manager):
    """
    A custom Manager for the ``EmailUser`` model.
    """
    def is_user_subscribed_to(self, user_email, package_name):
        """
        Checks if the given user is subscribed to the given package.
        """
        user = get_or_none(EmailUser, email=user_email)
        if not user:
            return False
        else:
            return user.is_subscribed_to(package_name)


@python_2_unicode_compatible
class EmailUser(models.Model):
    email = models.EmailField(max_length=254, unique=True)
    default_keywords = models.ManyToManyField(Keyword)

    objects = EmailUserManager()

    def __str__(self):
        return self.email

    def is_subscribed_to(self, package):
        """
        Checks if the user is subscribed to the given package.
        ``package`` can be either a str representing the name of the package
        or a ``Package`` instance.
        """
        if not isinstance(package, Package):
            package = get_or_none(Package, name=package)
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
        new_object = not self.id
        models.Model.save(self, *args, **kwargs)
        if new_object:
            self.default_keywords = Keyword.objects.filter(default=True)


class PackageManager(models.Manager):
    """
    A custom Manager for the ``Package`` model.
    """
    def __init__(self, package_type=None, *args, **kwargs):
        super(PackageManager, self).__init__(*args, **kwargs)
        self.type = package_type

    def get_query_set(self):
        qs = super(PackageManager, self).get_query_set()
        if self.type is None:
            return qs
        return qs.filter(package_type=self.type)

    def exists_with_name(self, package_name):
        """
        Returns True if a package with the given name exists.
        """
        return self.filter(name=package_name).exists()

    def create(self, *args, **kwargs):
        if 'package_type' not in kwargs and self.type is not None:
            kwargs['package_type'] = self.type

        return super(PackageManager, self).create(*args, **kwargs)

    def get_or_create(self, *args, **kwargs):
        defaults = kwargs.get('defaults', {})
        if self.type is not None:
            defaults.update({'package_type': self.type})
        kwargs['defaults'] = defaults
        return super(PackageManager, self).get_or_create(*args, **kwargs)

    def all_with_subscribers(self):
        """
        An additional method which filters the packages and returns a QuerySet
        containing only those which have at least one subscriber.
        """
        qs = self.annotate(subscriber_count=models.Count('subscriptions'))
        return qs.filter(subscriber_count__gt=0)


class BasePackage(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        abstract = True


@python_2_unicode_compatible
class Package(BasePackage):
    SOURCE_PACKAGE_TYPE = 0
    PSEUDO_PACKAGE_TYPE = 1
    SUBSCRIPTION_ONLY_PACKAGE_TYPE = 2
    TYPE_CHOICES = (
        (SOURCE_PACKAGE_TYPE, 'Source package'),
        (PSEUDO_PACKAGE_TYPE, 'Pseudo package'),
        (SUBSCRIPTION_ONLY_PACKAGE_TYPE, 'Subscription-only package'),
    )

    subscriptions = models.ManyToManyField(EmailUser, through='Subscription')
    package_type = models.IntegerField(choices=TYPE_CHOICES, default=0)

    objects = PackageManager()
    source_packages = PackageManager(SOURCE_PACKAGE_TYPE)
    pseudo_packages = PackageManager(PSEUDO_PACKAGE_TYPE)
    subscription_only_packages = PackageManager(SUBSCRIPTION_ONLY_PACKAGE_TYPE)

    def __str__(self):
        return self.name


class PseudoPackage(Package):
    class Meta:
        proxy = True

    objects = PackageManager(Package.PSEUDO_PACKAGE_TYPE)

    def get_absolute_url(self):
        return reverse('pts-package-page', kwargs={
            'package_name': self.name
        })


class SourcePackage(Package):
    class Meta:
        proxy = True

    objects = PackageManager(Package.SOURCE_PACKAGE_TYPE)

    def get_absolute_url(self):
        return reverse('pts-package-page', kwargs={
            'package_name': self.name
        })

    @property
    def main_entry(self):
        """
        Returns the `SourceRepositoryEntry` of the given package which belongs
        to either the default repository. If the package is not found in the
        default repository, the entry from the repository with the highest
        version of the package is returned.
        """
        default_repository = Repository.objects.get_default()
        if default_repository.exists():
            default_repository = default_repository[0]
            qs = SourceRepositoryEntry.objects.filter(
                source_package=self, repository=default_repository)
        else:
            qs = SourceRepositoryEntry.objects.filter(source_package=self)

        if qs.exists():
            return max(qs, key=lambda x: AptPkgVersion(x.version))
        else:
            return None


def get_web_package(package_name):
    """
    Utility function returning either a PseudoPackage or a SourcePackage based
    on the given package_name.

    If neither of them are found, it tries to find a BinaryPackage with the
    given name and returns the corresponding SourcePackage if found.

    If that is not possible, ``None`` is returned.
    """
    if SourcePackage.objects.exists_with_name(package_name):
        return SourcePackage.objects.get(name=package_name)
    elif PseudoPackage.objects.exists_with_name(package_name):
        return PseudoPackage.objects.get(name=package_name)
    elif BinaryPackage.objects.exists_with_name(package_name):
        binary_package = BinaryPackage.objects.get(name=package_name)
        return binary_package.source_package

    return None

class SubscriptionManager(models.Manager):
    def create_for(self, package_name, email, active=True):
        package = get_or_none(Package, name=package_name)
        if not package:
            # If the package did not previously exist, create a
            # "subscriptions-only" package.
            package = Package.subscription_only_packages.create(
                name=package_name)
        email_user, created = EmailUser.objects.get_or_create(
            email=email)

        subscription, _ = self.get_or_create(email_user=email_user,
                                             package=package)
        subscription.active = active
        subscription.save()

        return subscription

    def unsubscribe(self, package_name, email):
        package = get_or_none(Package, name=package_name)
        email_user = get_or_none(EmailUser, email=email)
        if not package or not email_user:
            return False
        subscription = get_or_none(
            Subscription, email_user=email_user, package=package)
        if subscription:
            subscription.delete()
        return True

    def get_for_email(self, email):
        email_user = get_or_none(EmailUser, email=email)
        if not email_user:
            return []
        return email_user.subscription_set.all_active()

    def all_active(self, keyword=None):
        """
        Returns all active subscriptions, optionally filtered on having the
        given keyword.
        This method is not guaranteed to return a ``QuerySet`` object so
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
    email_user = models.ForeignKey(EmailUser)
    package = models.ForeignKey(Package)
    active = models.BooleanField(default=True)
    _keywords = models.ManyToManyField(Keyword)
    _use_user_default_keywords = models.BooleanField(default=True)

    objects = SubscriptionManager()

    class KeywordsAdapter(object):
        """
        An adapter for accessing a Subscription's keywords.

        When a Subscription is initially created, it uses the default keywords
        of the user. Only after modifying the subscription-specific keywords,
        should it use a different set of keywords.

        This class allows the clients of the ``Subscription`` class to access
        the keywords field without having to think about whether the
        subscription is using the user's keywords or not, rather the whole
        process is handled automatically and seamlessly.
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


class BinaryPackageManager(models.Manager):
    """
    A custom Manager for the ``BinaryPackage`` model.
    """
    def exists_with_name(self, package_name):
        """
        Returns True if a package with the given name exists.
        """
        return self.filter(name=package_name).exists()

    def get_by_name(self, package_name):
        """
        Returns a ``BinaryPackage`` object for the given package name.
        """
        return self.get(name=package_name)

    def filter_by_source(self, source_package):
        """
        Returns the set of all binary packages which are linked to the given
        source package in at least one repository.
        """
        return self.filter(
            sourcerepositoryentry__source_package=source_package)

    def filter_no_source(self):
        """
        Returns all binary packages which are not linked to any source package.
        """
        qs = self.annotate(entry_count=models.Count('sourcerepositoryentry'))
        return qs.filter(entry_count=0)


@python_2_unicode_compatible
class BinaryPackage(BasePackage):
    source_package = models.ForeignKey(
        SourcePackage,
        on_delete=models.SET_NULL,
        null=True)

    objects = BinaryPackageManager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        # Take the URL of its source package
        return self.source_package.get_absolute_url()

    def update_source_mapping(self):
        entries = SourceRepositoryEntry.objects.filter(binary_packages=self)
        default_repository_entries = entries.filter(repository__default=True)
        if default_repository_entries.exists():
            entries = default_repository_entries
        highest_version_entry = max(entries, key=lambda x: AptPkgVersion(x.version))

        if self.source_package != highest_version_entry.source_package:
            self.source_package = highest_version_entry.source_package
            self.save()
            return True
        else:
            return False

from jsonfield import JSONField
from django.core.exceptions import ValidationError


@python_2_unicode_compatible
class Architecture(models.Model):
    name = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.name


class RepositoryManager(models.Manager):
    def get_default(self):
        """
        Returns the default Repository.

        If there is no default repository, returns an empty QuerySet.
        """
        return self.filter(default=True)


@python_2_unicode_compatible
class Repository(models.Model):
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
        base_url = self.uri.rstrip('/')
        return [
            base_url + '/' + self.suite + '/' + component
            for component in self.components
        ]

    def has_source_package(self, package):
        """
        The method returns whether the repository contains the given source
        package.
        The source package is an instance of the `SourcePackage` model.
        """
        qs = SourceRepositoryEntry.objects.filter(
            repository=self,
            source_package=package
        )
        return qs.exists()

    def _adapt_arguments(self, arguments, src_pkg):
        arguments['architectures'] = [
            Architecture.objects.get(name=arch)
            for arch in arguments.get('architectures', [])
            if Architecture.objects.filter(name=arch).exists()
        ]
        arguments['binary_packages'] = [
            BinaryPackage.objects.get_or_create(name=pkg, defaults={
                'source_package': src_pkg
            })[0]
            for pkg in arguments.get('binary_packages', [])
        ]
        if 'maintainer' in arguments:
            maintainer, _ = Developer.objects.get_or_create(
                email=arguments['maintainer']['email'])
            maintainer.update(**arguments['maintainer'])
            maintainer.save()
            arguments['maintainer'] = maintainer

        uploaders = []
        for uploader in arguments.get('uploaders', []):
            developer, _ = Developer.objects.get_or_create(
                email=uploader['email'])
            developer.update(**uploader)
            developer.save()
            uploaders.append(developer)
        arguments['uploaders'] = uploaders

        return arguments

    def add_source_package(self, package, **kwargs):
        """
        The method adds a new source package to the repository.

        The source package is given by the package parameter.
        The rest of the keyword arguments describe the SourceRepositoryEntry
        object which will be created for this source package, repository pair.
        """
        entry = SourceRepositoryEntry.objects.create(
            repository=self,
            source_package=package
        )
        kwargs = self._adapt_arguments(kwargs, package)
        entry.update(**kwargs)
        entry.save()
        return entry

    def update_source_package(self, package, **kwargs):
        """
        The method updates the data linked to a source package which is a part
        of the repository.
        """
        entry = SourceRepositoryEntry.objects.get(
            repository=self,
            source_package=package)
        if entry.version != kwargs['version']:
            kwargs = self._adapt_arguments(kwargs, package)
            entry.update(**kwargs)
            entry.save()
            return True
        else:
            return False

    @classmethod
    def release_file_url(cls, base_url, distribution):
        base_url = base_url.rstrip('/')
        return base_url + '/dists/{distribution}/Release'.format(
            distribution=distribution)

    def clean(self):
        super(Repository, self).clean()
        if self.default:
            # If this instance is not trying to set default to True, it is safe
            qs = Repository.objects.filter(default=True).exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "Only one repository can be set as the default")


@python_2_unicode_compatible
class Developer(models.Model):
    name = models.CharField(max_length=60, blank=True)
    email = models.EmailField(max_length=244, unique=True)

    def __str__(self):
        return "{name} <{email}>".format(name=self.name, email=self.email)

    def to_dict(self):
        """
        Returns a dictionary representing a Developer instance.
        """
        from django.forms.models import model_to_dict
        return model_to_dict(self, fields=['name', 'email'])

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


@python_2_unicode_compatible
class SourceRepositoryEntry(models.Model):
    source_package = models.ForeignKey(
        SourcePackage,
        related_name='repository_entries')
    repository = models.ForeignKey(Repository)
    version = models.CharField(max_length=50)

    standards_version = models.CharField(max_length=550, blank=True)
    architectures = models.ManyToManyField(Architecture, blank=True)
    binary_packages = models.ManyToManyField(BinaryPackage, blank=True)

    maintainer = models.ForeignKey(
        Developer,
        related_name='package_maintains_set',
        null=True)
    uploaders = models.ManyToManyField(
        Developer,
        related_name='package_uploads_set')

    priority = models.CharField(max_length=50, blank=True)
    section = models.CharField(max_length=50, blank=True)

    dsc_file_name = models.CharField(max_length=255, blank=True)
    directory = models.CharField(max_length=255, blank=True)
    homepage = models.URLField(max_length=255, blank=True)
    vcs = JSONField()

    class Meta:
        # A source package can be found only once in a single repository.
        unique_together = ('source_package', 'repository')

    def __str__(self):
        return "Source package {pkg} in the repository {repo}".format(
            pkg=self.source_package,
            repo=self.repository)

    @property
    def dsc_file_url(self):
        """
        Returns the URL where the .dsc file of this entry can be found.
        """
        if self.directory and self.dsc_file_name:
            base_url = self.repository.uri.rstrip('/')
            return base_url + '/' + self.directory + '/' + self.dsc_file_name
        else:
            return None

    @property
    def directory_url(self):
        """
        Returns the URL of the package's directory.
        """
        if self.directory:
            base_url = self.repository.uri.rstrip('/')
            return base_url + '/' + self.directory
        else:
            return None

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


@python_2_unicode_compatible
class PackageExtractedInfo(models.Model):
    package = models.ForeignKey(Package)
    key = models.CharField(max_length='50')
    value = JSONField()

    def __str__(self):
        return '{key}: {value} for package {package}'.format(
            key=self.key, value=self.value, package=self.package)

    class Meta:
        unique_together = ('key', 'package')


@python_2_unicode_compatible
class VersionControlSystem(models.Model):
    """
    Describes a particular version control system type which packages can
    set in their source information.
    """
    name = models.CharField(max_length=50, blank=True)
    shorthand = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return "{name} ({shorthand})".format(
            name=self.name, shorthand=self.shorthand
        )


class MailingListManager(models.Manager):
    """
    A custom manager for the MailingList class.
    """
    def get_by_email(self, email):
        """
        Returns a MailingList instance which matches the given email.
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
    Custom validator for MailingList's archive_url_template field.
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

    Instances should have the archive_url_template field set to the template
    which archive URLs should follow where a mandatory parameter is {user}.
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
        """
        return self.archive_url_template.format(user=user)

    def archive_url_for_email(self, email):
        """
        Returns the archive URL for the given email.

        Similar to archive_url, but extracts the user name from the email
        first.
        """
        if '@' not in email:
            return None
        user, domain = email.rsplit('@', 1)

        if domain != self.domain:
            return None

        return self.archive_url(user)
