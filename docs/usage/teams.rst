.. …teams:

Working with Teams
==================

Purpose of Teams
----------------

Distro Tracker teams have been designed to make it easier to collaborate
on a set of related packages. Members of the team receive the
:ref:`email messages <email-messages>` of all the packages that have been
added to the team.

.. _team-email-address:

Team Email Address
------------------

Each team has an associated email address of the form
:samp:`team+{identifier}@{distro-tracker-domain}`. This email address
can be used to discuss between all team members.

It is possible to opt-out from those emails by disabling the ``contact``
keyword at the team level (see :ref:`managing-team-subscriptions`).

This email address can also be used in the `Maintainer` field of
Debian packages. By doing this, you ensure that your team's packages
are automatically added to the Distro Tracker team and that all members
get the associated messages.

.. _team-packages-overview:

Team Packages Overview
----------------------

Each team provides synoptic views of all packages monitored by the team.
They are directly accessible from the team's main page:
:samp:`https://{distro-tracker-domain}/teams/{team-identifier}/`

.. _team-creation:

Creating a Team
---------------

On the *List of teams* page (:samp:`https://{distro-tracker-domain}/teams/`) you
have to click on the :guilabel:`Create a new team` button to display the
team creation form where you have to fill the following fields:

**Name** (required)
    This is the public name of your team.

**Identifier** (required)
    This is the short-name of your team that is used in the URL and in the
    associated :ref:`email address <team-email-address>`. A proposal is
    made based on the team's name, but you should think twice before
    blindly accepting it because you don't want to change it later as
    this would break URLs and email addresses.

**Visible in the list of teams and free to join by anyone**
    This checkbox defines if the list is public (default value) or
    private. A public list is visible in the list of teams and can
    be joined by anyone. A private list is not visible in the list
    of teams and only the team owner can invite members to the team.

**Description** (optional)
    Long description displayed on the team webpage.

**Url** (optional)
    A public URL displayed on the team's page for anyone who wants to
    learn more about the team.

**Maintainer email** (optional)
    An alternate email address that will be looked for in `Maintainers` and
    `Uploaders` fields when scanning the packages. Any package with this
    maintainer email will be automatically added to the team.

.. note::

    The user who created the team will be the team's owner. He's the
    only user who can update the team parameters. Changing the team's
    owner is not currently supported, if you have to do this, you will
    have to ask the site administrator to make the change for you.

.. _team-subscription:

Joining a Team
--------------

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
    of the team on the website.

Adding and Removing Packages
----------------------------

All team members can add or remove packages through the management page
available when you click on the :guilabel:`Manage team` button on the
team's main page.

Adding and Removing Members
---------------------------

Only the team owner can remove arbitrary members from the team. He can
also add new members to the team although their mail subscription will
be muted by default until they confirm their membership.

Any member (except the owner) can leave the team by clicking on the
:guilabel:`Leave` button on the team's main page.

.. _managing-team-subscriptions:

Managing Subscriptions to Teams
-------------------------------

Every user will see the list of teams he's part of on his profile,
on the :guilabel:`Subscriptions` page available at
:samp:`https://{distro-tracker-domain}/accounts/subscriptions/`.

By expanding the team entry, one can see whether team-specific keywords
have been configured. Those keywords are used to filter messages
that the user will get through the team. They can be modified by
clicking on the :guilabel:`Modify keywords` button.

If the user doesn't want to leave the team but wants to stop receiving
email messages for the team, he can `mute` the team by clicking on the
:guilabel:`Mute` button. The reverse is then done by clicking on the
:guilabel:`Unmute` button that replaced it.

If the user is not (equally) interested in all packages from the team,
he can click on the :guilabel:`Manage subscriptions` button and have
a list of all packages with the possibility to:

* mute/unmute individual packages;
* select different keywords for each package.
