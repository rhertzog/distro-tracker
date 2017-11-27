# -*- coding: utf-8 -*-

from django.db import models, migrations


def forwards_func(apps, schema_editor):
    # We get the model from the versioned app registry;
    # if we directly import it, it'll be the wrong version
    Keyword = apps.get_model('core', 'Keyword')
    Architecture = apps.get_model('core', 'Architecture')
    MailingList = apps.get_model('core', 'MailingList')
    db_alias = schema_editor.connection.alias
    Keyword.objects.using(db_alias).bulk_create([
        Keyword(name='default', default=True),
        Keyword(name='bts', default=True),
        Keyword(name='bts-control', default=True),
        Keyword(name='summary', default=True),
        Keyword(name='upload-source', default=True),
        Keyword(name='archive', default=True),
        Keyword(name='contact', default=True),
        Keyword(name='build', default=True),
        Keyword(name='vcs', default=False),
        Keyword(name='translation', default=False),
        Keyword(name='upload-binary', default=False),
        Keyword(name='derivatives', default=False),
        Keyword(name='derivatives-bugs', default=False),
    ])
    Architecture.objects.using(db_alias).bulk_create([
        Architecture(name='amd64'),
        Architecture(name='armel'),
        Architecture(name='armhf'),
        Architecture(name='hurd-i386'),
        Architecture(name='i386'),
        Architecture(name='ia64'),
        Architecture(name='kfreebsd-amd64'),
        Architecture(name='kfreebsd-i386'),
        Architecture(name='mips'),
        Architecture(name='mipsel'),
        Architecture(name='powerpc'),
        Architecture(name='s390'),
        Architecture(name='s390x'),
        Architecture(name='sparc'),
        Architecture(name='all'),
        Architecture(name='any'),
    ])
    MailingList.objects.using(db_alias).bulk_create([
        MailingList(name='debian', domain='lists.debian.org',
                    archive_url_template='https://lists.debian.org/{user}/'),
        MailingList(name='alioth-debian', domain='lists.alioth.debian.org',
                    archive_url_template='https://lists.alioth.debian.org/pipermail/{user}/'),
        MailingList(name='ubuntu', domain='lists.ubuntu.com',
                    archive_url_template='https://lists.ubuntu.com/archives/{user}/'),
        MailingList(name='riseup', domain='lists.riseup.net',
                    archive_url_template='https://lists.riseup.net/www/arc/{user}'),
        MailingList(name='launchpad', domain='lists.launchpad.net',
                    archive_url_template='https://lists.launchpad.net/{user}/'),
        MailingList(name='freedesktop', domain='lists.freedesktop.org',
                    archive_url_template='https://lists.freedesktop.org/archives/{user}/'),
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
