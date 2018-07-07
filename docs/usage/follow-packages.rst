.. _follow-packages:

Following Packages
==================

A package tracker is mainly of interest to retrieve information about
packages. Depending on your needs, there are multiple ways to get those
information.

Visiting the Package's Page
---------------------------

Each source package has its own web dashboard displaying information
aggregated from various sources. This page is accessible at the URL
:samp:`https://{distro-tracker-domain}/pkg/{package-name}`.

.. note::

    If a binary package name is entered, the user is redirected to the
    corresponding source package's page.

A convenient search form is provided on the front page as well as on each
package's page which allows users to jump to another package page. It
supports auto-completion for both source and binary package names.

The information currently provided for each package is divided into the
following panels:

**general**
    Contains general information extracted from the package currently
    available in the development repository:

    * name of the source package
    * current version
    * current maintainer and uploaders
    * list of supported architectures
    * standards version field
    * URL(s) for the VCS repository

**versions**
    For each repository tracked, lists the version of the source package
    that it contains.

**versioned links**
    Provides links to files which are specific to a given version.
    The set of links can vary depending on the configuration but here
    are the links that can be put in place:

    * .dsc file (source package)
    * debian/changelog (checklist icon)
    * debian/copyright (balance of law icon)
    * debian/rules (tools icon)
    * debian/control file (package icon)

**binaries**
    Lists the binary packages built by the source package and provides
    related links.

**action needed**
    Lists various issues affecting the source package. This information
    is mainly of interest to package maintainers and contributors. The
    higher priority issues are displayed first. More information can be
    displayed by clicking on the chevron on the left of each entry.

**news**
    Sorted list of news related to the package. Clicking on the link
    shows the full content associated to the news. Most news are actually
    email messages that one can get by subscribing to the package.

**bugs**
    Statistics and links to bug reports.

**links**
    Links to external sources of information that have something relevant
    for this source package.

Other vendor-specific panels can appear. For example, the Debian Package Tracker has an
`ubuntu` panel with information related to the state of the package in the
Ubuntu derivative distribution.

.. _package-subscription:

Getting Updates by Email
------------------------

If you don't want to visit the web page regularly, you can subscribe to
the package to receive updates by email (see :ref:`email-messages` to
have an idea of what messages you can get).

There are two ways to subscribe to a package:

Subscribing on the Website
~~~~~~~~~~~~~~~~~~~~~~~~~~

On each package page
(:samp:`https://{distro-tracker-domain}/pkg/{package-name}`) you will find
a :guilabel:`Subscribe` button. If you are authenticated, it will
immediately subscribe you and show you an :guilabel:`Unsubscribe` button
that you can use to revert the operation. If you are not authenticated,
it will invite you to login first to be able to complete the operation.

If you have have multiple emails associated to your account, the
subscription process will ask you to select the email address that
will receive the notifications.

Subscribing by Email
~~~~~~~~~~~~~~~~~~~~

To subscribe to a package through email, you will have to send an email
to :samp:`control@{distro-tracker-domain}` containing the command
:samp:`subscribe {package-name}` either in the subject or in the body of
the mail. This will subscribe the email address that you used to send
the message. You can ask for the subscription of another email address
by using the command :samp:`subscribe {package-name} {email}`.

The mailbot will send back a confimation mail to the email address being
subscribed. The message will contain a confirmation command that the user
must send back to the mailbot. A simple reply is usually enough for
this as the mailbot is smart enough to detect the command even when it's
quoted in the reply.

Following Updates with an RSS Feed
----------------------------------

Each package provides a dedicated RSS feed available at the following URL:
:samp:`https://{distro-tracker-domain}/pkg/{package-name}/rss`

You can find a small `rss feed` icon at the top-right of the `news`
panel on the package's page, it is linked to the RSS feed.

The RSS feed collates the regular news (from the `news` panel) as well as
the items from the `action needed` panel.
