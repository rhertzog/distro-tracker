Setting up the Package Tracking System
======================================

.. _requirements:

Requirements
------------

The Package Tracking System currently depends on the following Python packages:

- Django
- requests
- django-jsonfield
- python-debian
- python-apt
- python-gpgme

For Python2.7, the following additional packages are required:

- mock

.. _database_setup:

Database
--------

The PTS does not rely on any database specific features and as such should be
able to run on top of any database server. The only possible known issue is when
using sqlite3 which has a limit on the number of query parameters of 999 on
some systems.

When you choose your database flavor, you must install the Python bindings,
i.e. psycopg2 for PostgreSQL and MySQL-Python for MySQL, etc.

.. _localsettings_setup:

Local Settings
--------------

Before being able to run the PTS, a ``pts.project.local_settings`` file must
exist. This module provides settings values which are specific for each
deployment.

To make things easier, there is a ``pts/project/local_settings.py.template``
file included which contains all settings values, their descriptions and,
when possible, sane defaults. After modifying the necessary values, copy
this file to ``pts/project/local_settings.py``. Each settings variable is
documented in the ``local_settings.py.template`` file.

Static Assets
-------------

Once the local settings are filled in, the static assets like images,
Javascript and CSS files should be moved to the directory given in the
:data:`STATIC_ROOT <pts.project.local_settings.STATIC_ROOT>` setting. This is
necessary since Django does not serve static resources, but requires a Web
server for that.

Running the following management command will move all static resources that
Django uses to the correct directory::

$ ./manage.py collectstatic

.. note::
   Make sure the directory given in
   :data:`STATIC_ROOT <pts.project.settings.STATIC_ROOT>` exists. 

Keyrings
--------

The :data:`pts.project.local_settings.PTS_KEYRING_DIRECTORY` lets you define a
path to a directory containing known public PGP keys. These keys are used when
verifying various signed content, such as news.

You may add a ``gpg.conf`` file in this directory with additional ``keyring``
directives if you want to include more keys than the ones found in
``pubring.gpg`` file.

.. _tests_setup:

Tests
-----

Once everything is set up, be sure to run the test suite to make sure
everything is actually working as expected. You can do this by issuing the
following command from the PTS root directory::

$ ./manage.py test core control dispatch vendor

Alternatively, you may run the full test suite, including Django's internal
tests, by doing::

$ ./manage.py test
