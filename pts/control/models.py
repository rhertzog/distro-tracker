from __future__ import unicode_literals
from django.db import models

import hashlib
import string
import random


class CommandConfirmationManager(models.Manager):
    def create_for_command(self, command):
        chars = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(chars) for _ in range(16))
        random_string = random_string.encode('ascii')
        salt = hashlib.sha1(random_string).hexdigest()
        hash_input = (salt + command).encode('ascii')
        confirmation_key = hashlib.sha1(hash_input).hexdigest()

        return self.create(
            command=command,
            confirmation_key=confirmation_key)


class CommandConfirmation(models.Model):
    command = models.CharField(max_length=120)
    confirmation_key = models.CharField(max_length=40)
    date_sent = models.DateTimeField(auto_now_add=True)

    objects = CommandConfirmationManager()

    def __unicode__(self):
        return self.command

    def __str__(self):
        return self.command
