# -*- coding: utf-8 -*-

from django.db import models, migrations
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AddEmailConfirmation',
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
            name='MergeAccountConfirmation',
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
            name='ResetPasswordConfirmation',
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
            name='User',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(default=django.utils.timezone.now, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('main_email', models.EmailField(unique=True, max_length=255, verbose_name='email')),
                ('first_name', models.CharField(max_length=100, null=True, blank=True)),
                ('last_name', models.CharField(max_length=100, null=True, blank=True)),
                ('is_active', models.BooleanField(default=False)),
                ('is_staff', models.BooleanField(default=False)),
                ('groups', models.ManyToManyField(related_query_name='user', related_name='user_set', to='auth.Group', blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of his/her group.', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(related_query_name='user', related_name='user_set', to='auth.Permission', blank=True, help_text='Specific permissions for this user.', verbose_name='user permissions')),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='UserEmail',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('email', models.EmailField(unique=True, max_length=244)),
                ('user', models.ForeignKey(related_name='emails', to='django_email_accounts.User', null=True, on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='UserRegistrationConfirmation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('confirmation_key', models.CharField(unique=True, max_length=40)),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(related_name='confirmation', to='django_email_accounts.User', on_delete=models.CASCADE)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='resetpasswordconfirmation',
            name='user',
            field=models.ForeignKey(related_name='reset_password_confirmations', to='django_email_accounts.User', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='mergeaccountconfirmation',
            name='initial_user',
            field=models.ForeignKey(related_name='merge_account_initial_set', to='django_email_accounts.User', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='mergeaccountconfirmation',
            name='merge_with',
            field=models.ForeignKey(related_name='merge_account_with_set', to='django_email_accounts.User', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='addemailconfirmation',
            name='email',
            field=models.ForeignKey(to='django_email_accounts.UserEmail', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='addemailconfirmation',
            name='user',
            field=models.ForeignKey(to='django_email_accounts.User', on_delete=models.CASCADE),
            preserve_default=True,
        ),
    ]
