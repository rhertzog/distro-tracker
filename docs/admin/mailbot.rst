.. _mailbot:

Setting up the mailbot
======================

Email Address Settings
----------------------

The first step is to configure the project to use email addresses of your
choosing. You should modify the following values in
``distro_tracker/project/settings/local.py``:

* DISTRO_TRACKER_CONTROL_EMAIL

   This is the email address which is to be used for receiving control
   messages.

* DISTRO_TRACKER_CONTACT_EMAIL

   This is the email address from which the mailbot responds.

* DISTRO_TRACKER_FQDN

   The fully qualified domain name which will receive package related messages.
   Package messages will be sent to ``<package_name>@<DISTRO_TRACKER_FQDN>``.

.. note::

   These emails are allowed to be on different domains.
  
Management commands
-------------------

In order to have the received email messages properly processed they need to
be passed to the following management commands:

* :mod:`distro_tracker_control <distro_tracker.mail.management.commands.tracker_control>` - handles control messages
* :mod:`distro_tracker_dispatch <distro_tracker.mail.management.commands.tracker_dispatch>` - handles package messages
* :mod:`distro_tracker_receive_news <distro_tracker.mail.management.commands.tracker_receive_news>` -
  handles messages which should be turned into news items

These commands expect the received email message on standard input, which
means that the system's MTA needs to be setup to forward appropriate mails to
the appropriate command.

Exim4
-----

Mails received to ``DISTRO_TRACKER_CONTROL_EMAIL`` address should be piped to the
``control_process`` command. A way to set this up in Exim would be to create a
new alias for the local part of the control email address and set it to point
to the user who owns the Distro Tracker application. That user should have a ``.forward``
file in their home directory which includes the directive to pipe incoming email
to the command.

For example, if the ``DISTRO_TRACKER_CONTROL_EMAIL`` is set to ``control@distro_tracker.debian.net``
and the system user which owns the application is called ``dtracker`` the contents of
``/etc/aliases`` should include the following line::

   control: dtracker

And the ``.forward`` file should be::
   
   | python3 path/to/manage.py distro_tracker_control

Mails received at ``DISTRO_TRACKER_CONTACT_EMAIL`` should be saved or forwarded to the
Distro Tracker administrators. This can be done by adding an additional alias to
``/etc/aliases/``. For example, if ``DISTRO_TRACKER_CONTACT_EMAIL`` is set to
``owner@distro_tracker.debian.net``, the line in the aliases file would be::
   
   owner: some-admin-user

All mail addresses at the ``DISTRO_TRACKER_FQDN`` domain (apart from ``DISTRO_TRACKER_CONTROL_EMAIL``
and ``DISTRO_TRACKER_CONTACT_EMAIL`` addresses if they are on that domain), are considered
package names. As such, all of them should be piped to the ``dispatch``
management command so that they can be processed by Distro Tracker.

To set this up, a custom router and transport can be added to exim
configuration which acts as a catchall mechanism for any email addresses which
are not recognized. Such router and transport could be::

  distro_tracker_package_router:
    debug_print = "R: Distro Tracker catchall package router for $local_part@$domain"
    driver = accept
    transport = distro_tracker_dispatch_pipe

  distro_tracker_dispatch_pipe:
    driver = pipe
    command = python3 /path/to/manage.py distro_tracker_dispatch
    user = dtracker
    group = mail
    log_output

.. note::

   This router should be placed last in the exim configuration file.

Postfix
-------

To configure Postfix to forward email messages to appropriate commands you need
to first create a file with virtual aliases for the relevant email addresses.

Assuming the following configuration::

   DISTRO_TRACKER_CONTACT_EMAIL = owner@distro_tracker.debian.net
   DISTRO_TRACKER_CONTROL_EMAIL = control@distro_tracker.debian.net
   DISTRO_TRACKER_FQDN = distro_tracker.debian.net

The file ``/etc/postfix/virtual`` would be::

  distro_tracker.debian.net not-important-ignored
  postmaster@distro_tracker.debian.net postmaster@localhost
  owner@distro_tracker.debian.net dtracker-owner@localhost
  control@distro_tracker.debian.net dtracker-control@localhost
  _news@distro_tracker.debian.net dtracker-news@localhost
  # Catchall for package emails
  @distro_tracker.debian.net dtracker-dispatch@localhost

The ``/etc/aliases`` file should then include the following lines::
  
  dtracker-owner: some-admin-user
  dtracker-control: "| python3 /path/to/manage.py distro_tracker_control"
  dtracker-dispatch: "| python3 /path/to/manage.py distro_tracker_dispatch"
  dtracker-news: "| python3 /path/to/manage.py distro_tracker_receive_news"

Then, the ``main.cf`` file should be edited to include::

  virtual_alias_maps = hash:/etc/postfix/virtual

.. note::
   
   Be sure to run ``newaliases`` and ``postmap`` after editing ``/etc/aliases``
   and ``/etc/postfix/virtual``.

This way, all messages which are sent to the owner are delivered to the local
user ``some-admin-user``, messages sent to the control address are piped to
the ``distro_tracker_control`` management command, mesages which should be turned into
news items to the ``distro_tracker_receive_news`` command and messages sent to any other
address on the given domain are passed to the ``distro_tracker_dispatch`` management
command.
