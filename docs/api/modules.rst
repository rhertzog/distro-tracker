distro_tracker API
==================

The modules listed here contain the most interesting API available
in distro-tracker, in particular:

* :mod:`distro_tracker.core` contains all the base :mod:`models
  <distro_tracker.core.models>` and :mod:`views
  <distro_tracker.core.views>`, the :mod:`task API
  <distro_tracker.core.tasks>`, and other common :mod:`utilities
  <distro_tracker.core.utils>`.
* :mod:`distro_tracker.test` contain many helper methods that you will
  find useful to write unit tests for new code.

.. toctree::

   distro_tracker.accounts
   distro_tracker.core
   distro_tracker.html
   distro_tracker.mail
   distro_tracker.project
   distro_tracker.test
   distro_tracker.vendor
