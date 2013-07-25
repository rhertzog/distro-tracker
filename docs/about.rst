.. _about:

What is the Package Tracking System?
====================================

The Package Tracking System allows users to follow package information through
email messages and a Web presentation. This information may be interesting to
package maintainers, contributors, advances users, QA members, etc...

The PTS aims to be as extensible and as customizable as possible in order to
allow Debian derivatives to deploy their own Package Tracking System if they
so choose.

.. _email_about:

Email Interface
---------------

The Package Tracking System forwards email mesasges regarding a package to users
who are subscribed to that package.

The PTS receives email messages for each package on a special address in the
form of ``<package-name>@<pts-domain>``. If the local part of the email is a
valid package name, the message is a valid package message. Messages to the
package's address can be sent by either automated tools or users themselves.

Each package email is first tagged with one of the existing keywords and then
forwarded only to the subscribers interested in that keyword. Users sending
package messages to PTS can tag their own messages with a keyword by using a
local part of the address in the form of ``<package-name>_<keyword>``.

A user can choose which mails they are interested in, by selecting to either
receive messages tagged with one of their "default" keywords or they can choose
a different set of keywords for each of their package subscriptions.

Each vendor can provide their own set of available keywords and a set of rules to
tag incoming messages with one of the keywords. If there is no such tagging
mechanism and no keyword in the local part of the email address, the message is
tagged with the "default" keyword.

The keyword of the forwarded message is included in a mail header
``X-PTS-Keyword``.

There are three types of packages which are considered valid packages for email
message forwarding by the PTS:

- source package
- pseudo package - a list of pseudo packages should be provided by a vendor specific
  function :func:`pts.vendor.skeleton.rules.get_pseudo_package_list`
- subscription-only package - neither a pseudo package nor a source package, but
  still allows the same email functionality as the other package types

.. _email_control_about:

Email Control Interface
+++++++++++++++++++++++

Users can control their subscriptions (packages subscribed to, keywords to
accept) by sending control commands enclosed in an email message to a bot. The
designated email address for the control interface is ``control@<pts-domain>``,
by default. This is customizable by vendors.

Control emails contain a list of commands, each in a separate line. Available
commands can be obtained by sending a control message with the ``help``
command (an email message with ``help`` on a single line).

If a message which reaches the control bot contains too many lines which are
invalid commands, processing is halted and only the commands found up until
that point are processed. If there were no valid commands found in the email,
no response is sent, otherwise an email message is constructed and sent in
response to indicate the status of each processed command.

Certain commands may require confirmation by the user, e.g. subscribing to
receive package messages. If a control message contains any such command,
apart from a response email, a separate "confirmation" email is also sent.
Only one confirmation email is sent regardless of how many commands from the
original control message require confirmation. It includes a confirmation
code, instructions on how to confirm the commands and any extra information
about each command which is to be confirmed. 

.. _web_about:

Web Interface
-------------

Each source and pseudo package has its own Web page displaying information
aggregated from various sources. This page is accessible at the URL
``/<package-name>``.

If a binary package name is entered, the user is redirected to the
corresponding source package's page.

A convenient search form is provided on the frontpage as well as on each
package's page which allows users to jump to another package page and
supports autocomplete suggestions for both source and pseudo packages.

The information currently provided for each package is divided into the
following panels:

- General package information panel
- Versions panel
- Binaries panel
- News panel

Vendors can easily customize and add new panels to the page. For more
information refer to the
:ref:`design overview documentation <panels_web_design>` regarding panels.

.. _rss_about:

RSS news feed [coming soon]
+++++++++++++

.. _rest_about:

REST interface [coming soon]
++++++++++++++

.. _rdf_about:

RDF metadata [coming soon]
++++++++++++
