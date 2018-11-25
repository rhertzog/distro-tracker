"""SQLite database settings."""

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'distro-tracker.sqlite',
        'TEST': {
            'NAME': 'distro-tracker-test.sqlite',
        }
    }
}
