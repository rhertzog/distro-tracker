# -*- coding: utf-8 -*-

from django.db import models, migrations


def forwards_func(apps, schema_editor):
    # We get the model from the versioned app registry;
    # if we directly import it, it'll be the wrong version
    MailingList = apps.get_model('core', 'MailingList')
    db_alias = schema_editor.connection.alias
    MailingList.objects.using(db_alias).bulk_create([
        MailingList(name='alioth-debian-net', domain='alioth-lists.debian.net',
                    archive_url_template='https://alioth-lists.debian.net/pipermail/{user}/'),
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_delete_runningjob'),
    ]

    operations = [
        migrations.RunPython(
            forwards_func,
        ),
    ]
