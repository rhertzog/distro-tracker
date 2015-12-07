# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields
import distro_tracker.core.models
import django.db.models.deletion
from django.conf import settings
import distro_tracker.core.utils


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('django_email_accounts', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='ActionItem',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('short_description', models.TextField()),
                ('severity', models.IntegerField(default=2, choices=[(0, 'wishlist'), (1, 'low'), (2, 'normal'), (3, 'high'), (4, 'critical')])),
                ('created_timestamp', models.DateTimeField(auto_now_add=True)),
                ('last_updated_timestamp', models.DateTimeField(auto_now=True)),
                ('extra_data', jsonfield.fields.JSONField(null=True, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='ActionItemType',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('type_name', models.TextField(unique=True, max_length=100)),
                ('full_description_template', models.CharField(max_length=255, null=True, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Architecture',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=30)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='BinaryPackage',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('version', models.CharField(max_length=50, null=True)),
                ('short_description', models.CharField(max_length=300, blank=True)),
                ('long_description', models.TextField(blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='BinaryPackageBugStats',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('stats', jsonfield.fields.JSONField(default=dict, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='BinaryPackageRepositoryEntry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('priority', models.CharField(max_length=50, blank=True)),
                ('section', models.CharField(max_length=50, blank=True)),
                ('architecture', models.ForeignKey(to='core.Architecture')),
                ('binary_package', models.ForeignKey(related_name='repository_entries', to='core.BinaryPackage')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='ContributorName',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=60, blank=True)),
                ('contributor_email', models.ForeignKey(to='django_email_accounts.UserEmail')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='EmailSettings',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='ExtractedSourceFile',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('extracted_file', models.FileField(upload_to=distro_tracker.core.models._extracted_source_file_upload_path)),
                ('name', models.CharField(max_length=100)),
                ('date_extracted', models.DateTimeField(auto_now_add=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Keyword',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=50)),
                ('default', models.BooleanField(default=False)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='MailingList',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=100)),
                ('domain', models.CharField(unique=True, max_length=255)),
                ('archive_url_template', models.CharField(max_length=255, validators=[distro_tracker.core.models.validate_archive_url_template])),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='MembershipConfirmation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('confirmation_key', models.CharField(unique=True, max_length=40)),
                ('date_created', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='MembershipPackageSpecifics',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('_has_keywords', models.BooleanField(default=False)),
                ('muted', models.BooleanField(default=False)),
                ('keywords', models.ManyToManyField(to='core.Keyword')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='News',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('title', models.CharField(max_length=255)),
                ('content_type', models.CharField(default='text/plain', max_length=100)),
                ('_db_content', models.TextField(null=True, blank=True)),
                ('news_file', models.FileField(upload_to=distro_tracker.core.models.news_upload_path, blank=True)),
                ('created_by', models.CharField(max_length=100, blank=True)),
                ('datetime_created', models.DateTimeField(auto_now_add=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='PackageBugStats',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('stats', jsonfield.fields.JSONField(default=dict, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='PackageExtractedInfo',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('key', models.CharField(max_length=50)),
                ('value', jsonfield.fields.JSONField(default=dict)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='PackageName',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=100)),
                ('source', models.BooleanField(default=False)),
                ('binary', models.BooleanField(default=False)),
                ('pseudo', models.BooleanField(default=False)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Repository',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=50)),
                ('shorthand', models.CharField(unique=True, max_length=10)),
                ('uri', models.URLField(verbose_name='URI')),
                ('public_uri', models.URLField(verbose_name='public URI', blank=True)),
                ('suite', models.CharField(max_length=50)),
                ('codename', models.CharField(max_length=50, blank=True)),
                ('components', distro_tracker.core.utils.SpaceDelimitedTextField()),
                ('default', models.BooleanField(default=False)),
                ('optional', models.BooleanField(default=True)),
                ('binary', models.BooleanField(default=True)),
                ('source', models.BooleanField(default=True)),
                ('position', models.IntegerField(default=0)),
                ('architectures', models.ManyToManyField(to='core.Architecture', blank=True)),
            ],
            options={
                'ordering': ('position',),
                'verbose_name_plural': 'repositories',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='RepositoryFlag',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=50, choices=[('hidden', 'Hidden repository')])),
                ('value', models.BooleanField(default=False)),
                ('repository', models.ForeignKey(related_name='flags', to='core.Repository')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='RepositoryRelation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=50, choices=[('derivative', 'Derivative repository (target=parent)'), ('overlay', 'Overlay of target repository')])),
                ('repository', models.ForeignKey(related_name='relations', to='core.Repository')),
                ('target_repository', models.ForeignKey(related_name='reverse_relations', to='core.Repository')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='RunningJob',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('datetime_created', models.DateTimeField(auto_now_add=True)),
                ('initial_task_name', models.CharField(max_length=50)),
                ('additional_parameters', jsonfield.fields.JSONField(null=True)),
                ('state', jsonfield.fields.JSONField(null=True)),
                ('is_complete', models.BooleanField(default=False)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='SourcePackage',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('version', models.CharField(max_length=50)),
                ('standards_version', models.CharField(max_length=550, blank=True)),
                ('dsc_file_name', models.CharField(max_length=255, blank=True)),
                ('directory', models.CharField(max_length=255, blank=True)),
                ('homepage', models.URLField(max_length=255, blank=True)),
                ('vcs', jsonfield.fields.JSONField(default=dict)),
                ('architectures', models.ManyToManyField(to='core.Architecture', blank=True)),
                ('maintainer', models.ForeignKey(related_name='source_package', to='core.ContributorName', null=True)),
                ('uploaders', models.ManyToManyField(related_name='source_packages_uploads_set', to='core.ContributorName')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='SourcePackageDeps',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('build_dep', models.BooleanField(default=False)),
                ('binary_dep', models.BooleanField(default=False)),
                ('details', jsonfield.fields.JSONField(default=dict)),
                ('repository', models.ForeignKey(to='core.Repository')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='SourcePackageRepositoryEntry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('priority', models.CharField(max_length=50, blank=True)),
                ('section', models.CharField(max_length=50, blank=True)),
                ('repository', models.ForeignKey(related_name='source_entries', to='core.Repository')),
                ('source_package', models.ForeignKey(related_name='repository_entries', to='core.SourcePackage')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('active', models.BooleanField(default=True)),
                ('_use_user_default_keywords', models.BooleanField(default=True)),
                ('_keywords', models.ManyToManyField(to='core.Keyword')),
                ('email_settings', models.ForeignKey(to='core.EmailSettings')),
                ('package', models.ForeignKey(to='core.PackageName')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=100)),
                ('slug', models.SlugField(help_text="A team's slug determines its URL", unique=True)),
                ('description', models.TextField(null=True, blank=True)),
                ('url', models.URLField(max_length=255, null=True, blank=True)),
                ('public', models.BooleanField(default=True)),
                ('maintainer_email', models.ForeignKey(on_delete=django.db.models.deletion.SET_NULL, blank=True, to='django_email_accounts.UserEmail', null=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='TeamMembership',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('muted', models.BooleanField(default=False)),
                ('has_membership_keywords', models.BooleanField(default=False)),
                ('default_keywords', models.ManyToManyField(to='core.Keyword')),
                ('team', models.ForeignKey(related_name='team_membership_set', to='core.Team')),
                ('user_email', models.ForeignKey(related_name='membership_set', to='django_email_accounts.UserEmail')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='teammembership',
            unique_together=set([('user_email', 'team')]),
        ),
        migrations.AddField(
            model_name='team',
            name='members',
            field=models.ManyToManyField(related_name='teams', through='core.TeamMembership', to='django_email_accounts.UserEmail'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='team',
            name='owner',
            field=models.ForeignKey(related_name='owned_teams', on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='team',
            name='packages',
            field=models.ManyToManyField(related_name='teams', to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='sourcepackagerepositoryentry',
            unique_together=set([('source_package', 'repository')]),
        ),
        migrations.AlterUniqueTogether(
            name='repositoryrelation',
            unique_together=set([('repository', 'name')]),
        ),
        migrations.AlterUniqueTogether(
            name='repositoryflag',
            unique_together=set([('repository', 'name')]),
        ),
        migrations.AddField(
            model_name='repository',
            name='source_packages',
            field=models.ManyToManyField(to='core.SourcePackage', through='core.SourcePackageRepositoryEntry'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='packagename',
            name='subscriptions',
            field=models.ManyToManyField(to='core.EmailSettings', through='core.Subscription'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='packageextractedinfo',
            name='package',
            field=models.ForeignKey(to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='packageextractedinfo',
            unique_together=set([('key', 'package')]),
        ),
        migrations.AddField(
            model_name='packagebugstats',
            name='package',
            field=models.OneToOneField(related_name='bug_stats', to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='news',
            name='package',
            field=models.ForeignKey(to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='news',
            name='signed_by',
            field=models.ManyToManyField(related_name='signed_news_set', to='core.ContributorName'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='membershippackagespecifics',
            name='membership',
            field=models.ForeignKey(related_name='membership_package_specifics', to='core.TeamMembership'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='membershippackagespecifics',
            name='package_name',
            field=models.ForeignKey(to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='membershippackagespecifics',
            unique_together=set([('membership', 'package_name')]),
        ),
        migrations.AddField(
            model_name='membershipconfirmation',
            name='membership',
            field=models.ForeignKey(to='core.TeamMembership'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='extractedsourcefile',
            name='source_package',
            field=models.ForeignKey(related_name='extracted_source_files', to='core.SourcePackage'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='extractedsourcefile',
            unique_together=set([('source_package', 'name')]),
        ),
        migrations.AddField(
            model_name='emailsettings',
            name='default_keywords',
            field=models.ManyToManyField(to='core.Keyword'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='emailsettings',
            name='user_email',
            field=models.OneToOneField(to='django_email_accounts.UserEmail'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='contributorname',
            unique_together=set([('contributor_email', 'name')]),
        ),
        migrations.AddField(
            model_name='binarypackagerepositoryentry',
            name='repository',
            field=models.ForeignKey(related_name='binary_entries', to='core.Repository'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='binarypackagerepositoryentry',
            unique_together=set([('binary_package', 'repository', 'architecture')]),
        ),
        migrations.AddField(
            model_name='binarypackage',
            name='source_package',
            field=models.ForeignKey(to='core.SourcePackage'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='actionitem',
            name='item_type',
            field=models.ForeignKey(related_name='action_items', to='core.ActionItemType'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='actionitem',
            name='package',
            field=models.ForeignKey(related_name='action_items', to='core.PackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='actionitem',
            unique_together=set([('package', 'item_type')]),
        ),
        migrations.CreateModel(
            name='BinaryPackageName',
            fields=[
            ],
            options={
                'proxy': True,
            },
            bases=('core.packagename',),
        ),
        migrations.AddField(
            model_name='binarypackage',
            name='binary_package_name',
            field=models.ForeignKey(related_name='binary_package_versions', to='core.BinaryPackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='binarypackage',
            unique_together=set([('binary_package_name', 'version')]),
        ),
        migrations.AddField(
            model_name='binarypackagebugstats',
            name='package',
            field=models.OneToOneField(related_name='binary_bug_stats', to='core.BinaryPackageName'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='sourcepackage',
            name='binary_packages',
            field=models.ManyToManyField(to='core.BinaryPackageName', blank=True),
            preserve_default=True,
        ),
        migrations.CreateModel(
            name='EmailNews',
            fields=[
            ],
            options={
                'proxy': True,
            },
            bases=('core.news',),
        ),
        migrations.CreateModel(
            name='PseudoPackageName',
            fields=[
            ],
            options={
                'proxy': True,
            },
            bases=('core.packagename',),
        ),
        migrations.CreateModel(
            name='SourcePackageName',
            fields=[
            ],
            options={
                'proxy': True,
            },
            bases=('core.packagename',),
        ),
        migrations.AddField(
            model_name='sourcepackage',
            name='source_package_name',
            field=models.ForeignKey(related_name='source_package_versions', to='core.SourcePackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='sourcepackage',
            unique_together=set([('source_package_name', 'version')]),
        ),
        migrations.AddField(
            model_name='sourcepackagedeps',
            name='source',
            field=models.ForeignKey(related_name='source_dependencies', to='core.SourcePackageName'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='sourcepackagedeps',
            name='dependency',
            field=models.ForeignKey(related_name='source_dependents', to='core.SourcePackageName'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='sourcepackagedeps',
            unique_together=set([('source', 'dependency', 'repository')]),
        ),
    ]
