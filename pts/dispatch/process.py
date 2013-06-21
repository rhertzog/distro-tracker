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
from django.utils import timezone

from email import message_from_string
from datetime import datetime

from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_or_none
from pts.core.utils import verp
from pts.core.utils import get_decoded_message_payload

from pts.dispatch.custom_email_message import CustomEmailMessage
from pts.dispatch.models import UserBounceInformation

from pts.core.models import Package
from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN

import re
import logging

logger = logging.getLogger(__name__)


def process(message, sent_to_address=None):
    """
    Handles the dispatching of received messages.
    """
    msg = message_from_string(message)

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


def approved_default(msg):
    if msg['X-Bugzilla-Product']:
        return True
    else:
        return msg['X-PTS-Approved'] is not None


def get_keyword(local_part, msg):
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        # Keyword found in the address
        return split[2]

    re_accepted_installed = re.compile('^Accepted|INSTALLED|ACCEPTED')
    re_comments_regarding = re.compile(r'^Comments regarding .*\.changes$')

    body = get_message_body(msg)
    xloop = msg.get_all('X-Loop', ())
    subject = msg.get('Subject', '')
    xdak = msg.get_all('X-DAK', '')
    debian_pr_message = msg.get('X-Debian-PR-Message', '')

    owner_match = 'owner@bugs.debian.org' in xloop

    if owner_match and debian_pr_message.startswith('transcript'):
        return 'bts-control'
    elif owner_match and debian_pr_message:
        return 'bts'
    elif xdak and re_accepted_installed.match(subject):
        if re.search(r'\.dsc\s*$', body, flags=re.MULTILINE):
            return 'upload-source'
        else:
            return 'upload-binary'
    elif xdak or re_comments_regarding.match(subject):
        return 'katie-other'

    return 'default'


def get_message_body(msg):
    """
    Returns the message body, joining together all parts into one string.
    """
    return '\n'.join(get_decoded_message_payload(part)
                     for part in msg.walk() if not part.is_multipart())


def get_package_name(local_part):
    split = re.split(r'(\S+)_(\S+)', local_part)
    if len(split) > 1:
        package_name = split[1]
    else:
        package_name = local_part
    return package_name


def prepare_message(received_message, to_email, date):
    bounce_address = 'bounces+{date}@{pts_fqdn}'.format(
        date=date.strftime('%Y%m%d'),
        pts_fqdn=PTS_FQDN)
    message = CustomEmailMessage(
        msg=received_message,
        from_email=verp.encode(bounce_address, to_email),
        to=[to_email])
    return message


def add_new_headers(received_message, package_name, keyword):
    new_headers = [
        ('X-Loop', '{package}@{pts_fqdn}'.format(
            package=package_name,
            pts_fqdn=PTS_FQDN)),
        ('X-PTS-Package', package_name),
        ('X-PTS-Keyword', keyword),
        ('X-Debian-Package', package_name),
        ('X-Debian', 'PTS'),
        ('Precedence', 'list'),
        ('List-Unsubscribe',
            '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                control_email=PTS_CONTROL_EMAIL,
                package=package_name)),
    ]
    for header_name, header_value in new_headers:
        received_message[header_name] = header_value


def send_to_subscribers(received_message, package_name, keyword):
    package = get_or_none(Package, name=package_name)
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
        UserBounceInformation.objects.add_sent_for_user(email=message.to[0],
                                                        date=date)


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
    UserBounceInformation.objects.add_bounce_for_user(email=user_email,
                                                      date=date)

    logger.info('Logged bounce for {email} on {date}'.format(email=user_email,
                                                             date=date))
    info = UserBounceInformation.objects.get(email_user__email=user_email)
    if info.has_too_many_bounces():
        info.email_user.unsubscribe_all()
