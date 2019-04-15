.. _repositories:

Setting up the package repositories
===================================

In order to do its work, distro-tracker must know the repositiories to
watch. And among those you should define a default repository that will
be used in priority for package specific information.

With the admin web interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To access the admin web interface, you will first need to create an
account:

   $ ./manage.py createsuperuser

You should now be able to configure the repositories from the admin web
interface, which is accessible as “/admin/” in the package tracker
website.

Make sure that you create repositories with "sources" enabled as almost
everything is based on source packages, and do not forget to check the
"default repository" checkbox for one of the repositories you just
added.

With a fixture
~~~~~~~~~~~~~~

If you want to configure you package tracker to have all the repositories
like on tracker.debian.org, you can load a fixture::

   $ ./manage.py loaddata distro_tracker/core/fixtures/debian-repositories.xml 

Initial scan
~~~~~~~~~~~~

Once the repositories have been setup, you should run an initial scan::

    $ ./manage.py tracker_update_repositories

This might take a very long time...
