============
Contributing
============
Contributions to distro-tracker are greatly appreciated!
You can contribute in many ways, be it writing documentation and blog
posts, or fixing bugs and implementing new features.

Join the community
------------------
The recommended way to send feedback is to write to the Debian Quality
Assurance mailing list <debian-qa@lists.debian.org>. You can also reach us
using IRC on the #debian-qa channel at irc.debian.org.

You can also `report bugs <https://salsa.debian.org/qa/distro-tracker/issues>`_
in GitLab's interface. When you report a bug, ensure you include detailed
steps to reproduce it and any details that might be helpful in
troubleshooting.

If you are proposing a feature, please explain in detail how it would work,
and keep the scope as narrow as possible, to make it easier to implement.

If you do not know where to start, we have tasks suitable for
newcomers:

 * `in Debian's bug tracker <https://bugs.debian.org/cgi-bin/pkgreport.cgi?dist=unstable;package=tracker.debian.org;tag=newcomer>`_
 * `in GitLab's bug tracker <https://salsa.debian.org/qa/distro-tracker/issues?label_name%5B%5D=newcomer>`_

There are mentors willing to review your changes with special care when
you try to tackle those.

Please remember that this is a volunteer-driven project, and that
contributions are welcome.

Contribute
----------

Ready to contribute? Here's how to set up distro-tracker for local
development:

Usual workflow
~~~~~~~~~~~~~~

  1. Create a guest account on `Salsa <https://salsa.debian.org>`_ (a GitLab
     instance run by the Debian project) by visiting this page:
     https://salsa.debian.org/users/sign_up

     Follow all the steps to confirm your email, fill your profile,
     `setup your SSH keys
     <https://salsa.debian.org/help/ssh/README.md>`_.

     You might want to have a look at `Salsa's
     documentation <https://wiki.debian.org/Salsa/Doc>`_ and `GitLab's
     documentation <https://salsa.debian.org/help>`_ if you have doubts
     about something.

     Note that Debian Developers can skip this step as they already have
     an account on this service.

  2. Visit the `project's page <https://salsa.debian.org/qa/distro-tracker>`_
     and fork distro-tracker in your own account. See `GitLab's
     help <https://salsa.debian.org/help/user/project/repository/forking_workflow.md#creating-a-fork>`_.

  3. Clone distro-tracker locally::

       $ git clone git@salsa.debian.org:your-account/distro-tracker.git

     Note that ``your-account`` should be replaced by your Salsa's username.
     If you want to clone the project without creating any account then
     use this command::

       $ git clone https://salsa.debian.org/qa/distro-tracker.git

  4. For a quick startup, run this command::

       $ bin/quick-setup.sh

     It will install required packages with apt, put a sample
     configuration file in place and download a pre-built database file to
     save you some setup time.

     If you have more time and want to learn more about the configuration
     of distro tracker, follow the steps in the sections :ref:`setting-up`
     and :ref:`repositories`.

     .. warning::
        Due to limitations of salsa.debian.org not allowing CI jobs taking
        longer than 3h, the pre-built database is no longer being
        generated. The script has thus been modified to run the commands
        to initialize the database and it will take a long time to run.

  5. Start a local test server::

       $ ./manage.py runserver
       [...]
       Starting development server at http://127.0.0.1:8000/
       Quit the server with CONTROL-C.

     Visit the URL returned to have access to the test website.

  6. Switch to a new branch::

       $ git checkout -b name-of-your-bugfix-or-feature

  7. Develop your new feature, ideally following the rules of :ref:`tdd`.

  8. When you're done, check that all tests are succeeding in all
     supported platforms::

       $ tox

     This basically runs ``./manage.py test django_email_accounts
     distro_tracker`` with multiple versions of Django and Python.

     .. note::
        If you get errors like ``OSError: [Errno 38] Function not
        implemented``, then it means that you are lacking /dev/shm
        with proper permissions.

  9. Push your branch to your repository::

       $ git push -u origin name-of-your-bugfix-or-feature

  10. Submit us your work, ideally by opening a `merge
      request <https://salsa.debian.org/qa/distro-tracker/-/merge_requests/>`_.
      You can do this easily by visiting the distro-tracker
      project fork hosted in your own account (either through the “Branches”
      page, or through the “Merge requests” page). See `GitLab's
      help <https://salsa.debian.org/help/user/project/merge_requests/creating_merge_requests.md#new-merge-request-from-a-fork>`_
      if needed.

      Make sure to address any issue identified by the continuous
      integration system, the result of its “pipeline” can be directly
      seen in the merge request (and in the commits pushed in your own
      repository).

      If you don't have any Salsa account, you can generate patches and
      send them by email to the Debian Quality Assurance team::

       $ git format-patch -o . origin/master
       $ mutt debian-qa@lists.debian.org -a *.patch

.. _tdd:

Test Driven Development
~~~~~~~~~~~~~~~~~~~~~~~

Have a look at `Test-Driven Web Development with Python
<https://www.obeythetestinggoat.com/>`_ if you don't know yet about this
development methodology.

The suggested workflow looks like this:

  1. Add a functional test that covers the new feature from the point of
     view of the user. This test will fail since the feature doesn't exist
     yet.

  2. Think about what's the next step to let the functional test go
     further (i.e. fail later).

  3. Write a failing unit test for the new code that you want to write.

  4. Write the minimal code to make your unit test pass. You will
     typically run this very often::

        $ ./manage.py test path-to-the-testing-folder

  5. Refactor (if needed). You might have introduced some duplication in
     your code or in your tests. Clean that up now before it's too late.

  6. Commit (optional). Commit together the (working) unit tests and the
     new code.

  7. If you made progress from the functional tests point of view, go back
     to point 2, otherwise go back to point 3. If the functional test
     passes, continue.

  8. Commit. The functional tests are committed at this point to ensure
     that they are committed in a working state::

        $ git add .
        $ git commit

When you don't develop a new feature, your workflow is restricted to steps
3 to 6.

Conventions
~~~~~~~~~~~

  1. In regard to coding style, we observe `PEP8
     <https://www.python.org/dev/peps/pep-0008/>`_ with a few exceptions.

  2. Functions are documented using docstrings with `Sphinx markup
     <https://www.sphinx-doc.org/en/master/>`_.

  3. Imports are sorted in multiple groups separated by one empty line:
     first a group for ``__future__`` imports, then a single group for all
     the Python standard modules, then one group for each third-party
     module (and groups are sorted between them as well), followed by
     groups for the project modules (one group for ``distro_tracker`` and
     one group for ``django_email_accounts``), and last, one group for
     relative imports.

     Within each group the ``import foo`` statements are grouped and
     sorted at the top, while the ``from foo import bar`` statements
     are grouped and sorted at the end.

     Example:

.. code-block:: python3

   from __future__ import print_function

   import datetime
   import os
   from datetime import timedelta
   from email.utils import getaddresses, parseaddr

   from django.conf import settings
   from django.db import connection, models
   from django.utils.safestring import mark_safe

   import requests
   from requests.structures import CaseInsensitiveDict

   from distro_tracker.core.models import SourcePackage
   from distro_tracker.core.utils import get_or_none

   from django_email_accounts.models import User

Git commit notices
~~~~~~~~~~~~~~~~~~

Please invest some time to write good commit notices. Just like your code,
you write it once but it will be read many times by different persons
looking to understand why you made the change. So make it pleasant to
read.

The first line is the “summary” (or title) and describes briefly what the
commit changes. It's followed by an empty line and a long description. The
long description can be as long as you want and should explain why you
implemented the change seen in the commit.

The long description can also be used to close bugs by putting some
pseudo-fields at the end of the description:

 * for a GitLab issue, use ``Fixes: #XX`` (this is a standard GitLab
   feature)
 * for a Debian bug, use ``Closes: #XXXXXX`` (this is implemented by a
   `webhook <https://salsa.debian.org/salsa/webhook>`_)

Write access to the git repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`Project (and Debian QA group) members
<https://salsa.debian.org/qa/distro-tracker/-/project_members>`_ have write
access to the main git repository. They can thus clone the repository
with this URL::

   $ git clone git@salsa.debian.org:qa/distro-tracker.git

From there they can push their changes directly. They are however free to
use a fork and request review anyway when they prefer.
