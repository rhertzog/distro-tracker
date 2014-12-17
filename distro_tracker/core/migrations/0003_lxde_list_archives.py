# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


def forwards_func(apps, schema_editor):
    # We get the model from the versioned app registry;
    # if we directly import it, it'll be the wrong version
    MailingList = apps.get_model('core', 'MailingList')
    db_alias = schema_editor.connection.alias
    MailingList.objects.using(db_alias).bulk_create([
        MailingList(name='lxde', domain='lists.lxde.org',
                    archive_url_template='http://lists.lxde.org/pipermail/{user}/'),
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            forwards_func,
        ),
    ]
