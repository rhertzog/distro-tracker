.. _email-interaction:

Interacting with Distro-Tracker by Email
========================================

.. _mailbot:

How the Mailbot Works
---------------------

Users can control their subscriptions (packages subscribed to, keywords to
accept) by sending control commands enclosed in an email message to a robot. The
designated email address for its control interface is
:samp:`control@{distro-tracker-domain}` (aka control@tracker.debian.org
for Debian's instance).

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

.. _email-commands:

Mailbot Commands Reference
--------------------------

:samp:`subscribe {sourcepackage} [{email}]`
    Subscribes *email* to communications related to the source package
    *sourcepackage*. Sender address is used if the second argument is not
    present. If *sourcepackage* is not a valid source package, you will get a
    warning. However if it is a valid binary package, the package tracker
    will subscribe you to the corresponding source package.

:samp:`unsubscribe {sourcepackage} [{email}]`
    Removes a previous subscription to the source package *sourcepackage*
    using the specified email address or the sender address if the second
    argument is left out.

:samp:`unsubscribeall [{email}]`
    Removes all subscriptions of the specified email address or the sender
    address if the second argument is left out.

:samp:`which [{email}]`
    Lists all subscriptions for the sender or the email address optionally
    specified.

:samp:`keyword [{email}]`
    Tells you the :ref:`keywords <keywords>` that you are accepting.

:samp:`keyword {sourcepackage} [{email}]`
    Same as the previous item but for the given source package, since you
    may select a different set of keywords for each source package.

:samp:`keyword [{email}] +|-|= {list of keywords}`
    Accept (``+``) or refuse (``-``) mails classified under the given
    keyword(s).  Define the list (``=``) of accepted keywords. This
    changes the default set of keywords accepted by a user.

    Examples:

    * ``keyword + vcs derivatives``
    * ``keyword user@example.net - bts bts-control``
    * ``keyword = default contact upload-source``

:samp:`keywordall [{email}] +|-|= {list of keywords}`
    Accept (``+``) or refuse (``-``) mails classified under the given
    keyword(s).  Define the list (``=``) of accepted keywords. This
    changes the set of accepted keywords of all the currently active
    subscriptions of a user.

:samp:`keyword {sourcepackage} [{email}] +|-|= {list of keywords}`
    Same as previous item but overrides the keywords list for the
    indicated source package.

:samp:`join-team {team-identifier} [{email}]`
    Adds *email* (or sender address if not specified) to the team whose
    identifier is *team-identifier*. If the team is not public or doesn't
    exist, a warning is issued.

:samp:`leave-team {team-identifier} [{email}]`
    Removes *email* (or sender address if not specified) from the team whose
    identifier is *team-identifier*. If the user identified by the email
    is not a member of the team, a warning is issued.

:samp:`list-team-packages {team-identifier}`
    Lists all packages of the team whose identifier is *team-identifier*.
    If the team is private, the result is only sent if the user is a
    member of the team.

:samp:`which-teams [{email}]`
    Lists all teams that have *email* (or the sender address if not
    specified) as a member.

:samp:`quit | thanks | --`
    Stops processing commands. All following lines are ignored by the bot.
