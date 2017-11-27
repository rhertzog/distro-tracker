# -*- coding: utf-8 -*-

from django.db import models, migrations
import jsonfield.fields
import distro_tracker.core.utils


class Migration(migrations.Migration):

    dependencies = [
        ('django_email_accounts', '0001_initial'),
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='BuildLogCheckStats',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('stats', jsonfield.fields.JSONField(default=dict)),
                ('package', models.OneToOneField(related_name='build_logcheck_stats', to='core.SourcePackageName', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='DebianContributor',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('agree_with_low_threshold_nmu', models.BooleanField(default=False)),
                ('is_debian_maintainer', models.BooleanField(default=False)),
                ('allowed_packages', distro_tracker.core.utils.SpaceDelimitedTextField(blank=True)),
                ('email', models.OneToOneField(to='django_email_accounts.UserEmail', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='LintianStats',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('stats', jsonfield.fields.JSONField(default=dict)),
                ('package', models.OneToOneField(related_name='lintian_stats', to='core.PackageName', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='PackageExcuses',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('excuses', jsonfield.fields.JSONField(default=dict)),
                ('package', models.OneToOneField(related_name='excuses', to='core.PackageName', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='PackageTransition',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('transition_name', models.CharField(max_length=50)),
                ('status', models.CharField(max_length=50, null=True, blank=True)),
                ('reject', models.BooleanField(default=False)),
                ('package', models.ForeignKey(related_name='package_transitions', to='core.PackageName', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='UbuntuPackage',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('version', models.TextField(max_length=100)),
                ('bugs', jsonfield.fields.JSONField(null=True, blank=True)),
                ('patch_diff', jsonfield.fields.JSONField(null=True, blank=True)),
                ('package', models.OneToOneField(related_name='ubuntu_package', to='core.PackageName', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
