"""
Appropriate settings to run during development.

When running in development mode, selected.py should point to this file.
"""

from .defaults import INSTALLED_APPS, MIDDLEWARE_CLASSES

DEBUG = True
TEMPLATE_DEBUG = True

ADMINS = ()

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

SITE_URL = 'http://127.0.0.1:8000'

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

XHR_SIMULATED_DELAY = 0.5

MIDDLEWARE_CLASSES += (
    'debug_toolbar.middleware.DebugToolbarMiddleware',
)

INSTALLED_APPS += (
    'debug_toolbar',
)

DEBUG_TOOLBAR_CONFIG = {
    'HIDE_DJANGO_SQL': True,
    'INTERCEPT_REDIRECTS': False,
    'SHOW_TEMPLATE_CONTEXT': False,
}

DEBUG_TOOLBAR_PANELS = (
    'debug_toolbar.panels.version.VersionDebugPanel',
    'debug_toolbar.panels.timer.TimerDebugPanel',
    'debug_toolbar.panels.settings_vars.SettingsVarsDebugPanel',
    'debug_toolbar.panels.headers.HeaderDebugPanel',
    'debug_toolbar.panels.request_vars.RequestVarsDebugPanel',
    'debug_toolbar.panels.sql.SQLDebugPanel',
    'debug_toolbar.panels.logger.LoggingPanel',
)

DATABASE_ENGINE = 'dummy_for_debug_toolbar'
