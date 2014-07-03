.. _setting-up:

Setting up Distro Tracker
=========================

.. _requirements:

Requirements
------------

Distro Tracker currently depends on the following Debian packages:

- python-django (>= 1.6)
- python-requests
- python-django-jsonfield
- python-django-south
- python-debian
- python-apt
- python-gpgme
- python-yaml
- python-soappy
- python-beautifulsoup
- python-ldap

For Python2.7, the following additional packages are required:

- python-mock
- python-lzma

.. _database_setup:

Database
--------

Distro Tracker does not rely on any database specific features and as such should be
able to run on top of any database server. The only possible known issue is when
using sqlite3 which has a limit on the number of query parameters of 999 on
some systems.

When you choose your database flavor, you must install the Python bindings,
i.e. psycopg2 for PostgreSQL and MySQL-Python for MySQL, etc.

To create the database you must run the following commands::

$ ./manage.py syncdb
$ ./manage.py migrate

This is because some of the apps' models are managed by South.

See also the Debian package's README.Debian for some details about the setup.

.. _localsettings_setup:

Local Settings
--------------

While Distro Tracker tries to guess as much as needed, you generally will want
to customize some of its parameters. You will do so in
``distro_tracker/project/settings/local.py``. Have a look at the ``defaults.py``
to learn about all the variables that you can override and extend.

To make things easier, Distro Tracker provides default configuration suitable
for production use (installed from the Debian package) or for development
use (running out of a git checkout). Depending on the case, the
``selected.py`` symlink points either to ``production.py`` or to
``development.py``.

Keyrings
--------

The ``DISTRO_TRACKER_KEYRING_DIRECTORY`` lets you define a
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
following command from the Distro Tracker root directory::

$ ./manage.py test

Cron tasks
----------

The data used by distro-tracker needs to be regularly updated/refreshed.
For this you must put “./manage.py tracker_run_all_tasks” in cron.


