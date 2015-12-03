# Copyright 2013-2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements the processing of received package messages in order to dispatch
them to subscribers.
"""
from __future__ import unicode_literals
from django.core.mail import get_connection
from django.utils import six
from django.utils import timezone
from django.core.mail import EmailMessage

from datetime import datetime

from distro_tracker.core.utils import extract_email_address_from_header
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils import distro_tracker_render_to_string
from distro_tracker.core.utils import verp

from distro_tracker.core.utils.email_messages import CustomEmailMessage
from distro_tracker.core.utils.email_messages import (
    patch_message_for_django_compat)
from distro_tracker.mail.models import UserEmailBounceStats

from distro_tracker.core.models import PackageName
from distro_tracker.core.models import Keyword
from distro_tracker.core.models import Team
from django.conf import settings
DISTRO_TRACKER_CONTROL_EMAIL = settings.DISTRO_TRACKER_CONTROL_EMAIL
DISTRO_TRACKER_FQDN = settings.DISTRO_TRACKER_FQDN

from copy import deepcopy
import re
import logging

logger = logging.getLogger(__name__)

from distro_tracker import vendor


def _get_logdata(msg, package, keyword):
    return {
        'from': extract_email_address_from_header(msg.get('From', '')),
        'msgid': msg.get('Message-ID', 'no-msgid-present@localhost'),
        'package': package or '<unknown>',
        'keyword': keyword or '<unknown>',
    }


def process(msg, package=None, keyword=None):
    """
    Handles the dispatching of received messages.

    :param msg: The received message
    :type msg: :py:class:`email.message.Message`

    :param package: The package to which the message was sent.

    :param keyword: The keyword under which the message must be dispatched.
    """
    logdata = _get_logdata(msg, package, keyword)
    logger.info("dispatch :: received from %(from)s :: %(msgid)s",
                logdata)
    forward(msg, package=package, keyword=keyword)


def forward(msg, package=None, keyword=None):
    """
    Forwards a received message to the various subscribers of the
    given package/keyword combination.

    :param msg: The received message
    :type msg: :py:class:`email.message.Message`

    :param package: The package name.

    :param keyword: The keyword under which the message must be forwarded.
    """
    logdata = _get_logdata(msg, package, keyword)

    logger.info("dispatch :: forward to %(package)s/%(keyword)s :: %(msgid)s",
                logdata)
    # Check loop
    package_email = '{package}@{distro_tracker_fqdn}'.format(
        package=package, distro_tracker_fqdn=DISTRO_TRACKER_FQDN)
    if package_email in msg.get_all('X-Loop', ()):
        # Bad X-Loop, discard the message
        logger.info('dispatch :: discarded %(msgid)s due to X-Loop', logdata)
        return

    # Extract keyword
    keyword = get_keyword(keyword, msg)
    logger.info('dispatch :: %s %s', package, keyword)
    # Default keywords require special approvement
    if keyword == 'default' and not approved_default(msg):
        logger.info('dispatch :: discarded non-approved message %(msgid)s',
                    logdata)
        return

    # Now send the message to subscribers
    add_new_headers(msg, package, keyword)
    send_to_subscribers(msg, package, keyword)
    send_to_teams(msg, package, keyword)


def get_keyword(suggested_keyword, msg):
    """
    Extracts the keywoword from the given message.

    The function first tries using a vendor-provided function
    :func:`get_keyword <distro_tracker.vendor.skeleton.rules.get_keyword>`.

    If the vendor did not implement this function or does not return a keyword
    for the given message, the function fallbacks to the suggested keyword.

    If this also does not yield a keyword, ``default`` is returned.

    :param suggested_keyword: The suggested keyword parsed from the target
        address. Can be None.
    :type suggested_keyword: string
    :param msg: The received package message
    :type msg: :py:class:`email.message.Message` or an equivalent interface
        object

    :returns: The name of the keyword.
    :rtype: string
    """
    # Use a vendor-provided function to try and classify the message.
    keyword, _ = vendor.call('get_keyword', suggested_keyword, msg)
    if keyword:
        return keyword

    # Otherwise try getting the keyword from the address
    if suggested_keyword:
        return suggested_keyword

    # If we still do not have the keyword
    return 'default'


def approved_default(msg):
    """
    The function checks whether a message tagged with the default keyword should
    be approved, meaning that it gets forwarded to subscribers.

    :param msg: The received package message
    :type msg: :py:class:`email.message.Message` or an equivalent interface
        object
    """
    if 'X-Distro-Tracker-Approved' in msg:
        return True

    approved, implemented = vendor.call('approve_default_message', msg)
    if implemented:
        return approved
    else:
        return False


def add_new_headers(received_message, package_name, keyword):
    """
    The function adds new distro-tracker specific headers to the received
    message. This is used before forwarding the message to subscribers.

    The headers added by this function are used regardless whether the
    message is forwarded due to direct package subscriptions or a team
    subscription.

    :param received_message: The received package message
    :type received_message: :py:class:`email.message.Message` or an equivalent
        interface object

    :param package_name: The name of the package for which this message was
        intended.
    :type package_name: string

    :param keyword: The keyword with which the message should be tagged
    :type keyword: string
    """
    new_headers = [
        ('X-Loop', '{package}@{distro_tracker_fqdn}'.format(
            package=package_name,
            distro_tracker_fqdn=DISTRO_TRACKER_FQDN)),
        ('X-Distro-Tracker-Package', package_name),
        ('X-Distro-Tracker-Keyword', keyword),
    ]

    extra_vendor_headers, implemented = vendor.call(
        'add_new_headers', received_message, package_name, keyword)
    if implemented:
        new_headers.extend(extra_vendor_headers)

    add_headers(received_message, new_headers)


def add_direct_subscription_headers(received_message, package_name, keyword):
    """
    The function adds headers to the received message which are specific for
    messages to be sent to users that are directly subscribed to the package.
    """
    new_headers = [
        ('Precedence', 'list'),
        ('List-Unsubscribe',
            '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                control_email=DISTRO_TRACKER_CONTROL_EMAIL,
                package=package_name)),
    ]
    add_headers(received_message, new_headers)


def add_team_membership_headers(received_message, package_name, keyword, team):
    """
    The function adds headers to the received message which are specific for
    messages to be sent to users that are members of a team.
    """
    new_headers = [
        ('X-Distro-Tracker-Team', team.slug),
    ]
    add_headers(received_message, new_headers)


def add_headers(message, new_headers):
    """
    Adds the given headers to the given message in a safe way.
    """
    for header_name, header_value in new_headers:
        # With Python 2, make sure we are adding bytes to the message
        if six.PY2:
            header_name, header_value = (
                header_name.encode('utf-8'),
                header_value.encode('utf-8'))
        message[header_name] = header_value


def send_to_teams(received_message, package_name, keyword):
    """
    Sends the given email message to all members of each team that has the
    given package.

    The message is only sent to those users who have not muted the team
    and have the given keyword in teir set of keywords for the team
    membership.

    :param received_message: The modified received package message to be sent
        to the subscribers.
    :type received_message: :py:class:`email.message.Message` or an equivalent
        interface object

    :param package_name: The name of the package for which this message was
        intended.
    :type package_name: string

    :param keyword: The keyword with which the message should be tagged
    :type keyword: string
    """
    keyword = get_or_none(Keyword, name=keyword)
    package = get_or_none(PackageName, name=package_name)
    if not keyword or not package:
        return
    # Get all teams that have the given package
    teams = Team.objects.filter(packages=package)
    teams = teams.prefetch_related('team_membership_set')

    date = timezone.now().date()
    messages_to_send = []
    for team in teams:
        logger.info('dispatch :: sending to team %s', team.slug)
        team_message = deepcopy(received_message)
        add_team_membership_headers(
            team_message, package_name, keyword.name, team)

        # Send the message to each member of the team
        for membership in team.team_membership_set.all():
            # Do not send messages to muted memberships
            if membership.is_muted(package):
                continue
            # Do not send the message if the user has disabled the keyword
            if keyword not in membership.get_keywords(package):
                continue

            messages_to_send.append(prepare_message(
                team_message, membership.user_email.email, date))

    send_messages(messages_to_send, date)


def send_to_subscribers(received_message, package_name, keyword):
    """
    Sends the given email message to all subscribers of the package with the
    given name and those that accept messages tagged with the given keyword.

    :param received_message: The modified received package message to be sent
        to the subscribers.
    :type received_message: :py:class:`email.message.Message` or an equivalent
        interface object

    :param package_name: The name of the package for which this message was
        intended.
    :type package_name: string

    :param keyword: The keyword with which the message should be tagged
    :type keyword: string
    """
    # Make a copy of the message to be sent and add any headers which are
    # specific for users that are directly subscribed to the package.
    received_message = deepcopy(received_message)
    add_direct_subscription_headers(received_message, package_name, keyword)
    package = get_or_none(PackageName, name=package_name)
    if not package:
        return
    # Build a list of all messages to be sent
    date = timezone.now().date()
    messages_to_send = [
        prepare_message(received_message,
                        subscription.email_settings.user_email.email,
                        date)
        for subscription in package.subscription_set.all_active(keyword)
    ]
    send_messages(messages_to_send, date)


def send_messages(messages_to_send, date):
    """
    Sends all the given email messages over a single SMTP connection.
    """
    connection = get_connection()
    connection.send_messages(messages_to_send)

    for message in messages_to_send:
        logger.info("dispatch => %s", message.to[0])
        UserEmailBounceStats.objects.add_sent_for_user(email=message.to[0],
                                                       date=date)


def prepare_message(received_message, to_email, date):
    """
    Converts a message which is to be sent to a subscriber to a
    :py:class:`CustomEmailMessage
    <distro_tracker.core.utils.email_messages.CustomEmailMessage>`
    so that it can be sent out using Django's API.
    It also sets the required evelope-to value in order to track the bounce for
    the message.

    :param received_message: The modified received package message to be sent
        to the subscribers.
    :type received_message: :py:class:`email.message.Message` or an equivalent
        interface object

    :param to_email: The email of the subscriber to whom the message is to be
        sent
    :type to_email: string

    :param date: The date which should be used as the message's sent date.
    :type date: :py:class:`datetime.datetime`
    """
    bounce_address = 'bounces+{date}@{distro_tracker_fqdn}'.format(
        date=date.strftime('%Y%m%d'),
        distro_tracker_fqdn=DISTRO_TRACKER_FQDN)
    message = CustomEmailMessage(
        msg=patch_message_for_django_compat(received_message),
        from_email=verp.encode(bounce_address, to_email),
        to=[to_email])
    return message


def handle_bounces(sent_to_address):
    """
    Handles a received bounce message.

    :param sent_to_address: The envelope-to (return path) address to which the
        bounced email was returned.
    :type sent_to_address: string
    """
    bounce_email, user_email = verp.decode(sent_to_address)
    match = re.match(r'^bounces\+(\d{8})@' + DISTRO_TRACKER_FQDN, bounce_email)
    if not match:
        logger.warning('bounces :: invalid address %s', bounce_email)
        return
    try:
        date = datetime.strptime(match.group(1), '%Y%m%d')
    except ValueError:
        logger.warning('bounces :: invalid date in address %s', bounce_email)
        return
    UserEmailBounceStats.objects.add_bounce_for_user(email=user_email,
                                                     date=date)

    logger.info('bounces :: received one for %s/%s', user_email, date)
    user = UserEmailBounceStats.objects.get(email=user_email)
    if user.has_too_many_bounces():
        logger.info('bounces => %s has too many bounces', user_email)

        packages = [p.name for p in user.emailsettings.packagename_set.all()]
        email_body = distro_tracker_render_to_string(
            'dispatch/unsubscribed-due-to-bounces-email.txt', {
                'email': user_email,
                'packages': packages,
            })
        EmailMessage(
            subject='All your package subscriptions have been cancelled',
            from_email=settings.DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL,
            to=[user_email],
            cc=[settings.DISTRO_TRACKER_CONTACT_EMAIL],
            body=email_body,
            headers={
                'From': settings.DISTRO_TRACKER_CONTACT_EMAIL,
            },
        ).send()

        user.emailsettings.unsubscribe_all()
        for package in packages:
            logger.info('bounces :: removed %s from %s', user_email, package)
