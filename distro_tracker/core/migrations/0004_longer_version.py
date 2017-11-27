# -*- coding: utf-8 -*-

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_lxde_list_archives'),
    ]

    operations = [
        migrations.AlterField(
            model_name='binarypackage',
            name='version',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='sourcepackage',
            name='version',
            field=models.CharField(max_length=100),
        ),
    ]
