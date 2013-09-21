# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'CommandConfirmation'
        db.create_table(u'mail_commandconfirmation', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('confirmation_key', self.gf('django.db.models.fields.CharField')(unique=True, max_length=40)),
            ('date_created', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('commands', self.gf('django.db.models.fields.TextField')()),
        ))
        db.send_create_signal(u'mail', ['CommandConfirmation'])

        # Adding model 'BounceStats'
        db.create_table(u'mail_bouncestats', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email_user', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['core.EmailUser'])),
            ('mails_sent', self.gf('django.db.models.fields.IntegerField')(default=0)),
            ('mails_bounced', self.gf('django.db.models.fields.IntegerField')(default=0)),
            ('date', self.gf('django.db.models.fields.DateField')()),
        ))
        db.send_create_signal(u'mail', ['BounceStats'])

        # Adding unique constraint on 'BounceStats', fields ['email_user', 'date']
        db.create_unique(u'mail_bouncestats', ['email_user_id', 'date'])


    def backwards(self, orm):
        # Removing unique constraint on 'BounceStats', fields ['email_user', 'date']
        db.delete_unique(u'mail_bouncestats', ['email_user_id', 'date'])

        # Deleting model 'CommandConfirmation'
        db.delete_table(u'mail_commandconfirmation')

        # Deleting model 'BounceStats'
        db.delete_table(u'mail_bouncestats')


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
        },
        u'mail.bouncestats': {
            'Meta': {'ordering': "[u'-date']", 'unique_together': "((u'email_user', u'date'),)", 'object_name': 'BounceStats'},
            'date': ('django.db.models.fields.DateField', [], {}),
            'email_user': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['core.EmailUser']"}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'mails_bounced': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'mails_sent': ('django.db.models.fields.IntegerField', [], {'default': '0'})
        },
        u'mail.commandconfirmation': {
            'Meta': {'object_name': 'CommandConfirmation'},
            'commands': ('django.db.models.fields.TextField', [], {}),
            'confirmation_key': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '40'}),
            'date_created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'})
        }
    }

    complete_apps = ['mail']