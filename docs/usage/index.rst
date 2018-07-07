.. _usage:

Documentation for end-users
===========================

Most users will be happy to just browse the website provided by Distro
Tracker and they will find there the information that they are looking
for. But more advanced users will want to create an account and be able
to:

* subscribe to packages and receive e-mail notifications for various
  events (bug reports, package upload, etc.)
* subscribe to teams and receive e-mail notifications for all packages
  monitored by the team
* customize the above subscriptions to select exactly the notifications
  that they receive

All those operations can be done from the website once you are
authenticated but it can also be done through commands sent to
a mailbot (:samp:`control@{distro-tracker-domain}`).

.. _package-subscription:

Subscribing to a package
------------------------

On the website
~~~~~~~~~~~~~~

On each package page
(:samp:`https://{distro-tracker-domain}/pkg/{package-name}`) you will find
a :guilabel:`Subscribe` button. If you are authenticated, it will
immediately subscribe you and show you an :guilabel:`Unsubscribe` button
that you can use to revert the operation. If you are not authenticated,
it will invite you to login first to be able to complete the operation.

If you have have multiple emails associated to your account, the
subscription process will ask you to select the email address that
will receive the notifications.

With the mailbot
~~~~~~~~~~~~~~~~

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

.. _team-subscription:

Subscribing to a team
---------------------

On the website
~~~~~~~~~~~~~~

On each team page
(:samp:`https://{distro-tracker-domain}/teams/{team-identifier}/`) you will find
a :guilabel:`Join` button. If you are authenticated, it will
immediately add you to the team and show you a :guilabel:`Leave` button
that you can use to revert the operation. If you are not authenticated,
it will invite you to login first to be able to complete the operation.

If you have have multiple emails associated to your account, the
subscription process will ask you to select the email address that
will receive the notifications.

With the mailbot
~~~~~~~~~~~~~~~~

To join a team through email, you will have to send an email
to :samp:`control@{distro-tracker-domain}` containing the command
:samp:`join-team {team-identifier}` either in the subject or in the body of
the mail. This will subscribe the email address that you used to send
the message. You can ask for the subscription of another email address
by using the command :samp:`join-team {team-identifier} {email}`.

The mailbot will send back a confimation mail to the email address being
subscribed. The message will contain a confirmation command that the user
must send back to the mailbot. A simple reply is usually enough for
this as the mailbot is smart enough to detect the command even when it's
quoted in the reply.

.. note::

The team identifier to use is the same identifier that is used in the URL
of the team on the website. This is the `slug` field in the team creation
form.

More details
------------

.. toctree::

   email
   web
