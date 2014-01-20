# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'DebianContributor'
        db.create_table(u'debian_debiancontributor', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email', self.gf('django.db.models.fields.related.OneToOneField')(to=orm['django_email_accounts.UserEmail'], unique=True)),
            ('agree_with_low_threshold_nmu', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('is_debian_maintainer', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('allowed_packages', self.gf('distro_tracker.core.utils.SpaceDelimitedTextField')(blank=True)),
        ))
        db.send_create_signal(u'debian', ['DebianContributor'])

        # Adding model 'LintianStats'
        db.create_table(u'debian_lintianstats', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'lintian_stats', unique=True, to=orm['core.PackageName'])),
            ('stats', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'debian', ['LintianStats'])

        # Adding model 'PackageTransition'
        db.create_table(u'debian_packagetransition', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.ForeignKey')(related_name=u'package_transitions', to=orm['core.PackageName'])),
            ('transition_name', self.gf('django.db.models.fields.CharField')(max_length=50)),
            ('status', self.gf('django.db.models.fields.CharField')(max_length=50, null=True, blank=True)),
            ('reject', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal(u'debian', ['PackageTransition'])

        # Adding model 'PackageExcuses'
        db.create_table(u'debian_packageexcuses', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'excuses', unique=True, to=orm['core.PackageName'])),
            ('excuses', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'debian', ['PackageExcuses'])

        # Adding model 'BuildLogCheckStats'
        db.create_table(u'debian_buildlogcheckstats', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'build_logcheck_stats', unique=True, to=orm['core.PackageName'])),
            ('stats', self.gf('jsonfield.fields.JSONField')(default={})),
        ))
        db.send_create_signal(u'debian', ['BuildLogCheckStats'])

        # Adding model 'UbuntuPackage'
        db.create_table(u'debian_ubuntupackage', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('package', self.gf('django.db.models.fields.related.OneToOneField')(related_name=u'ubuntu_package', unique=True, to=orm['core.PackageName'])),
            ('version', self.gf('django.db.models.fields.TextField')(max_length=100)),
            ('bugs', self.gf('jsonfield.fields.JSONField')(null=True, blank=True)),
            ('patch_diff', self.gf('jsonfield.fields.JSONField')(null=True, blank=True)),
        ))
        db.send_create_signal(u'debian', ['UbuntuPackage'])


    def backwards(self, orm):
        # Deleting model 'DebianContributor'
        db.delete_table(u'debian_debiancontributor')

        # Deleting model 'LintianStats'
        db.delete_table(u'debian_lintianstats')

        # Deleting model 'PackageTransition'
        db.delete_table(u'debian_packagetransition')

        # Deleting model 'PackageExcuses'
        db.delete_table(u'debian_packageexcuses')

        # Deleting model 'BuildLogCheckStats'
        db.delete_table(u'debian_buildlogcheckstats')

        # Deleting model 'UbuntuPackage'
        db.delete_table(u'debian_ubuntupackage')


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
        u'core.emailuser': {
            'Meta': {'object_name': 'EmailUser'},
            'default_keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'user_email': ('django.db.models.fields.related.OneToOneField', [], {'to': u"orm['django_email_accounts.UserEmail']", 'unique': 'True'})
        },
        u'core.keyword': {
            'Meta': {'object_name': 'Keyword'},
            'default': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '50'})
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
        u'core.subscription': {
            'Meta': {'object_name': 'Subscription'},
            '_keywords': ('django.db.models.fields.related.ManyToManyField', [], {'to': u"orm['core.Keyword']", 'symmetrical': 'False'}),
            '_use_user_default_keywords': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'email_user': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.EmailUser']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.PackageName']"})
        },
        u'debian.buildlogcheckstats': {
            'Meta': {'object_name': 'BuildLogCheckStats'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'build_logcheck_stats'", 'unique': 'True', 'to': u"orm['core.PackageName']"}),
            'stats': ('jsonfield.fields.JSONField', [], {'default': '{}'})
        },
        u'debian.debiancontributor': {
            'Meta': {'object_name': 'DebianContributor'},
            'agree_with_low_threshold_nmu': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'allowed_packages': ('distro_tracker.core.utils.SpaceDelimitedTextField', [], {'blank': 'True'}),
            'email': ('django.db.models.fields.related.OneToOneField', [], {'to': u"orm['django_email_accounts.UserEmail']", 'unique': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_debian_maintainer': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        u'debian.lintianstats': {
            'Meta': {'object_name': 'LintianStats'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'lintian_stats'", 'unique': 'True', 'to': u"orm['core.PackageName']"}),
            'stats': ('jsonfield.fields.JSONField', [], {'default': '{}'})
        },
        u'debian.packageexcuses': {
            'Meta': {'object_name': 'PackageExcuses'},
            'excuses': ('jsonfield.fields.JSONField', [], {'default': '{}'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'excuses'", 'unique': 'True', 'to': u"orm['core.PackageName']"})
        },
        u'debian.packagetransition': {
            'Meta': {'object_name': 'PackageTransition'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "u'package_transitions'", 'to': u"orm['core.PackageName']"}),
            'reject': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'status': ('django.db.models.fields.CharField', [], {'max_length': '50', 'null': 'True', 'blank': 'True'}),
            'transition_name': ('django.db.models.fields.CharField', [], {'max_length': '50'})
        },
        u'debian.ubuntupackage': {
            'Meta': {'object_name': 'UbuntuPackage'},
            'bugs': ('jsonfield.fields.JSONField', [], {'null': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'package': ('django.db.models.fields.related.OneToOneField', [], {'related_name': "u'ubuntu_package'", 'unique': 'True', 'to': u"orm['core.PackageName']"}),
            'patch_diff': ('jsonfield.fields.JSONField', [], {'null': 'True', 'blank': 'True'}),
            'version': ('django.db.models.fields.TextField', [], {'max_length': '100'})
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

    complete_apps = ['debian']