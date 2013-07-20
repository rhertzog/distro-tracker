# Copyright 2013 The Debian Package Tracking System Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/ptsauthors
#
# This file is part of the Package Tracking System. It is subject to the
# license terms in the LICENSE file found in the top-level directory of
# this distribution and at http://deb.li/ptslicense. No part of the Package
# Tracking System, including this file, may be copied, modified, propagated, or
# distributed except according to the terms contained in the LICENSE file.

from __future__ import unicode_literals
from django.core.mail import get_connection
from django.utils import six
from django.utils import timezone
from django.core.mail import EmailMessage

from pts.core.utils import message_from_bytes
from datetime import datetime

from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_or_none
from pts.core.utils import pts_render_to_string
from pts.core.utils import verp

from pts.core.utils.email_messages import CustomEmailMessage
from pts.dispatch.models import EmailUserBounceStats

from pts.core.models import PackageName
from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN

import re
import logging

logger = logging.getLogger(__name__)

from pts import vendor


def process(message, sent_to_address=None):
    """
    Handles the dispatching of received messages.
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
    package_email = '{package}@{pts_fqdn}'.format(package=package_name,
                                                  pts_fqdn=PTS_FQDN)
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


def get_package_name(local_part):
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        package_name = split[1]
    else:
        package_name = local_part
    return package_name


def get_keyword(local_part, msg):
    keyword = get_keyword_from_address(local_part)
    if keyword:
        return keyword

    # Use a vendor-provided function to try and classify the message.
    keyword, _ = vendor.call('get_keyword', local_part, msg)
    if keyword:
        return keyword

    # If we still do not have the keyword
    return 'default'


def get_keyword_from_address(local_part):
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        # Keyword found in the address
        return split[2]


def approved_default(msg):
    if 'X-PTS-Approved' in msg:
        return True

    approved, implemented = vendor.call('approve_default_message', msg)
    if implemented:
        return approved
    else:
        return False


def add_new_headers(received_message, package_name, keyword):
    new_headers = [
        ('X-Loop', '{package}@{pts_fqdn}'.format(
            package=package_name,
            pts_fqdn=PTS_FQDN)),
        ('X-PTS-Package', package_name),
        ('X-PTS-Keyword', keyword),
        ('Precedence', 'list'),
        ('List-Unsubscribe',
            '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                control_email=PTS_CONTROL_EMAIL,
                package=package_name)),
    ]

    extra_vendor_headers, implemented = vendor.call(
        'add_new_headers', received_message, package_name, keyword)
    if implemented:
        new_headers.extend(extra_vendor_headers)

    for header_name, header_value in new_headers:
        received_message[header_name] = header_value


def send_to_subscribers(received_message, package_name, keyword):
    package = get_or_none(PackageName, name=package_name)
    if not package:
        return
    # Build a list of all messages to be sent
    date = timezone.now().date()
    messages_to_send = [
        prepare_message(received_message, subscription.email_user.email, date)
        for subscription in package.subscription_set.all_active(keyword)
    ]
    # Send all messages over a single SMTP connection
    connection = get_connection()
    connection.send_messages(messages_to_send)

    for message in messages_to_send:
        EmailUserBounceStats.objects.add_sent_for_user(email=message.to[0],
                                                       date=date)


def prepare_message(received_message, to_email, date):
    bounce_address = 'bounces+{date}@{pts_fqdn}'.format(
        date=date.strftime('%Y%m%d'),
        pts_fqdn=PTS_FQDN)
    message = CustomEmailMessage(
        msg=received_message,
        from_email=verp.encode(bounce_address, to_email),
        to=[to_email])
    return message


def handle_bounces(sent_to_address):
    """
    Handles a received bounce message.
    """
    bounce_email, user_email = verp.decode(sent_to_address)
    match = re.match(r'^bounces\+(\d{8})@' + PTS_FQDN, bounce_email)
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
    user = EmailUserBounceStats.objects.get(email=user_email)
    if user.has_too_many_bounces():
        logger.info("{email} has too many bounces".format(email=user_email))

        email_body = pts_render_to_string(
            'dispatch/unsubscribed-due-to-bounces-email.txt', {
                'email': user_email,
                'packages': user.packagename_set.all()
            })
        EmailMessage(
            subject='All your subscriptions from the PTS have been cancelled',
            from_email=settings.PTS_BOUNCE_NO_REPLY_EMAIL,
            to=[user_email],
            cc=[settings.PTS_CONTACT_EMAIL],
            body=email_body,
            headers={
                'From': settings.PTS_CONTACT_EMAIL,
            },
        ).send()

        user.unsubscribe_all()
