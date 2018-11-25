"""
PostgreSQL settings.

Defaults to unix socket with user auth.
"""
import getpass

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'distro-tracker',
        'USER': getpass.getuser(),
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
        'TEST': {
            'NAME': 'distro-tracker-test',
        },
    }
}
