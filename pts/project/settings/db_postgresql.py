""" PostgreSQL settings

Defaults to unix socket with user auth.
"""
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'pts',
        'USER': 'pts',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    }
}
