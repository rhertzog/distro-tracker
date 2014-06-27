.. _webserver:

Integration with a Web Server
=============================

.. _apache_webserver:

Apache2
-------

Distro Tracker can be deployed as any other Django project on Apache. For more information
you can see the following
`link <https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/modwsgi/>`_.

After installing mod_wsgi, a minimal configuration would be to include a new
file in sites-available with the following settings::

    WSGIDaemonProcess distro_tracker.some.domain python-path=/path/to/distro_tracker user=distro-tracker group=distro-tracker home=/ processes=4 threads=5 maximum-requests=5000 inactivity-timeout=1800 umask=0007 display-name=wsgi-distro_tracker.some.domain

    <VirtualHost *:80>
            ServerAdmin owner@distro_tracker.some.domain
            ServerName distro_tracker.some.domain

            DocumentRoot /path/to/assets/
            # To make sure all static file assets with no extension
            # (such as extracted source files) have the correct Content-Type
            DefaultType text/plain
            AddDefaultCharset utf-8

            ErrorLog ${APACHE_LOG_DIR}/distro_tracker.some.domain-error.log
            LogLevel warn

            CustomLog ${APACHE_LOG_DIR}/distro_tracker.some.domain-access.log combined

            WSGIScriptAlias / /path/to/distro_tracker/project/wsgi.py
            WSGIProcessGroup distro_tracker.some.domain

            Alias /static/ /path/to/assets/static/
            Alias /media/ /path/to/assets/media/

            <Directory /path/to/distro_tracker/project>
                    <Files wsgi.py>
                            Order allow,deny
                            Allow from all
                    </Files>
            </Directory>

            <Directory /path/to/assets/static>
                    Order deny,allow
                    Allow from all
            </Directory>
    </VirtualHost>

.. note::
   Notice the placeholder paths which need to be set according to the local
   file system.

.. note::
   In this case, the same Web server serves both the static files and runs the
   Django app.

nginx and Gunicorn
------------------

Distro Tracker does not include gunicorn in its
:data:`INSTALLED_APPS <distro_tracker.project.settings.INSTALLED_APPS>`, but there is
nothing to prevent users to include it and deploy it with gunicorn
running as the WSGI server and a reverse proxy in front of it.

Static Assets
-------------

When serving `distro-tracker` with a web server, the static assets like images,
Javascript and CSS files should be moved to the directory given in the
``STATIC_ROOT`` setting. Running the following management command will move all
static resources that Django uses to the correct directory::

$ ./manage.py collectstatic
