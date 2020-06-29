.. _design:

Design Overview
===============

Introduction
------------

Distro Tracker is implemented as a Python 3 application using the
`Django framework <https://www.djangoproject.com>`_.

An important goal of the project is to implement a system which is easily
customizable so it could serve Debian derivatives too (vendors).

This document will present an overview of the high-level design choices which
were made.

Note that a previous version of the service pre-existed (it was known
as the Package Tracking System), but which operated over completely
different technology (statically generated documents, etc.).  Some
features have been kept identical over the rewrite.


.. _email_design:

Email Interface
---------------

There are three aspects to the email interface: the control message
processing, dispatching received package messages to the correct
subscribers and creating news items based on received emails.

This is implemented in the :mod:`distro_tracker.mail` app. The three mentioned
functionalities are found in the following subpackages and modules of this app:

- :mod:`distro_tracker.mail.control.control`
- :mod:`distro_tracker.mail.dispatch`
- :mod:`distro_tracker.mail.mail_news`

.. _control_email_design:

Email Control Messages
++++++++++++++++++++++

Distro Tracker expects the system's MTA to pipe any received control emails to the
:mod:`distro_tracker.mail.management.commands.tracker_control` Django management
command. For information how to set this up, refer to the
:ref:`mailbot setup <mailbot>`.

The actual processing of the received command email message is implemented in
:func:`distro_tracker.mail.control.process.process`. It does this by retrieving the message's
payload and feeding it into an instance of
:class:`distro_tracker.mail.control.commands.CommandProcessor`.

The :class:`CommandProcessor <distro_tracker.mail.control.commands.CommandProcessor>` takes
care of parsing and executing all given commands.

All available commands are implemented in the :mod:`distro_tracker.mail.control.commands`
module. Each command must be a subclass of the
:mod:`distro_tracker.mail.control.commands.base.Command` class. There are three attributes of the
class that subclasses must override:

- :attr:`META <distro_tracker.mail.control.commands.base.Command.META>` - most importantly
  provides the command name
- :attr:`REGEX_LIST <distro_tracker.mail.control.commands.base.Command.REGEX_LIST>` - allows
  matching a string to the command
- :meth:`handle() <distro_tracker.mail.control.commands.base.Command.handle>` - implements the command
  processing

The class :class:`distro_tracker.mail.control.commands.CommandFactory` produces instances of
the correct :class:`Command <distro_tracker.mail.control.commands.base.Command>` subclasses
based on a given line.

Commands which require confirmation are easily implemented by decorating the
class with the :func:`distro_tracker.mail.control.commands.confirmation.needs_confirmation`
class decorator. In addition to that, two more methods can be implemented, but
are not mandatory:

- ``pre_confirm`` - for actions which should come before asking for
   confirmation for the command. If this method does not return an
   object which evalutes as a True Boolean, no confirmation is sent.
   It should also make sure to add appropriate status messages to the
   response.
   If the method is not provided, then a default response indicating that
   a confirmation is required is output.

- ``get_confirmation_message`` - Method which should return a string
   containing an additional message to be included in the confirmation
   email.

.. _dispatch_email_design:

Email Dispatch
++++++++++++++

As is the case for control message processing, Distro Tracker expects the system's MTA
to pipe any received package emails to a management command -
:mod:`distro_tracker.mail.management.commands.tracker_dispatch`. For information how to set
this up, refer to the :ref:`mailbot setup <mailbot>`.

The function that performs the processing of a received package message is
:func:`distro_tracker.mail.dispatch.process`. In order to tag the received message
with a package and a keyword, it uses a vendor-provided function
:func:`classify_message <distro_tracker.vendor.skeleton.rules.classify_message>`. 
In case a vendor has not implemented this function, the message is tagged
with the ``default`` keyword.

The same function is also used to transform some of the incoming emails
into permanent news items that are displayed on each package page.

.. _tasks_design:

Tasks Framework
---------------

Since Distro Tracker aggregates information based on many different sources,
a way to perform incremental updates is necessary. This means that if an update
from one source causes such changes which could have an effect on some other
information, this information needs to be updated, as well. In order to avoid
recalculating everything after each update, a framework for executing such
tasks is implemented in :mod:`distro_tracker.core.tasks`.

In order to implement a task, the :class:`distro_tracker.core.tasks.BaseTask` class should
be subclassed and mixed together with schedulers to define when the task
should be run. Various mixins exist in
:mod:`distro_tracker.core.tasks.mixins` to help build task processing some
common entities.

.. note::
   All task classes should be placed in a module called ``tracker_tasks`` found at
   the top level of an installed Django app. Tasks in apps which are not
   installed will never be run.

.. note::
   Each task's operation must be idempotent to ensure that if an error does occur
   before being able to save the state of the job, rerunning the task will not
   cause any inconsistencies.

For more information see the documentation on the :mod:`distro_tracker.core.tasks` module.

.. _vendor_design:

Vendor-specific Rules
---------------------

Since Distro Tracker aims to be extensible, it allows a simple way for vendors to
implement functions which are plugged in by core code when necessary.

Vendor-provided functions can be called using the :func:`distro_tracker.vendor.common.call`
function. The function object itself can be retrieved by using the
lower-level :func:`distro_tracker.vendor.common.get_callable` function, but this should
be avoided.

All vendor-provided functions must be found in the module given by the
``DISTRO_TRACKER_VENDOR_RULES`` settings value.

.. _packageinfo_design:

Package Information
-------------------

Distro Tracker retrieves package information from a set of user-defined repositories.
Admin users can add new :class:`distro_tracker.core.models.Repository` instances through
the admin panel. Information from repositories is updated by the task
:class:`distro_tracker.core.retrieve_data.UpdateRepositoriesTask` and it emits events
based on changes found in the repositories.

Additional tasks are implemented in :class:`distro_tracker.core.retrieve_data` which
use those events to store pre-calculated (extracted) information ready
to be rendered in a variety of contexts (webpage, REST, RDF, etc.).

Distro Tracker also updates the list of existing pseudo packages by using the
vendor-provided function
:func:`get_pseudo_package_list <distro_tracker.vendor.skeleton.rules.get_pseudo_package_list>`.

All retrieved data can be accessed by using the models found in
:mod:`distro_tracker.core.models`. Refer to that module's documentation for convenient
APIs for interacting with the extracted information.

Data model
++++++++++

You may wish to check the data model. This can be done for instance
with the following command after having installed 'django_extensions'
in INSTALLED_APPS (see distro_tracker.project.setup.locals.py)::

 $ ./manage.py graph_models core | dot -Tpng >graph.png

.. _web_design:

Web Interface
-------------

.. _panels_web_design:

Panels Framework
++++++++++++++++

Distro Tracker allows an easy way to embed new information on a package Web page.
It consists of implementing a subclass of the :class:`distro_tracker.core.panels.BasePanel`
class. Panels can provide the HTML directly or, alternatively, the name of the
template which should be included. This template then has to render the panel's
information to the page.

It is recommended that the panel inherits from the ``core/panels/panel.html``
template and fills in its contents to the blocks defined in the template, so
that the page remains visually consistent. This is not mandatory, however.

.. note::
   All panel classes should be placed in a module called ``tracker_panels`` found at
   the top level of an installed Django app. Panels from apps which are not
   installed will never appear on a package page.

Distro Tracker implements some general panels which could be used by any vendor.
Refer to the documentation of each panel in :mod:`distro_tracker.core.panels` to see
any possible ways of augmenting their information by implementing
vendor-specific functions.

.. _views_web_design:

Views and Templates
+++++++++++++++++++

The core views are found in :mod:`distro_tracker.core.views` and are extremely thin.

The package page view only finds the correct package model instance and
passes it on to available panels. It renders a template which includes each
panel within the skeleton of the page.

Other core views are in charge of a redirect of legacy package URLs, package
search and package autocomplete.

.. _clientside_web_design:

Client-side Functionality
+++++++++++++++++++++++++

The client-side implements a simple autocomplete form for searching packages.
It uses Javascript to call an HTTP endpoint implemented by one of the views.

The HTML of the pages uses the HTML5 standard.

The `Bootstrap <https://getbootstrap.com/>`_ front-end framework is
used for the GUI.
