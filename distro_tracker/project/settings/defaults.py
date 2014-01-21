# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""Default Django settings for the PTS project.

Most settings are documented in this file and they are initialized to some
reasonable default values when possible.  They will be extended (and
possibly overriden) by settings from the other modules in this package
depending on the setup selected by the administrator. You likely won't
have to modify that file.

You should instead modify local.py to put your site-specific settings.
"""
from __future__ import unicode_literals
from django.utils import six
from os.path import dirname

import socket
import os.path

six.add_move(six.MovedModule('mock', 'mock', 'unittest.mock'))

DEBUG = False
TEMPLATE_DEBUG = DEBUG

DISTRO_TRACKER_BASE_PATH = dirname(dirname(dirname(dirname(__file__))))

ADMINS = (
    # ('Your Name', 'your_email@example.com'),
)

MANAGERS = ADMINS

#: The Django DATABASES setting
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'distro-tracker.sqlite'),
        # The following settings are not used with sqlite3:
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    }
}

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

#: Absolute path to the directory static files should be collected to.
#: Don't put anything in this directory yourself; store your static files
#: in apps' "static/" subdirectories and in STATICFILES_DIRS.
STATIC_ROOT = os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'static')

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = '/media/'

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"
STATIC_URL = '/static/'

# Additional locations of static files
STATICFILES_DIRS = (
    # Put strings here, like "/home/html/static" or "C:/www/django/static".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
)

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
#    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# Make this unique, and don't share it with anybody.
try:
    with open('/var/lib/distro-tracker/key', 'r') as f:
        SECRET_KEY = f.read().strip()
except IOError:
    SECRET_KEY = 'etu2#5lv=!0(g9l31mw=cpwhioy!egg60lb5o3_67d83#(wu-u'

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    ('django.template.loaders.cached.Loader', (
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader'
    )),
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'distro_tracker.vendor.debian.sso_auth.DebianSsoUserMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # Uncomment the next line for simple clickjacking protection:
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'distro_tracker.vendor.debian.sso_auth.DebianSsoUserBackend',
    'django_email_accounts.auth.EmailUserBackend',
)

AUTH_USER_MODEL = 'accounts.User'

ROOT_URLCONF = 'distro_tracker.project.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'distro_tracker.project.wsgi.application'

TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
    os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'templates'),
)
TEMPLATE_CONTEXT_PROCESSORS = (
    'django.contrib.auth.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.i18n',
    'django.core.context_processors.media',
    'django.core.context_processors.static',
    'django.core.context_processors.tz',
    'django.contrib.messages.context_processors.messages',
    'django.core.context_processors.request',
    'distro_tracker.core.context_processors.extras',
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'django_email_accounts',
    'south',
    'distro_tracker.core',
    'distro_tracker.accounts',
    'distro_tracker.mail',
)

# See http://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s '
                      '%(process)d %(thread)d %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
        'simple-timestamp': {
            'format': '%(levelname)s %(asctime)s %(message)s'
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'console-timestamp': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple-timestamp',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
        'distro_tracker.mail': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'distro_tracker.core.panels': {
            'handlers': ['console-timestamp'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'distro_tracker.core.tasks': {
            'handlers': ['console-timestamp'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'distro_tracker.core.retrieve_data': {
            'handlers': ['console-timestamp'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'distro_tracker.vendor.debian': {
            'handlers': ['console-timestamp'],
            'level': 'DEBUG',
            'propagate': True,
        }
    }
}

#: Hosts/domain names that are valid for this site; required if DEBUG is False
#: See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts
ALLOWED_HOSTS = [ socket.getfqdn() ]

## PTS specific settings

#: The fully qualified domain name for the PTS deployment
DISTRO_TRACKER_FQDN = socket.getfqdn()

#: The name of the vendor. Equivalent to the Vendor field of an
#: /etc/dpkg/origins file.
DISTRO_TRACKER_VENDOR_NAME = ".".join(DISTRO_TRACKER_FQDN.split(".")[1:2]).capitalize()
#: The URL of the vendor. Equivalent to the Vendor-URL field of an
#: /etc/dpkg/origins file."""
DISTRO_TRACKER_VENDOR_URL = "http://www." + ".".join(DISTRO_TRACKER_FQDN.split(".", 1)[1:2])

#: This directory is used to store the locally cached resources.
#: Any PTS app should be able to use this directory to store its caches.
#: For example, it is used to store the APT cache of repository information and
#: the cache of retrieved Web resources.
DISTRO_TRACKER_CACHE_DIRECTORY = os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'cache')

#: This directory should contain a GPG keyring of known public keys
DISTRO_TRACKER_KEYRING_DIRECTORY = os.path.join(DISTRO_TRACKER_BASE_PATH, 'data', 'keyring')

#: The number of days to tolerate bounced messages for subscribers.
DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE = 4
#: The number of errors after which the processing of a command email stops.
DISTRO_TRACKER_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS = 5
#: The number of days a command confirmation key should be valid.
DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS = 3

#: The email address which is to receive control emails.
#: It does not necessarily have to be in the same domain as specified in
#: :py:data:`distro_tracker.project.settings.DISTRO_TRACKER_FQDN`.
DISTRO_TRACKER_CONTROL_EMAIL = 'control@' + DISTRO_TRACKER_FQDN
#: The email address which is to receive contact emails.
#: It does not necessarily have to be in the same domain as specified in
#: :py:data:`distro_tracker.project.settings.DISTRO_TRACKER_FQDN`.
DISTRO_TRACKER_CONTACT_EMAIL = 'owner@' + DISTRO_TRACKER_FQDN
#: The email address which is to be used as the sender address when no bounce
#: processing should happen.
#: It does not necessarily have to be in the same domain as specified in
#: :py:data:`distro_tracker.project.settings.DISTRO_TRACKER_FQDN`.
DISTRO_TRACKER_BOUNCES_EMAIL = 'bounces@' + DISTRO_TRACKER_FQDN
#: The email address which should receive bounces that are a result of spam.
DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL = DISTRO_TRACKER_BOUNCES_EMAIL

#: The maximum number of news to include in the news panel of a package page
DISTRO_TRACKER_NEWS_PANEL_LIMIT = 30

#: The maximum number of RSS news items to include in the news feed
DISTRO_TRACKER_RSS_ITEM_LIMIT = 30

#: A list of extra headers to include when rendering an email news item.
#: See: :class:`distro_tracker.core.models.EmailNewsRenderer`
DISTRO_TRACKER_EMAIL_NEWS_HEADERS = (
    'Date',
)

#: The maximum size that the :class:`distro_tracker.core.utils.packages.AptCache` should
#: consume for all of its cached source files, given in bytes.
DISTRO_TRACKER_APT_CACHE_MAX_SIZE = 5 * 1024 ** 3  # 5 GiB

DJANGO_EMAIL_ACCOUNTS_POST_MERGE_HOOK = 'distro_tracker.accounts.hooks.post_merge'
