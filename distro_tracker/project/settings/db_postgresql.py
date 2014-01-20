""" PostgreSQL settings

Defaults to unix socket with user auth.
"""
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'distro-tracker',
        'USER': 'distro-tracker',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    }
}
