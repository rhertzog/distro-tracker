# -*- coding: utf-8 -*-

from django.db import models, migrations


def forwards_func(apps, schema_editor):
    # We get the model from the versioned app registry;
    # if we directly import it, it'll be the wrong version
    Architecture = apps.get_model('core', 'Architecture')
    db_alias = schema_editor.connection.alias
    Architecture.objects.using(db_alias).bulk_create([
        Architecture(name='alpha'),
        Architecture(name='arm'),
        Architecture(name='arm64'),
        Architecture(name='armeb'),
        Architecture(name='avr32'),
        Architecture(name='hppa'),
        Architecture(name='m32r'),
        Architecture(name='m68k'),
        Architecture(name='mips64'),
        Architecture(name='mips64el'),
        Architecture(name='mipsn32'),
        Architecture(name='mipsn32el'),
        Architecture(name='or1k'),
        Architecture(name='powerpcel'),
        Architecture(name='powerpcspe'),
        Architecture(name='ppc64'),
        Architecture(name='ppc64el'),
        Architecture(name='sh3'),
        Architecture(name='sh3eb'),
        Architecture(name='sh4'),
        Architecture(name='sh4eb'),
        Architecture(name='sparc64'),
        Architecture(name='x32'),
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_uri_as_char_field'),
    ]

    operations = [
        migrations.RunPython(
            forwards_func,
        ),
    ]
