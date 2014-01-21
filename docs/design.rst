.. _design:

Package Tracking Design Overview
================================

Introduction
------------

The Package Tracking System is implemented as a Python application using the
`Django framework <https://www.djangoproject.com>`_. It aims to support both
Python2.7 and Python3.

An important goal of the project is to implement a system which is easily
customizable so it could serve Debian derivatives too (vendors).

This document will present an overview of the high-level design choices which
were made.

Note that a previous version of the PTS pre-existed, but which operated over 
completely different technology (statically generated documents, etc.). 
Some features have been kept identical over the rewrite.


.. _email_design:

Email Interface
---------------

There are three aspects to the email interface in the PTS: the control message
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

The PTS expects the system's MTA to pipe any received control emails to the
:mod:`distro_tracker.mail.management.commands.pts_control` Django management
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

As is the case for control message processing, the PTS expects the system's MTA
to pipe any received package emails to a management command -
:mod:`distro_tracker.mail.management.commands.pts_dispatch`. For information how to set
this up, refer to the :ref:`mailbot setup <mailbot>`.

The function that performs the processing of a received package message is
:func:`distro_tracker.mail.dispatch.process`. In order to tag the received message
with a keyword, it uses a vendor-provided function
:func:`get_keyword <distro_tracker.vendor.skeleton.rules.get_keyword>`. In case a vendor
has not implemented this function, the message is tagged as ``default``.

News from Email Messages
++++++++++++++++++++++++

The PTS allows for automatic news creation based on received emails. It is necessary
to set up the MTA so it pipes received emails which should potentially be turned into
news items, to the management command
:mod:`distro_tracker.mail.management.commands.pts_receive_news`.

News are created as :class:`distro_tracker.core.models.News` objects and each of the
model's instances associated with a particular package is displayed in the
:class:`NewsPanel <distro_tracker.core.panels.NewsPanel>`.

By default, any messages given to the management command which contains the
``X-PTS-Package`` header are turned into news items with the content type of
the news item being ``message/rfc822`` and the content the entire message.

However, it is also possible to implement a vendor-specific function
:func:`distro_tracker.vendor.skeleton.rules.create_news_from_email_message` which will be
given the received email message object and can create custom news items based
on vendor-specific rules.

.. _tasks_design:

Tasks Framework
---------------

Since the PTS expects to aggregate information based on many different sources,
a way to perform incremental updates is necessary. This means that if an update
from one source causes such changes which could have an effect on some other
information, this information needs to be updated, as well. In order to avoid
recalculating everything after each update, a framework for executing such
tasks is implemented in :mod:`distro_tracker.core.tasks`.

Each task defines a list of "events" which it produces and a list of "events"
it depends on. An event is any change of shared information or anything else
a task would like to inform other tasks of happening. Knowing this, the
framework can build a graph of dependencies between tasks.

When running a single task, all other tasks which are dependent on that one
are automatically run afterwards, in the correct order and ensuring a task runs
only once all the tasks it depends on are completed. It also makes sure not to
initiate any task for which no events were raised.

In order to implement a task, the :class:`distro_tracker.core.tasks.BaseTask` class should
be subclassed. Its attributes
:attr:`PRODUCES_EVENTS <distro_tracker.core.tasks.BaseTask.PRODUCES_EVENTS>` and
:attr:`DEPENDS_ON_EVENTS <distro_tracker.core.tasks.BaseTask.DEPENDS_ON_EVENTS>` are lists
of strings giving names of events which the task produces and depends on,
respectively. The :meth:`execute() <distro_tracker.core.tasks.BaseTask.execute>` method
implements the task's functionality.

.. note::
   All task classes should be placed in a module called ``pts_tasks`` found at
   the top level of an installed Django app. Tasks in apps which are not
   installed will never be run.

When running a task, a :class:`distro_tracker.core.tasks.Job` instance is created which
keeps track of raised events, completed tasks and the order in which the tasks
should run. It stores its state using the :class:`distro_tracker.core.tasks.JobState`
class which is in charge of making sure the job state is persistent, so that
even if a job were to fail, it is still possible to reconstruct it and continue
its execution.

.. note::
   Each task's operation must be idempotent to ensure that if an error does occur
   before being able to save the state of the job, rerunning the task will not
   cause any inconsistencies.

A task has access to the :class:`Job <distro_tracker.core.tasks.Job>` instance it is a
part of and can access all events raised during its processing. A convenience
method :meth:`get_all_events <distro_tracker.core.tasks.BaseTask.get_all_events>` is
provided which returns only the events the class has indicated in the
:attr:`DEPENDS_ON_EVENTS <distro_tracker.core.tasks.BaseTask.DEPENDS_ON_EVENTS>` list.

For more information see the documentation on the :mod:`distro_tracker.core.tasks` module.

.. _vendor_design:

Vendor-specific Rules
---------------------

Since the PTS aims to be extensible, it allows a simple way for vendors to
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

The PTS retrieves package information from a set of user-defined repositories.
Admin users can add new :class:`distro_tracker.core.models.Repository` instances through
the admin panel. Information from repositories is updated by the task
:class:`distro_tracker.core.retrieve_data.UpdateRepositoriesTask` and it emits events
based on changes found in the repositories.

Additional tasks are implemented in :class:`distro_tracker.core.retrieve_data` which
use those events to store pre-calculated (extracted) information ready
to be rendered in a variety of contexts (webpage, REST, RDF, etc.).

The PTS also updates the list of existing pseudo packages by using the
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

The PTS allows an easy way to embed new information on a package Web page.
It consists of implementing a subclass of the :class:`distro_tracker.core.panels.BasePanel`
class. Panels can provide the HTML directly or, alternatively, the name of the
template which should be included. This template then has to render the panel's
information to the page.

It is recommended that the panel inherits from the ``core/panels/panel.html``
template and fills in its contents to the blocks defined in the template, so
that the page remains visually consistent. This is not mandatory, however.

.. note::
   All panel classes should be placed in a module called ``pts_panels`` found at
   the top level of an installed Django app. Panels from apps which are not
   installed will never appear on a package page.

The PTS implements some general panels which could be used by any vendor.
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

The `Bootstrap <http://twitter.github.io/bootstrap/>`_ front-end framework is
used for the GUI.
