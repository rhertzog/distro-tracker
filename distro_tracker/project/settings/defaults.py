# Copyright 2013-2014 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""Default Django settings for the Distro Tracker project.

Most settings are documented in this file and they are initialized to some
reasonable default values when possible.  They will be extended (and
possibly overriden) by settings from the other modules in this package
depending on the setup selected by the administrator. You likely won't
have to modify that file.

You should instead create local.py to put your site-specific settings (use
local.py.sample as template).

Here are the most important settings:

:py:data:`DISTRO_TRACKER_FQDN`
    The fully qualified domain name of the distro-tracker installation.
    It should be a service-specific DNS entry like "tracker.example.com".
    Defaults to the FQDN of the machine which might not be adequate.

:py:data:`DISTRO_TRACKER_DATA_PATH`
    The directory where distro-tracker will hold its data. The directory is
    further sub-divided in multiple directories for specific use
    cases (e.g. cache, keyring, static, media, logs, templates, etc.).
    Defaults to the "data" sub-directory in the distro-tracker
    base directory (where the code lives).

:py:data:`MEDIA_URL`
    URL that handles the media served from MEDIA_ROOT. Make sure to use a
    trailing slash.
    Examples: "http://example.com/media/", "http://media.example.com/"
    Defaults to "/media/".

:py:data:`STATIC_URL`
    URL prefix for static files.
    Example: "http://example.com/static/", "http://static.example.com/"
    Defaults to "/static/"

Some settings have default values which are computed dynamically from
other settings. Those settings can also be overriden. Here's the list
of those settings.

:py:data:`DISTRO_TRACKER_VENDOR_NAME`
    The name of the vendor. Equivalent to the Vendor field of an
    /etc/dpkg/origins file. Default value computed from the domain
    name of :py:data:`DISTRO_TRACKER_FQDN`.

:py:data:`DISTRO_TRACKER_VENDOR_URL`
    The URL of the vendor. Equivalent to the Vendor-URL field of an
    /etc/dpkg/origins file. Default value computed as "www." + the domain
    name of :py:data:`DISTRO_TRACKER_FQDN`.

:py:data:`STATIC_ROOT`
    Absolute path to the directory static files should be collected to.
    Don't put anything in this directory yourself; store your static files
    in apps' "static/" subdirectories and in STATICFILES_DIRS. Defaults
    to the "static" sub-directory of :py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`MEDIA_ROOT`
    Absolute filesystem path to the directory that will hold user-uploaded
    files. Defaults to the "media" sub-directory of
    :py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_CACHE_DIRECTORY`
    This directory is used to store the locally cached resources.
    Any Distro Tracker app should be able to use this directory to store
    its caches. For example, it is used to store the APT cache of repository
    information and the cache of retrieved Web resources.
    Defaults to the "cache" sub-directory of
    :py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_KEYRING_DIRECTORY`
    This directory should contain a gpg.conf listing the GPG keyrings of known
    public keys. It's used to identify authors of package uploads. Defaults
    to the "keyring" sub-directory of py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_LOG_DIRECTORY`
    This directory will hold log files generated by distro-tracker.
    Defaults to the "logs" sub-directory of py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_MAILDIR_DIRECTORY`
    This directory is used as a mailbox in the Maildir format. All incoming
    mails are stored here. Defaults to the "maildir" sub-directory of
    py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_TEMPLATE_DIRECTORY`
    This directory can hold custom templates that will override the
    templates supplied by distro-tracker. Defaults to the "templates"
    sub-directory of py:data:`DISTRO_TRACKER_DATA_PATH`.

:py:data:`DISTRO_TRACKER_CONTROL_EMAIL`
    The email address which is to receive control emails.
    It does not necessarily have to be in the same domain as specified in
    :py:data:`DISTRO_TRACKER_FQDN`. Defaults to "control@" +
    :py:data:`DISTRO_TRACKER_FQDN`.

:py:data:`DISTRO_TRACKER_CONTACT_EMAIL`
    The email address which is to receive contact emails.
    It does not necessarily have to be in the same domain as specified in
    :py:data:`DISTRO_TRACKER_FQDN`. Defaults to "owner@" +
    :py:data:`DISTRO_TRACKER_FQDN`.

:py:data:`DISTRO_TRACKER_BOUNCES_EMAIL`
    The email address which is to be used as the sender address when no bounce
    processing should happen. It does not necessarily have to be in the same
    domain as specified in :py:data:`DISTRO_TRACKER_FQDN`. Defaults
    to "bounces@" + :py:data:`DISTRO_TRACKER_FQDN`.

:py:data:`DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL`
    The email address which should receive bounces that are likely the
    result of incoming spam.

More settings:
"""
from __future__ import unicode_literals
from django.utils import six
from os.path import dirname

import socket
import os.path

six.add_move(six.MovedModule('mock', 'mock', 'unittest.mock'))

# Django's debug mode, never enable this in production
DEBUG = False
TEMPLATE_DEBUG = DEBUG

BASE_DIR = dirname(dirname(dirname(dirname(__file__))))
DISTRO_TRACKER_DATA_PATH = os.path.join(BASE_DIR, 'data')

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

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
    # 'django.contrib.staticfiles.finders.DefaultStorageFinder',
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
    'django.contrib.messages.middleware.MessageMiddleware',
    # Disabled to allow rendering in iframes
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'django_email_accounts.auth.UserEmailBackend',
)

AUTH_USER_MODEL = 'accounts.User'

ROOT_URLCONF = 'distro_tracker.project.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'distro_tracker.project.wsgi.application'

TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
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
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'django_email_accounts',
    'distro_tracker.html',
    'distro_tracker.core',
    'distro_tracker.accounts',
    'distro_tracker.mail',
)

# See http://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s [%(module)s/%(process)d/%(thread)d] ' +
                      '%(levelname)s: %(message)s'
        },
        'standard': {
            'format': '%(asctime)s %(process)d %(levelname)s: %(message)s'
        },
        'simple': {
            'format': '%(asctime)s %(levelname)s: %(message)s'
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'filters': ['require_debug_true'],
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
        'null': {
            'level': 'DEBUG',
            'class': 'logging.NullHandler',
        },
        'mail.log': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': 'mail.log',
            'formatter': 'standard',
            'when': 'W0',
            'delay': True,
            'backupCount': 52,
        },
        'tasks.log': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': 'tasks.log',
            'formatter': 'standard',
            'when': 'W0',
            'delay': True,
            'backupCount': 52,
        },
        'errors.log': {
            'level': 'ERROR',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': 'errors.log',
            'formatter': 'verbose',
            'when': 'W0',
            'delay': True,
            'backupCount': 52,
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['errors.log', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['errors.log', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security.DisallowedHost': {
            'handlers': ['null'],
            'level': 'ERROR',
            'propagate': False,
        },
        'py.warnings': {
            'handlers': ['console'],
        },
        'distro_tracker': {
            'handlers': ['errors.log', 'console'],
            'level': 'DEBUG',
        },
        'distro_tracker.mail': {
            'handlers': ['mail.log'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'distro_tracker.tasks': {
            'handlers': ['tasks.log'],
            'level': 'DEBUG',
            'propagate': True,
        },
    }
}

# === Distro Tracker specific settings ===

# The fully qualified domain name for the Distro Tracker deployment
DISTRO_TRACKER_FQDN = socket.getfqdn()

#: This file is the trusted.gpg main file to hand out to APT
DISTRO_TRACKER_TRUSTED_GPG_MAIN_FILE = '/etc/apt/trusted.gpg'
#: This directory is trusted.gpg.d directory to hand out to APT
DISTRO_TRACKER_TRUSTED_GPG_PARTS_DIR = '/etc/apt/trusted.gpg.d/'

#: The number of days to tolerate bounced messages for subscribers.
DISTRO_TRACKER_MAX_DAYS_TOLERATE_BOUNCE = 4
#: The number of errors after which the processing of a command email stops.
DISTRO_TRACKER_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS = 5
#: The number of days a command confirmation key should be valid.
DISTRO_TRACKER_CONFIRMATION_EXPIRATION_DAYS = 3

#: The maximum number of news to include in the news panel of a package page
DISTRO_TRACKER_NEWS_PANEL_LIMIT = 30

#: The maximum number of RSS news items to include in the news feed
DISTRO_TRACKER_RSS_ITEM_LIMIT = 30

#: A list of extra headers to include when rendering an email news item.
#: See: :class:`distro_tracker.core.models.EmailNewsRenderer`
DISTRO_TRACKER_EMAIL_NEWS_HEADERS = (
    'Date',
)

#: The maximum size that the
#: :class:`distro_tracker.core.utils.packages.AptCache` should
#: consume for all of its cached source files, given in bytes.
DISTRO_TRACKER_APT_CACHE_MAX_SIZE = 5 * 1024 ** 3  # 5 GiB

#: Whether we accept foo@domain.com as valid emails to dispatch to the foo
#: package
DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS = False

DJANGO_EMAIL_ACCOUNTS_POST_MERGE_HOOK = \
    'distro_tracker.accounts.hooks.post_merge'

#: Whether we include a captcha check on the new user registration form
DJANGO_EMAIL_ACCOUNTS_USE_CAPTCHA = False

# The lambda functions are evaluated at the end of the settings import
# logic. They provide default values to settings which have not yet been
# set (neither above nor in local.py).
_COMPUTE_DEFAULT_SETTINGS = (
    ('DISTRO_TRACKER_VENDOR_NAME',
     lambda t: ".".join(t['DISTRO_TRACKER_FQDN'].split(".")[1:2]).capitalize()),
    ('DISTRO_TRACKER_VENDOR_URL',
     lambda t: "http://www." + ".".join(
         t['DISTRO_TRACKER_FQDN'].split(".", 1)[1:2])),
    ('DISTRO_TRACKER_CONTROL_EMAIL',
     lambda t: 'control@' + t['DISTRO_TRACKER_FQDN']),
    ('DISTRO_TRACKER_CONTACT_EMAIL',
     lambda t: 'owner@' + t['DISTRO_TRACKER_FQDN']),
    ('DISTRO_TRACKER_BOUNCES_EMAIL',
     lambda t: 'bounces@' + t['DISTRO_TRACKER_FQDN']),
    ('DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL',
     lambda t: t['DISTRO_TRACKER_BOUNCES_EMAIL']),
    ('ALLOWED_HOSTS', lambda t: [t['DISTRO_TRACKER_FQDN']]),
    ('ADMINS', lambda t: (
        (t['DISTRO_TRACKER_VENDOR_NAME'] + ' Tracker Admins',
         t['DISTRO_TRACKER_CONTACT_EMAIL']),
    )),
    ('SERVER_EMAIL', lambda t: t['DISTRO_TRACKER_CONTACT_EMAIL']),
    ('DEFAULT_FROM_EMAIL', lambda t: t['DISTRO_TRACKER_CONTACT_EMAIL']),
    ('STATIC_ROOT',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'static')),
    ('MEDIA_ROOT',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'media')),
    ('DISTRO_TRACKER_CACHE_DIRECTORY',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'cache')),
    ('DISTRO_TRACKER_KEYRING_DIRECTORY',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'keyring')),
    ('DISTRO_TRACKER_TEMPLATE_DIRECTORY',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'templates')),
    ('DISTRO_TRACKER_LOG_DIRECTORY',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'logs')),
    ('DISTRO_TRACKER_MAILDIR_DIRECTORY',
     lambda t: os.path.join(t['DISTRO_TRACKER_DATA_PATH'], 'maildir')),
)


def compute_default_settings(target):
    for setting, value in _COMPUTE_DEFAULT_SETTINGS:
        if setting in target:
            continue  # Settings is already defined
        target[setting] = value(target)
    # Extend TEMPLATE_DIRS with our directory
    target['TEMPLATE_DIRS'] += (target['DISTRO_TRACKER_TEMPLATE_DIRECTORY'],)
    # Update LOGGING with full paths
    for handler in target['LOGGING']['handlers'].values():
        if 'filename' not in handler or "/" in handler['filename']:
            continue
        handler['filename'] = os.path.join(
            target['DISTRO_TRACKER_LOG_DIRECTORY'], handler['filename'])
    # Update DATABASES with full paths
    dbconf = target['DATABASES']['default']
    if dbconf['ENGINE'] == 'django.db.backends.sqlite3':
        if '/' not in dbconf['NAME']:
            dbconf['NAME'] = os.path.join(target['DISTRO_TRACKER_DATA_PATH'],
                                          dbconf['NAME'])
        if ('TEST' in dbconf and 'NAME' in dbconf['TEST'] and
                '/' not in dbconf['TEST']['NAME']):
            dbconf['TEST']['NAME'] = os.path.join(
                target['DISTRO_TRACKER_DATA_PATH'], dbconf['TEST']['NAME'])


def GET_INSTANCE_NAME():
    from django.conf import settings
    return "{vendor} Package Tracker".format(
        vendor=settings.DISTRO_TRACKER_VENDOR_NAME)
