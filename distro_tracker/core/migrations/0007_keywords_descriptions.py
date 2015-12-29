# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations, models

keywords = {
    'bts': 'All bug reports and associated discussions',
    'bts-control': 'Status changes of bug reports',
    'vcs': 'Commit notices of the VCS repository associated to the package',
    'upload-source': 'Notifications of sourceful uploads',
    'upload-binary': 'Notifications of binary-only uploads (made by build daemons)',
    'summary': 'News about the status of the package',
    'contact': 'Mails from people contacting the maintainer(s)',
    'default': 'Anything else that cannot be better classified',
    'build': 'Notifications of build failures from build daemons',
    'derivatives': 'Changes made to this package by derivatives',
    'derivatives-bugs': 'Bug traffic about this package in derivative distributions',
    'archive': 'Other notifications sent by the archive management tool',
    'translation': 'Notifications about translations related to the package',
}


def describe_keywords(apps, schema_editor):
    Keyword = apps.get_model('core', 'Keyword')
    for k, v in keywords.items():
        Keyword.objects.filter(name=k).update(description=v)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0006_more_architectures'),
    ]
    operations = [
        migrations.AddField(
            model_name='Keyword',
            name='description',
            field=models.CharField(max_length=256, blank=True),
            preserve_default=True,
        ),
        migrations.RunPython(describe_keywords),
    ]
