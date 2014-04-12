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

Until distro-tracker is uploaded to Debian as a proper Debian package,
we use a `Trello board <https://trello.com/b/faDgzjwO/pts-rewrite>`_ to manage
the development tasks of distro-tracker. You can create an account there and
then ping `Raphaël Hertzog <hertzog@debian.org>`_ to get access to the
distro-tracker board.

You can also report bugs against the `qa.debian.org pseudo-package
<https://bugs.debian.org/cgi-bin/pkgreport.cgi?pkg=qa.debian.org>`_, to do so
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

  2. Follow the steps in the chapter `Setup` in order to get the application
     running

  3. Switch to a new branch::

       $ git checkout -b name-of-your-bugfix-or-feature

  4. Add a functional test considering the user perspective in
     functional_tests/tests.py

  5. Add a failing unit test where it belongs. To run a subset of tests,
     issue::

       $ python manage test path-to-the-testing-folder

  6. Fix it

  7. When you're done, check that all tests are succeeding::

       $ python manage test

  8. Commit your changes, push them on a public repository or send them by
     email to the Debian Quality Assurance team::

       $ git add .
       $ git commit
       $ git format-patch -o . origin/master
       $ mutt debian-qa@lists.debian.org -a *.patch

Conventions
~~~~~~~~~~~

  1. Development follows the test-driven development method (TDD). Have a look
     at `Test-Driven Web Development with Python
     <http://www.obeythetestinggoat.com/>`_ if you don't know yet about it.

  2. In regard to coding style, we observe `PEP8\
     <http://legacy.python.org/dev/peps/pep-0008/>`_ with a few exceptions.

  3. Functions are documented using doctrings


