from __future__ import unicode_literals
from django.db import models
from core.utils import get_or_none


class EmailUser(models.Model):
    email = models.EmailField(max_length=254, unique=True)

    def __unicode__(self):
        return self.email

    def __str__(self):
        return self.email


class Package(models.Model):
    name = models.CharField(max_length=100, unique=True)
    subscriptions = models.ManyToManyField(EmailUser, through='Subscription')

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


class Subscription(models.Model):
    email_user = models.ForeignKey(EmailUser)
    package = models.ForeignKey(Package)

    objects = SubscriptionManager()

    def __unicode__(self):
        return self.email_user + ' ' + self.package

    def __str__(self):
        return self.email_user + ' ' + self.package
