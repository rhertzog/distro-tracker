# -*- coding: utf-8 -*-

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('django_email_accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='BounceStats',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('mails_sent', models.IntegerField(default=0)),
                ('mails_bounced', models.IntegerField(default=0)),
                ('date', models.DateField()),
            ],
            options={
                'ordering': ['-date'],
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='CommandConfirmation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('confirmation_key', models.CharField(unique=True, max_length=40)),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('commands', models.TextField()),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='UserEmailBounceStats',
            fields=[
            ],
            options={
                'proxy': True,
            },
            bases=('django_email_accounts.useremail',),
        ),
        migrations.AddField(
            model_name='bouncestats',
            name='user_email',
            field=models.ForeignKey(to='mail.UserEmailBounceStats', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='bouncestats',
            unique_together=set([('user_email', 'date')]),
        ),
    ]
