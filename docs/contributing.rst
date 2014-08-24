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

You can also report bugs against the `tracker.debian.org pseudo-package
<https://bugs.debian.org/cgi-bin/pkgreport.cgi?pkg=tracker.debian.org>`_, to do so
please follow `the usual instructions
<https://www.debian.org/Bugs/Reporting>`_.

When you report a bug, ensure you include detailed steps to reproduce it
and any details that might be helpful in troubleshooting.

If you are proposing a feature, please explain in detail how it would work,
and keep the scope as narrow as possible, to make it easier to implement.

Remember that this is a volunteer-driven project, and that contributions are
welcome.

Contribute
----------

Ready to contribute? Here's how to set up `distro-tracker` for local
development:

Usual workflow
~~~~~~~~~~~~~~

  1. Clone distro-tracker locally::

       $ git clone git://anonscm.debian.org/qa/distro-tracker.git

     Note that you can also browse the sources at
     http://anonscm.debian.org/gitweb/?p=qa/distro-tracker.git

  2. Follow the steps in the chapter :ref:`setting-up`.

  3. Start a local test server::

       $ ./manage.py runserver
       [...]
       Starting development server at http://127.0.0.1:8000/
       Quit the server with CONTROL-C.

     Visit the URL returned to have access to the test website.

  4. Configure the package repositories as explained in
     :ref:`repositories`. With your test server, the URL of
     the admin web interface is http://127.0.0.1:8000/admin/.

  5. Switch to a new branch::

       $ git checkout -b name-of-your-bugfix-or-feature

  6. Develop your new feature, ideally following the rules of :ref:`tdd`.

  7. When you're done, check that all tests are succeeding in all
     supported platforms::

       $ tox

     This basically runs “./manage.py test” with multiple versions
     of Django and Python.

  8. Push your changes on a public repository or send them by
     email to the Debian Quality Assurance team::

       $ git format-patch -o . origin/master
       $ mutt debian-qa@lists.debian.org -a *.patch

.. _tdd:

Test Driven Development
~~~~~~~~~~~~~~~~~~~~~~~

Have a look at `Test-Driven Web Development with Python
<http://www.obeythetestinggoat.com/>`_ if you don't know yet about this
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

  1. In regard to coding style, we observe `PEP8\
     <http://legacy.python.org/dev/peps/pep-0008/>`_ with a few exceptions.

  2. Functions are documented using doctrings with `Sphinx markup
     <http://sphinx-doc.org/contents.html>`_.

Write access to the git repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Debian developers in the "qa" group have write access to the
repository and should use the following command to checkout
a git repository where they can push changes::

   $ git clone ssh://<yourdebianlogin>@git.debian.org/git/qa/distro-tracker.git

Anyone with commit access can use topic branches in the
“people/`debianlogin`/” hierarchy.

