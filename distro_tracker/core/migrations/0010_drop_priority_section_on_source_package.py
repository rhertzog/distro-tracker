# -*- coding: utf-8 -*-

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_unique_constraint_on_subscriptions'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sourcepackagerepositoryentry',
            name='priority',
        ),
        migrations.RemoveField(
            model_name='sourcepackagerepositoryentry',
            name='section',
        ),
    ]
