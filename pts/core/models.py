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


class BasePackage(models.Model):
    name = models.CharField(max_length=100, unique=True)


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


@python_2_unicode_compatible
class BinaryPackage(BasePackage):
    source_package = models.ForeignKey(SourcePackage)

    objects = BinaryPackageManager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        # Take the URL of its source package
        return self.source_package.get_absolute_url()
