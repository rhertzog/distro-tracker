# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Keyword'
        db.create_table(u'core_keyword', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(unique=True, max_length=50)),
            ('default', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'core', ['Keyword'])

        # Adding model 'EmailUser'
        db.create_table(u'core_emailuser', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('user_email', self.gf('django.db.models.fields.related.OneToOneField')(to=orm['django_email_accounts.UserEmail'], unique=True)),
        ))
        db.send_create_signal(u'core', ['EmailUser'])

        # Adding M2M table for field default_keywords on 'EmailUser'
        m2m_table_name = db.shorten_name(u'core_emailuser_default_keywords')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('emailuser', models.ForeignKey(orm[u'core.emailuser'], null=False)),
            ('keyword', models.ForeignKey(orm[u'core.keyword'], null=False))
        ))
        db.create_unique(m2m_table_name, ['emailuser_id', 'keyword_id'])

        # Adding model 'PackageName'
        db.create_table(u'core_packagename', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(unique=True, max_length=100)),
            ('source', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('binary', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('pseudo', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'core', ['PackageName'])

        # Adding model 'Subscription'
        db.create_table(u'core_subscription', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email_user', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.EmailUser'])),
            ('package', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.PackageName'])),
            ('active', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('_use_user_default_keywords', self.gf('django.db.models.fields.BooleanField')(default=True)),
        ))
        db.send_create_signal(u'core', ['Subscription'])

        # Adding M2M table for field _keywords on 'Subscription'
        m2m_table_name = db.shorten_name(u'core_subscription__keywords')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('subscription', models.ForeignKey(orm[u'core.subscription'], null=False)),
            ('keyword', models.ForeignKey(orm[u'core.keyword'], null=False))
        ))
        db.create_unique(m2m_table_name, ['subscription_id', 'keyword_id'])

        # Adding model 'Architecture'
        db.create_table(u'core_architecture', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(unique=True, max_length=30)),
        ))
        db.send_create_signal(u'core', ['Architecture'])

        # Adding model 'Repository'
        db.create_table(u'core_repository', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(unique=True, max_length=50)),
            ('shorthand', self.gf('django.db.models.fields.CharField')(unique=True, max_length=10)),
            ('uri', self.gf('django.db.models.fields.URLField')(max_length=200)),
            ('public_uri', self.gf('django.db.models.fields.URLField')(max_length=200, blank=True)),
            ('suite', self.gf('django.db.models.fields.CharField')(max_length=50)),
            ('codename', self.gf('django.db.models.fields.CharField')(max_length=50, blank=True)),
            ('components', self.gf('distro_tracker.core.utils.SpaceDelimitedTextField')()),
            ('default', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('optional', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('binary', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('source', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('position', self.gf('django.db.models.fields.IntegerField')(default=0)),
        ))
        db.send_create_signal(u'core', ['Repository'])

        # Adding M2M table for field architectures on 'Repository'
        m2m_table_name = db.shorten_name(u'core_repository_architectures')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('repository', models.ForeignKey(orm[u'core.repository'], null=False)),
            ('architecture', models.ForeignKey(orm[u'core.architecture'], null=False))
        ))
        db.create_unique(m2m_table_name, ['repository_id', 'architecture_id'])

        # Adding model 'ContributorName'
        db.create_table(u'core_contributorname', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('contributor_email', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['django_email_accounts.UserEmail'])),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=60, blank=True)),
        ))
        db.send_create_signal(u'core', ['ContributorName'])

        # Adding unique constraint on 'ContributorName', fields ['contributor_email', 'name']
        db.create_unique(u'core_contributorname', ['contributor_email_id', 'name'])

        # Adding model 'SourcePackage'
        db.create_table(u'core_sourcepackage', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('source_package_name', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'source_package_versions', to=orm['core.PackageName'])),
            ('version', self.gf('django.db.models.fields.CharField')(max_length=50)),
            ('standards_version', self.gf('django.db.models.fields.CharField')(max_length=550, blank=True)),
            ('maintainer', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'source_package', null=True, to=orm['core.ContributorName'])),
            ('dsc_file_name', self.gf('django.db.models.fields.CharField')(max_length=255, blank=True)),
            ('directory', self.gf('django.db.models.fields.CharField')(max_length=255, blank=True)),
            ('homepage', self.gf('django.db.models.fields.URLField')(max_length=255, blank=True)),
            ('vcs', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'core', ['SourcePackage'])

        # Adding unique constraint on 'SourcePackage', fields ['source_package_name', 'version']
        db.create_unique(u'core_sourcepackage', ['source_package_name_id', 'version'])

        # Adding M2M table for field architectures on 'SourcePackage'
        m2m_table_name = db.shorten_name(u'core_sourcepackage_architectures')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('sourcepackage', models.ForeignKey(orm[u'core.sourcepackage'], null=False)),
            ('architecture', models.ForeignKey(orm[u'core.architecture'], null=False))
        ))
        db.create_unique(m2m_table_name, ['sourcepackage_id', 'architecture_id'])

        # Adding M2M table for field binary_packages on 'SourcePackage'
        m2m_table_name = db.shorten_name(u'core_sourcepackage_binary_packages')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('sourcepackage', models.ForeignKey(orm[u'core.sourcepackage'], null=False)),
            ('binarypackagename', models.ForeignKey(orm[u'core.packagename'], null=False))
        ))
        db.create_unique(m2m_table_name, ['sourcepackage_id', 'binarypackagename_id'])

        # Adding M2M table for field uploaders on 'SourcePackage'
        m2m_table_name = db.shorten_name(u'core_sourcepackage_uploaders')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('sourcepackage', models.ForeignKey(orm[u'core.sourcepackage'], null=False)),
            ('contributorname', models.ForeignKey(orm[u'core.contributorname'], null=False))
        ))
        db.create_unique(m2m_table_name, ['sourcepackage_id', 'contributorname_id'])

        # Adding model 'BinaryPackage'
        db.create_table(u'core_binarypackage', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('binary_package_name', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'binary_package_versions', to=orm['core.PackageName'])),
            ('version', self.gf('django.db.models.fields.CharField')(max_length=50, null=True)),
            ('source_package', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.SourcePackage'])),
            ('short_description', self.gf('django.db.models.fields.CharField')(max_length=300, blank=True)),
            ('long_description', self.gf('django.db.models.fields.TextField')(blank=True)),
        ))
        db.send_create_signal(u'core', ['BinaryPackage'])

        # Adding unique constraint on 'BinaryPackage', fields ['binary_package_name', 'version']
        db.create_unique(u'core_binarypackage', ['binary_package_name_id', 'version'])

        # Adding model 'BinaryPackageRepositoryEntry'
        db.create_table(u'core_binarypackagerepositoryentry', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('binary_package', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'repository_entries', to=orm['core.BinaryPackage'])),
            ('repository', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'binary_package_entries', to=orm['core.Repository'])),
            ('architecture', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.Architecture'])),
            ('priority', self.gf('django.db.models.fields.CharField')(max_length=50, blank=True)),
            ('section', self.gf('django.db.models.fields.CharField')(max_length=50, blank=True)),
        ))
        db.send_create_signal(u'core', ['BinaryPackageRepositoryEntry'])

        # Adding unique constraint on 'BinaryPackageRepositoryEntry', fields ['binary_package', 'repository', 'architecture']
        db.create_unique(u'core_binarypackagerepositoryentry', ['binary_package_id', 'repository_id', 'architecture_id'])

        # Adding model 'SourcePackageRepositoryEntry'
        db.create_table(u'core_sourcepackagerepositoryentry', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('source_package', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'repository_entries', to=orm['core.SourcePackage'])),
            ('repository', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.Repository'])),
            ('priority', self.gf('django.db.models.fields.CharField')(max_length=50, blank=True)),
            ('section', self.gf('django.db.models.fields.CharField')(max_length=50, blank=True)),
        ))
        db.send_create_signal(u'core', ['SourcePackageRepositoryEntry'])

        # Adding unique constraint on 'SourcePackageRepositoryEntry', fields ['source_package', 'repository']
        db.create_unique(u'core_sourcepackagerepositoryentry', ['source_package_id', 'repository_id'])

        # Adding model 'ExtractedSourceFile'
        db.create_table(u'core_extractedsourcefile', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('source_package', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'extracted_source_files', to=orm['core.SourcePackage'])),
            ('extracted_file', self.gf('django.db.models.fields.files.FileField')(max_length=100)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=100)),
            ('date_extracted', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
        ))
        db.send_create_signal(u'core', ['ExtractedSourceFile'])

        # Adding unique constraint on 'ExtractedSourceFile', fields ['source_package', 'name']
        db.create_unique(u'core_extractedsourcefile', ['source_package_id', 'name'])

        # Adding model 'PackageExtractedInfo'
        db.create_table(u'core_packageextractedinfo', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.PackageName'])),
            ('key', self.gf('django.db.models.fields.CharField')(max_length=u'50')),
            ('value', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'core', ['PackageExtractedInfo'])

        # Adding unique constraint on 'PackageExtractedInfo', fields ['key', 'package']
        db.create_unique(u'core_packageextractedinfo', ['key', 'package_id'])

        # Adding model 'MailingList'
        db.create_table(u'core_mailinglist', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=100)),
            ('domain', self.gf('django.db.models.fields.CharField')(unique=True, max_length=255)),
            ('archive_url_template', self.gf('django.db.models.fields.CharField')(max_length=255)),
        ))
        db.send_create_signal(u'core', ['MailingList'])

        # Adding model 'RunningJob'
        db.create_table(u'core_runningjob', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('datetime_created', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('initial_task_name', self.gf('django.db.models.fields.CharField')(max_length=50)),
            ('additional_parameters', self.gf('jsonfield.fields.JSONField')(null=True)),
            ('state', self.gf('jsonfield.fields.JSONField')(null=True)),
            ('is_complete', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'core', ['RunningJob'])

        # Adding model 'News'
        db.create_table(u'core_news', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.PackageName'])),
            ('title', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('content_type', self.gf('django.db.models.fields.CharField')(default=u'text/plain', max_length=100)),
            ('_db_content', self.gf('django.db.models.fields.TextField')(null=True, blank=True)),
            ('news_file', self.gf('django.db.models.fields.files.FileField')(max_length=100, blank=True)),
            ('created_by', self.gf('django.db.models.fields.CharField')(max_length=100, blank=True)),
            ('datetime_created', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
        ))
        db.send_create_signal(u'core', ['News'])

        # Adding M2M table for field signed_by on 'News'
        m2m_table_name = db.shorten_name(u'core_news_signed_by')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('news', models.ForeignKey(orm[u'core.news'], null=False)),
            ('contributorname', models.ForeignKey(orm[u'core.contributorname'], null=False))
        ))
        db.create_unique(m2m_table_name, ['news_id', 'contributorname_id'])

        # Adding model 'PackageBugStats'
        db.create_table(u'core_packagebugstats', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'bug_stats', unique=True, to=orm['core.PackageName'])),
            ('stats', self.gf('jsonfield.fields.JSONField')(default={}, blank=True)),
        ))
        db.send_create_signal(u'core', ['PackageBugStats'])

        # Adding model 'BinaryPackageBugStats'
        db.create_table(u'core_binarypackagebugstats', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'binary_bug_stats', unique=True, to=orm['core.PackageName'])),
            ('stats', self.gf('jsonfield.fields.JSONField')(default={}, blank=True)),
        ))
        db.send_create_signal(u'core', ['BinaryPackageBugStats'])

        # Adding model 'ActionItemType'
        db.create_table(u'core_actionitemtype', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('type_name', self.gf('django.db.models.fields.TextField')(unique=True, max_length=100)),
            ('full_description_template', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
        ))
        db.send_create_signal(u'core', ['ActionItemType'])

        # Adding model 'ActionItem'
        db.create_table(u'core_actionitem', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'action_items', to=orm['core.PackageName'])),
            ('item_type', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'action_items', to=orm['core.ActionItemType'])),
            ('short_description', self.gf('django.db.models.fields.TextField')()),
            ('severity', self.gf('django.db.models.fields.IntegerField')(default=2)),
            ('created_timestamp', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('last_updated_timestamp', self.gf('django.db.models.fields.DateTimeField')(auto_now=True, blank=True)),
            ('extra_data', self.gf('jsonfield.fields.JSONField')(null=True, blank=True)),
        ))
        db.send_create_signal(u'core', ['ActionItem'])

        # Adding unique constraint on 'ActionItem', fields ['package', 'item_type']
        db.create_unique(u'core_actionitem', ['package_id', 'item_type_id'])

        # Adding model 'SourcePackageDeps'
        db.create_table(u'core_sourcepackagedeps', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('source', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'source_dependencies', to=orm['core.PackageName'])),
            ('dependency', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'source_dependents', to=orm['core.PackageName'])),
            ('repository', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.Repository'])),
            ('build_dep', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('binary_dep', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('details', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'core', ['SourcePackageDeps'])

        # Adding unique constraint on 'SourcePackageDeps', fields ['source', 'dependency', 'repository']
        db.create_unique(u'core_sourcepackagedeps', ['source_id', 'dependency_id', 'repository_id'])

        # Adding model 'Team'
        db.create_table(u'core_team', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(unique=True, max_length=100)),
            ('slug', self.gf('django.db.models.fields.SlugField')(unique=True, max_length=50)),
            ('maintainer_email', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['django_email_accounts.UserEmail'], null=True, on_delete=models.SET_NULL, blank=True)),
            ('description', self.gf('django.db.models.fields.TextField')(null=True, blank=True)),
            ('url', self.gf('django.db.models.fields.URLField')(max_length=255, null=True, blank=True)),
            ('public', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('owner', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'owned_teams', null=True, on_delete=models.SET_NULL, to=orm['django_email_accounts.User'])),
        ))
        db.send_create_signal(u'core', ['Team'])

        # Adding M2M table for field packages on 'Team'
        m2m_table_name = db.shorten_name(u'core_team_packages')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('team', models.ForeignKey(orm[u'core.team'], null=False)),
            ('packagename', models.ForeignKey(orm[u'core.packagename'], null=False))
        ))
        db.create_unique(m2m_table_name, ['team_id', 'packagename_id'])

        # Adding model 'TeamMembership'
        db.create_table(u'core_teammembership', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email_user', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'membership_set', to=orm['core.EmailUser'])),
            ('team', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'team_membership_set', to=orm['core.Team'])),
            ('muted', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('has_membership_keywords', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'core', ['TeamMembership'])

        # Adding unique constraint on 'TeamMembership', fields ['email_user', 'team']
        db.create_unique(u'core_teammembership', ['email_user_id', 'team_id'])

        # Adding M2M table for field default_keywords on 'TeamMembership'
        m2m_table_name = db.shorten_name(u'core_teammembership_default_keywords')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('teammembership', models.ForeignKey(orm[u'core.teammembership'], null=False)),
            ('keyword', models.ForeignKey(orm[u'core.keyword'], null=False))
        ))
        db.create_unique(m2m_table_name, ['teammembership_id', 'keyword_id'])

        # Adding model 'MembershipPackageSpecifics'
        db.create_table(u'core_membershippackagespecifics', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('membership', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'membership_package_specifics', to=orm['core.TeamMembership'])),
            ('package_name', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.PackageName'])),
            ('_has_keywords', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('muted', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'core', ['MembershipPackageSpecifics'])

        # Adding unique constraint on 'MembershipPackageSpecifics', fields ['membership', 'package_name']
        db.create_unique(u'core_membershippackagespecifics', ['membership_id', 'package_name_id'])

        # Adding M2M table for field keywords on 'MembershipPackageSpecifics'
        m2m_table_name = db.shorten_name(u'core_membershippackagespecifics_keywords')
        db.create_table(m2m_table_name, (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('membershippackagespecifics', models.ForeignKey(orm[u'core.membershippackagespecifics'], null=False)),
            ('keyword', models.ForeignKey(orm[u'core.keyword'], null=False))
        ))
        db.create_unique(m2m_table_name, ['membershippackagespecifics_id', 'keyword_id'])

        # Adding model 'MembershipConfirmation'
        db.create_table(u'core_membershipconfirmation', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('confirmation_key', self.gf('django.db.models.fields.CharField')(unique=True, max_length=40)),
            ('date_created', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('membership', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.TeamMembership'])),
        ))
        db.send_create_signal(u'core', ['MembershipConfirmation'])


    def backwards(self, orm):
        # Removing unique constraint on 'MembershipPackageSpecifics', fields ['membership', 'package_name']
        db.delete_unique(u'core_membershippackagespecifics', ['membership_id', 'package_name_id'])

        # Removing unique constraint on 'TeamMembership', fields ['email_user', 'team']
        db.delete_unique(u'core_teammembership', ['email_user_id', 'team_id'])

        # Removing unique constraint on 'SourcePackageDeps', fields ['source', 'dependency', 'repository']
        db.delete_unique(u'core_sourcepackagedeps', ['source_id', 'dependency_id', 'repository_id'])

        # Removing unique constraint on 'ActionItem', fields ['package', 'item_type']
        db.delete_unique(u'core_actionitem', ['package_id', 'item_type_id'])

        # Removing unique constraint on 'PackageExtractedInfo', fields ['key', 'package']
        db.delete_unique(u'core_packageextractedinfo', ['key', 'package_id'])

        # Removing unique constraint on 'ExtractedSourceFile', fields ['source_package', 'name']
        db.delete_unique(u'core_extractedsourcefile', ['source_package_id', 'name'])

        # Removing unique constraint on 'SourcePackageRepositoryEntry', fields ['source_package', 'repository']
        db.delete_unique(u'core_sourcepackagerepositoryentry', ['source_package_id', 'repository_id'])

        # Removing unique constraint on 'BinaryPackageRepositoryEntry', fields ['binary_package', 'repository', 'architecture']
        db.delete_unique(u'core_binarypackagerepositoryentry', ['binary_package_id', 'repository_id', 'architecture_id'])

        # Removing unique constraint on 'BinaryPackage', fields ['binary_package_name', 'version']
        db.delete_unique(u'core_binarypackage', ['binary_package_name_id', 'version'])

        # Removing unique constraint on 'SourcePackage', fields ['source_package_name', 'version']
        db.delete_unique(u'core_sourcepackage', ['source_package_name_id', 'version'])

        # Removing unique constraint on 'ContributorName', fields ['contributor_email', 'name']
        db.delete_unique(u'core_contributorname', ['contributor_email_id', 'name'])

        # Deleting model 'Keyword'
        db.delete_table(u'core_keyword')

        # Deleting model 'EmailUser'
        db.delete_table(u'core_emailuser')

        # Removing M2M table for field default_keywords on 'EmailUser'
        db.delete_table(db.shorten_name(u'core_emailuser_default_keywords'))

        # Deleting model 'PackageName'
        db.delete_table(u'core_packagename')

        # Deleting model 'Subscription'
        db.delete_table(u'core_subscription')

        # Removing M2M table for field _keywords on 'Subscription'
        db.delete_table(db.shorten_name(u'core_subscription__keywords'))

        # Deleting model 'Architecture'
        db.delete_table(u'core_architecture')

        # Deleting model 'Repository'
        db.delete_table(u'core_repository')

        # Removing M2M table for field architectures on 'Repository'
        db.delete_table(db.shorten_name(u'core_repository_architectures'))

        # Deleting model 'ContributorName'
        db.delete_table(u'core_contributorname')

        # Deleting model 'SourcePackage'
        db.delete_table(u'core_sourcepackage')

        # Removing M2M table for field architectures on 'SourcePackage'
        db.delete_table(db.shorten_name(u'core_sourcepackage_architectures'))

        # Removing M2M table for field binary_packages on 'SourcePackage'
        db.delete_table(db.shorten_name(u'core_sourcepackage_binary_packages'))

        # Removing M2M table for field uploaders on 'SourcePackage'
        db.delete_table(db.shorten_name(u'core_sourcepackage_uploaders'))

        # Deleting model 'BinaryPackage'
        db.delete_table(u'core_binarypackage')

        # Deleting model 'BinaryPackageRepositoryEntry'
        db.delete_table(u'core_binarypackagerepositoryentry')

        # Deleting model 'SourcePackageRepositoryEntry'
        db.delete_table(u'core_sourcepackagerepositoryentry')

        # Deleting model 'ExtractedSourceFile'
        db.delete_table(u'core_extractedsourcefile')

        # Deleting model 'PackageExtractedInfo'
        db.delete_table(u'core_packageextractedinfo')

        # Deleting model 'MailingList'
        db.delete_table(u'core_mailinglist')

        # Deleting model 'RunningJob'
        db.delete_table(u'core_runningjob')

        # Deleting model 'News'
        db.delete_table(u'core_news')

        # Removing M2M table for field signed_by on 'News'
        db.delete_table(db.shorten_name(u'core_news_signed_by'))

        # Deleting model 'PackageBugStats'
        db.delete_table(u'core_packagebugstats')

        # Deleting model 'BinaryPackageBugStats'
        db.delete_table(u'core_binarypackagebugstats')

        # Deleting model 'ActionItemType'
        db.delete_table(u'core_actionitemtype')

        # Deleting model 'ActionItem'
        db.delete_table(u'core_actionitem')

        # Deleting model 'SourcePackageDeps'
        db.delete_table(u'core_sourcepackagedeps')

        # Deleting model 'Team'
        db.delete_table(u'core_team')

        # Removing M2M table for field packages on 'Team'
        db.delete_table(db.shorten_name(u'core_team_packages'))

        # Deleting model 'TeamMembership'
        db.delete_table(u'core_teammembership')

        # Removing M2M table for field default_keywords on 'TeamMembership'
        db.delete_table(db.shorten_name(u'core_teammembership_default_keywords'))

        # Deleting model 'MembershipPackageSpecifics'
        db.delete_table(u'core_membershippackagespecifics')

        # Removing M2M table for field keywords on 'MembershipPackageSpecifics'
        db.delete_table(db.shorten_name(u'core_membershippackagespecifics_keywords'))

        # Deleting model 'MembershipConfirmation'
        db.delete_table(u'core_membershipconfirmation')


    models = {
        u'auth.group': {
            'Meta': {'object_name': 'Group'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '80'}),
            'permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'})
        },
        u'auth.permission': {
            'Meta': {'ordering': "(u'content_type__app_label', u'content_type__model', u'codename')", 'unique_together': "((u'content_type', u'codename'),)", 'object_name': 'Permission'},
            'codename': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['contenttypes.ContentType']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '50'})
        },
        u'contenttypes.contenttype': {
            'Meta': {'ordering': "('name',)", 'unique_together': "(('app_label', 'model'),)", 'object_name': 'ContentType', 'db_table': "'django_content_type'"},
            'app_label': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'})
        },
        u'core.actionitem': {
            'Meta': {'unique_together': "((u'package', u'item_type'),)", 'object_name': 'ActionItem'},
            'created_timestamp': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'extra_data': ('jsonfield.fields.JSONField', [], {'null': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'item_type': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'action_items'", 'to': u"orm['core.ActionItemType']"}),
            'last_updated_timestamp': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'action_items'", 'to': u"orm['core.PackageName']"}),
            'severity': ('django.db.models.fields.IntegerField', [], {'default': '2'}),
            'short_description': ('django.db.models.fields.TextField', [], {})
        },
        u'core.actionitemtype': {
            'Meta': {'object_name': 'ActionItemType'},
            'full_description_template': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'type_name': ('django.db.models.fields.TextField', [], {'unique': 'True', 'max_length': '100'})
        },
        u'core.architecture': {
            'Meta': {'object_name': 'Architecture'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '30'})
        },
        u'core.binarypackage': {
            'Meta': {'unique_together': "((u'binary_package_name', u'version'),)", 'object_name': 'BinaryPackage'},
            'binary_package_name': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'binary_package_versions'", 'to': u"orm['core.PackageName']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'long_description': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'short_description': ('django.db.models.fields.CharField', [], {'max_length': '300', 'blank': 'True'}),
            'source_package': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.SourcePackage']"}),
            'version': ('django.db.models.fields.CharField', [], {'max_length': '50', 'null': 'True'})
        },
        u'core.binarypackagebugstats': {
            'Meta': {'object_name': 'BinaryPackageBugStats'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'binary_bug_stats'", 'unique': 'True', 'to': u"orm['core.PackageName']"}),
            'stats': ('jsonfield.fields.JSONField', [], {'default': '{}', 'blank': 'True'})
        },
        u'core.binarypackagerepositoryentry': {
            'Meta': {'unique_together': "((u'binary_package', u'repository', u'architecture'),)", 'object_name': 'BinaryPackageRepositoryEntry'},
            'architecture': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.Architecture']"}),
            'binary_package': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'repository_entries'", 'to': u"orm['core.BinaryPackage']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'priority': ('django.db.models.fields.CharField', [], {'max_length': '50', 'blank': 'True'}),
            'repository': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'binary_package_entries'", 'to': u"orm['core.Repository']"}),
            'section': ('django.db.models.fields.CharField', [], {'max_length': '50', 'blank': 'True'})
        },
        u'core.contributorname': {
            'Meta': {'unique_together': "((u'contributor_email', u'name'),)", 'object_name': 'ContributorName'},
            'contributor_email': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['django_email_accounts.UserEmail']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '60', 'blank': 'True'})
        },
        u'core.emailuser': {
            'Meta': {'object_name': 'EmailUser'},
            'default_keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'user_email': ('django.db.models.fields.related.OneToOneField', [], {'to': u"orm['django_email_accounts.UserEmail']", 'unique': 'True'})
        },
        u'core.extractedsourcefile': {
            'Meta': {'unique_together': "((u'source_package', u'name'),)", 'object_name': 'ExtractedSourceFile'},
            'date_extracted': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'extracted_file': ('django.db.models.fields.files.FileField', [], {'max_length': '100'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'source_package': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'extracted_source_files'", 'to': u"orm['core.SourcePackage']"})
        },
        u'core.keyword': {
            'Meta': {'object_name': 'Keyword'},
            'default': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '50'})
        },
        u'core.mailinglist': {
            'Meta': {'object_name': 'MailingList'},
            'archive_url_template': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'domain': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '255'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'})
        },
        u'core.membershipconfirmation': {
            'Meta': {'object_name': 'MembershipConfirmation'},
            'confirmation_key': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '40'}),
            'date_created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'membership': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.TeamMembership']"})
        },
        u'core.membershippackagespecifics': {
            'Meta': {'unique_together': "((u'membership', u'package_name'),)", 'object_name': 'MembershipPackageSpecifics'},
            '_has_keywords': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            'membership': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'membership_package_specifics'", 'to': u"orm['core.TeamMembership']"}),
            'muted': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'package_name': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.PackageName']"})
        },
        u'core.news': {
            'Meta': {'object_name': 'News'},
            '_db_content': ('django.db.models.fields.TextField', [], {'null': 'True', 'blank': 'True'}),
            'content_type': ('django.db.models.fields.CharField', [], {'default': "u'text/plain'", 'max_length': '100'}),
            'created_by': ('django.db.models.fields.CharField', [], {'max_length': '100', 'blank': 'True'}),
            'datetime_created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'news_file': ('django.db.models.fields.files.FileField', [], {'max_length': '100', 'blank': 'True'}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.PackageName']"}),
            'signed_by': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "u'signed_news_set'", 'symmetrical': 'False', 'to': u"orm['core.ContributorName']"}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '255'})
        },
        u'core.packagebugstats': {
            'Meta': {'object_name': 'PackageBugStats'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'bug_stats'", 'unique': 'True', 'to': u"orm['core.PackageName']"}),
            'stats': ('jsonfield.fields.JSONField', [], {'default': '{}', 'blank': 'True'})
        },
        u'core.packageextractedinfo': {
            'Meta': {'unique_together': "((u'key', u'package'),)", 'object_name': 'PackageExtractedInfo'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'key': ('django.db.models.fields.CharField', [], {'max_length': "u'50'"}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.PackageName']"}),
            'value': ('jsonfield.fields.JSONField', [], {'default': '{}'})
        },
        u'core.packagename': {
            'Meta': {'object_name': 'PackageName'},
            'binary': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '100'}),
            'pseudo': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'source': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'subscriptions': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.EmailUser']", 'through': u"orm['core.Subscription']", 'symmetrical': 'False'})
        },
        u'core.repository': {
            'Meta': {'ordering': "(u'position',)", 'object_name': 'Repository'},
            'architectures': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Architecture']", 'symmetrical': 'False', 'blank': 'True'}),
            'binary': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'codename': ('django.db.models.fields.CharField', [], {'max_length': '50', 'blank': 'True'}),
            'components': ('distro_tracker.core.utils.SpaceDelimitedTextField', [], {}),
            'default': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '50'}),
            'optional': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'position': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'public_uri': ('django.db.models.fields.URLField', [], {'max_length': '200', 'blank': 'True'}),
            'shorthand': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '10'}),
            'source': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'source_packages': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.SourcePackage']", 'through': u"orm['core.SourcePackageRepositoryEntry']", 'symmetrical': 'False'}),
            'suite': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'uri': ('django.db.models.fields.URLField', [], {'max_length': '200'})
        },
        u'core.runningjob': {
            'Meta': {'object_name': 'RunningJob'},
            'additional_parameters': ('jsonfield.fields.JSONField', [], {'null': 'True'}),
            'datetime_created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'initial_task_name': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            'is_complete': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'state': ('jsonfield.fields.JSONField', [], {'null': 'True'})
        },
        u'core.sourcepackage': {
            'Meta': {'unique_together': "((u'source_package_name', u'version'),)", 'object_name': 'SourcePackage'},
            'architectures': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Architecture']", 'symmetrical': 'False', 'blank': 'True'}),
            'binary_packages': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.PackageName']", 'symmetrical': 'False', 'blank': 'True'}),
            'directory': ('django.db.models.fields.CharField', [], {'max_length': '255', 'blank': 'True'}),
            'dsc_file_name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'blank': 'True'}),
            'homepage': ('django.db.models.fields.URLField', [], {'max_length': '255', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'maintainer': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'source_package'", 'null': 'True', 'to': u"orm['core.ContributorName']"}),
            'source_package_name': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'source_package_versions'", 'to': u"orm['core.PackageName']"}),
            'standards_version': ('django.db.models.fields.CharField', [], {'max_length': '550', 'blank': 'True'}),
            'uploaders': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "u'source_packages_uploads_set'", 'symmetrical': 'False', 'to': u"orm['core.ContributorName']"}),
            'vcs': ('jsonfield.fields.JSONField', [], {'default': '{}'}),
            'version': ('django.db.models.fields.CharField', [], {'max_length': '50'})
        },
        u'core.sourcepackagedeps': {
            'Meta': {'unique_together': "((u'source', u'dependency', u'repository'),)", 'object_name': 'SourcePackageDeps'},
            'binary_dep': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'build_dep': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'dependency': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'source_dependents'", 'to': u"orm['core.PackageName']"}),
            'details': ('jsonfield.fields.JSONField', [], {'default': '{}'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'repository': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.Repository']"}),
            'source': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'source_dependencies'", 'to': u"orm['core.PackageName']"})
        },
        u'core.sourcepackagerepositoryentry': {
            'Meta': {'unique_together': "((u'source_package', u'repository'),)", 'object_name': 'SourcePackageRepositoryEntry'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'priority': ('django.db.models.fields.CharField', [], {'max_length': '50', 'blank': 'True'}),
            'repository': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.Repository']"}),
            'section': ('django.db.models.fields.CharField', [], {'max_length': '50', 'blank': 'True'}),
            'source_package': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'repository_entries'", 'to': u"orm['core.SourcePackage']"})
        },
        u'core.subscription': {
            'Meta': {'object_name': 'Subscription'},
            '_keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            '_use_user_default_keywords': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'email_user': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.EmailUser']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.PackageName']"})
        },
        u'core.team': {
            'Meta': {'object_name': 'Team'},
            'description': ('django.db.models.fields.TextField', [], {'null': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'maintainer_email': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['django_email_accounts.UserEmail']", 'null': 'True', 'on_delete': 'models.SET_NULL', 'blank': 'True'}),
            'members': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "u'teams'", 'symmetrical': 'False', 'through': u"orm['core.TeamMembership']", 'to': u"orm['core.EmailUser']"}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '100'}),
            'owner': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'owned_teams'", 'null': 'True', 'on_delete': 'models.SET_NULL', 'to': u"orm['django_email_accounts.User']"}),
            'packages': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "u'teams'", 'symmetrical': 'False', 'to': u"orm['core.PackageName']"}),
            'public': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'url': ('django.db.models.fields.URLField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'})
        },
        u'core.teammembership': {
            'Meta': {'unique_together': "((u'email_user', u'team'),)", 'object_name': 'TeamMembership'},
            'default_keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            'email_user': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'membership_set'", 'to': u"orm['core.EmailUser']"}),
            'has_membership_keywords': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'muted': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'team': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'team_membership_set'", 'to': u"orm['core.Team']"})
        },
        u'django_email_accounts.user': {
            'Meta': {'object_name': 'User'},
            'first_name': ('django.db.models.fields.CharField', [], {'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'groups': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['auth.Group']", 'symmetrical': 'False', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_active': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'is_staff': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'is_superuser': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'last_login': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'last_name': ('django.db.models.fields.CharField', [], {'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'main_email': ('django.db.models.fields.EmailField', [], {'unique': 'True', 'max_length': '255'}),
            'password': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'user_permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'})
        },
        u'django_email_accounts.useremail': {
            'Meta': {'object_name': 'UserEmail'},
            'email': ('django.db.models.fields.EmailField', [], {'unique': 'True', 'max_length': '244'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'user': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'emails'", 'null': 'True', 'to': u"orm['django_email_accounts.User']"})
        }
    }

    complete_apps = ['core']
