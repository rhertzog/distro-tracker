.. _vendor-customization:

Vendor Customization
--------------------

The package tracker has been developed to be usable outside of the Debian
project, for example in the context of a Debian derivative distribution.

To be able to tweak the behaviour of the package tracker for the specific
needs of each project, one can provide vendor-specific code in
:py:mod:`distro_tracker.vendor` and enable that code by selecting
the vendor in the ``DISTRO_TRACKER_VENDOR_RULES``.

Have a look at the :py:mod:`skeleton vendor
<distro_tracker.vendor.skeleton.rules>` to have an idea of the
things that you can tweak through this mechanism.
