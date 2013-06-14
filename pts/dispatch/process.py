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

from email import message_from_string

from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_or_none

from pts.dispatch.custom_email_message import CustomEmailMessage

from pts.core.models import Package
from django.conf import settings
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
PTS_FQDN = settings.PTS_FQDN


def process(message, sent_to_address=None):
    """
    Handles the dispatching of received messages.
    """
    msg = message_from_string(message)

    if sent_to_address is None:
        # No MTA was recognized, the last resort is to try and use the message
        # To header.
        sent_to_address = extract_email_address_from_header(msg['To'])
    local_part = sent_to_address.split('@')[0]

    package_name = local_part

    add_new_headers(msg, package_name)
    send_to_subscribers(msg, package_name)


def prepare_message(received_message, to_email):
    message = CustomEmailMessage(msg=received_message, to=[to_email])
    return message


def add_new_headers(received_message, package_name):
    new_headers = [
        ('X-Loop', '{package}@{pts_fqdn}'.format(
            package=package_name,
            pts_fqdn=PTS_FQDN)),
        ('X-PTS-Package', package_name),
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


def send_to_subscribers(received_message, package_name):
    package = get_or_none(Package, name=package_name)
    if not package:
        return
    # Build a list of all messages to be sent
    messages_to_send = [
        prepare_message(received_message, subscriber.email)
        for subscriber in package.subscriptions.all()
    ]
    # Send all messages over a single SMTP connection
    connection = get_connection()
    connection.send_messages(messages_to_send)
