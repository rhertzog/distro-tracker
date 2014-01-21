# Copyright 2013 The Distro Tracker Developers
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

from distro_tracker.core.utils import message_from_bytes
from datetime import datetime

from distro_tracker.core.utils import extract_email_address_from_header
from distro_tracker.core.utils import get_or_none
from distro_tracker.core.utils import distro_tracker_render_to_string
from distro_tracker.core.utils import verp

from distro_tracker.core.utils.email_messages import CustomEmailMessage
from distro_tracker.mail.models import EmailUserBounceStats

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


def process(message, sent_to_address=None):
    """
    Handles the dispatching of received messages.

    :param message: The received message
    :type message: ``bytes``

    :param sent_to_address: The address to which the message was sent.
        Necessary in order to determine which package it was sent to.
    """
    assert isinstance(message, six.binary_type), 'Message must be given as bytes'
    msg = message_from_bytes(message)

    if sent_to_address is None:
        # No MTA was recognized, the last resort is to try and use the message
        # To header.
        sent_to_address = extract_email_address_from_header(msg['To'])

    if sent_to_address.startswith('bounces+'):
        return handle_bounces(sent_to_address)

    local_part = sent_to_address.split('@')[0]

    # Extract package name
    package_name = get_package_name(local_part)
    # Check loop
    package_email = '{package}@{distro_tracker_fqdn}'.format(package=package_name,
                                                  distro_tracker_fqdn=DISTRO_TRACKER_FQDN)
    if package_email in msg.get_all('X-Loop', ()):
        # Bad X-Loop, discard the message
        logger.info('Bad X-Loop, message discarded')
        return

    # Extract keyword
    keyword = get_keyword(local_part, msg)
    # Default keywords require special approvement
    if keyword == 'default' and not approved_default(msg):
        logger.info('Discarding default keyword message')
        return

    # Now send the message to subscribers
    add_new_headers(msg, package_name, keyword)
    send_to_subscribers(msg, package_name, keyword)
    send_to_teams(msg, package_name, keyword)


def get_package_name(local_part):
    """
    Extracts the name of the package from the local part of the email address
    to which the email was sent.

    The local part has two valid forms:
    - <package_name>_<keyword>
    - <package_name>

    In both cases, only the package name is returned.

    :param local_part: The local part of an email address
    :type local_part: string
    """
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        package_name = split[1]
    else:
        package_name = local_part
    return package_name


def get_keyword(local_part, msg):
    """
    Extracts the keywoword from the given message.

    The function first tries using a vendor-provided function
    :func:`get_keyword <distro_tracker.vendor.skeleton.rules.get_keyword>`.

    If the vendor did not implement this function or does not return a keyword
    for the given message, the function tries extracting the keyword from the
    ``local_part`` of the address (using :func:`get_keyword_from_address`).

    If this also does not yield a keyword, ``default`` is returned.

    :param local_part: The local part of the email address to which the message
        was sent.
    :type local_part: string
    :param msg: The received package message
    :type msg: :py:class:`email.message.Message` or an equivalent interface
        object

    :returns: The name of the keyword.
    :rtype: string
    """
    # Use a vendor-provided function to try and classify the message.
    keyword, _ = vendor.call('get_keyword', local_part, msg)
    if keyword:
        return keyword

    # Otherwise try getting the keyword from the address
    keyword = get_keyword_from_address(local_part)
    if keyword:
        return keyword

    # If we still do not have the keyword
    return 'default'


def get_keyword_from_address(local_part):
    """
    Tries to extract the keyword from the local part of the email address where
    the email was received.

    If the local part is in the form:
    <package_name>_<keyword>
    the keyword is returned.

    :returns: The extracted keyword
    :rtype: string or ``None``
    """
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        # Keyword found in the address
        return split[2]


def approved_default(msg):
    """
    The function checks whether a message tagged with the default keyword should
    be approved, meaning that it gets forwarded to subscribers.

    :param msg: The received package message
    :type msg: :py:class:`email.message.Message` or an equivalent interface
        object
    """
    if 'X-PTS-Approved' in msg:
        return True

    approved, implemented = vendor.call('approve_default_message', msg)
    if implemented:
        return approved
    else:
        return False


def add_new_headers(received_message, package_name, keyword):
    """
    The function adds new PTS-specific headers to the received message.
    This is used before forwarding the message to subscribers.

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
        ('X-PTS-Package', package_name),
        ('X-PTS-Keyword', keyword),
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
        ('X-PTS-Team', team.slug),
    ]
    add_headers(received_message, new_headers)


def add_headers(message, new_headers):
    """
    Adds the given headers to the given message in a safe way.
    """
    for header_name, header_value in new_headers:
        # Make sure we are adding bytes to the message
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
                team_message, membership.email_user.email, date))

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
        prepare_message(received_message, subscription.email_user.email, date)
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
        EmailUserBounceStats.objects.add_sent_for_user(email=message.to[0],
                                                       date=date)


def prepare_message(received_message, to_email, date):
    """
    Converts a message which is to be sent to a subscriber to a
    :py:class:`CustomEmailMessage <distro_tracker.core.utils.email_messages.CustomEmailMessage>`
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
        msg=received_message,
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
        # Invalid bounce address
        logger.error('Invalid bounce address ' + bounce_email)
        return
    try:
        date = datetime.strptime(match.group(1), '%Y%m%d')
    except ValueError:
        # Invalid bounce address
        logger.error('Invalid bounce address ' + bounce_email)
        return
    EmailUserBounceStats.objects.add_bounce_for_user(email=user_email,
                                                     date=date)

    logger.info('Logged bounce for {email} on {date}'.format(email=user_email,
                                                             date=date))
    user = EmailUserBounceStats.objects.get(user_email__email=user_email)
    if user.has_too_many_bounces():
        logger.info("{email} has too many bounces".format(email=user_email))

        email_body = distro_tracker_render_to_string(
            'dispatch/unsubscribed-due-to-bounces-email.txt', {
                'email': user_email,
                'packages': user.packagename_set.all()
            })
        EmailMessage(
            subject='All your subscriptions from the PTS have been cancelled',
            from_email=settings.DISTRO_TRACKER_BOUNCES_LIKELY_SPAM_EMAIL,
            to=[user_email],
            cc=[settings.DISTRO_TRACKER_CONTACT_EMAIL],
            body=email_body,
            headers={
                'From': settings.DISTRO_TRACKER_CONTACT_EMAIL,
            },
        ).send()

        user.unsubscribe_all()
