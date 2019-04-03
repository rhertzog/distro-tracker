.. _setting-up:

Setting up Distro Tracker
=========================

.. _requirements:

Requirements
------------

Distro Tracker currently depends on the following Debian packages:

- python3-django (>= 1.11)
- python3-requests
- python3-django-jsonfield (>= 1.0.0)
- python3-django-debug-toolbar (in development mode only)
- python3-django-captcha (optional)
- python3-debian
- python3-debianbts
- python3-apt
- python3-gpg
- python3-yaml
- python3-bs4
- python3-pyinotify
- python3-tox (for development only)
- python3-selenium (for development only)
- chromium-driver (for development only)
- python3-sphinx (for development only, to build documentation)

Here is the list of required packages for development on Debian Buster::

 $ sudo apt install python3-django python3-requests python3-django-jsonfield python3-django-debug-toolbar python3-debian python3-debianbts python3-apt python3-gpg python3-yaml python3-bs4 python3-pyinotify python3-selenium chromium-driver

If you are using Debian Stretch, you will need to `enable stretch-backports <https://backports.debian.org/Instructions/>`_ before attempting to do local development of Distro Tracker. 

.. _database_setup:

Database
--------

Distro Tracker does not rely on any database specific features and as such should be
able to run on top of any database server. The only possible known issue is when
using sqlite3 which has a limit on the number of query parameters of 999 on
some systems.

When you choose your database flavor, you must also install the Python bindings,
i.e. psycopg2 for PostgreSQL (*python3-psycopg2*) and mysqlclient for MySQL
(*python3-mysqldb*), etc.

To create the database you must run the following commands::

$ ./manage.py migrate

See also the Debian package's README.Debian for some details about the setup.

.. _localsettings_setup:

Local Settings
--------------

While Distro Tracker tries to guess as much as needed, you generally will
want to customize some of its parameters. You can do so by copying
``distro_tracker/project/settings/local.py.sample`` to
``distro_tracker/project/settings/local.py`` and then editing the latter
file. Have a look at :py:mod:`distro_tracker.project.settings.defaults`
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

Documentation
-------------

This project uses `Sphinx <http://www.sphinx-doc.org/en/master/index.html>`_ for documentation. If you want to improve the documentation or build the documentation locally, first be sure to have the python3-sphinx package installed. Then go to the docs subdirectory ``cd docs`` and run ``make html`` to build the documentation. 

The output will be located in ``_build/html`` and you can preview the documentation in a web browser ``firefox _build/html/index.html``.





