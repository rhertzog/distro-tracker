from __future__ import unicode_literals
from django.db import models


class CommandConfirmation(models.Model):
    command = models.CharField(max_length=120)
    confirmation_key = models.CharField(max_length=40)
    date_sent = models.DateTimeField(auto_now_add=True)

    def __unicode__(self):
        return self.command

    def __str__(self):
        return self.command
