""" PostgreSQL settings

Defaults to unix socket with user auth.
"""
import os

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'distro-tracker',
        'USER': os.getlogin(),
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
        'TEST': {
            'NAME': 'distro-tracker-test',
        },
    }
}
