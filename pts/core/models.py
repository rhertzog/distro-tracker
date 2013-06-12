from __future__ import unicode_literals
from django.db import models
from core.utils import get_or_none


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


class EmailUser(models.Model):
    email = models.EmailField(max_length=254, unique=True)

    objects = EmailUserManager()

    def __unicode__(self):
        return self.email

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

        return package in self.package_set.all()


class PackageManager(models.Manager):
    """
    A custom Manager for the ``Package`` model.
    """
    def exists_with_name(self, package_name):
        """
        Returns True if a package with the given name exists.
        """
        return self.filter(name=package_name).exists()


class Package(models.Model):
    name = models.CharField(max_length=100, unique=True)
    subscriptions = models.ManyToManyField(EmailUser, through='Subscription')

    objects = PackageManager()

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.name


class SubscriptionManager(models.Manager):
    def create_for(self, package_name, email):
        package = get_or_none(Package, name=package_name)
        if not package:
            return None
        email_user, created = EmailUser.objects.get_or_create(
            email=email)

        return self.create(
            email_user=email_user,
            package=package)

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
        return email_user.subscription_set.all()


class Subscription(models.Model):
    email_user = models.ForeignKey(EmailUser)
    package = models.ForeignKey(Package)

    objects = SubscriptionManager()

    def __unicode__(self):
        return self.email_user + ' ' + self.package

    def __str__(self):
        return self.email_user + ' ' + self.package


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


class BinaryPackage(models.Model):
    name = models.CharField(max_length=100, unique=True)
    source_package = models.ForeignKey(Package)

    objects = BinaryPackageManager()

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.name
