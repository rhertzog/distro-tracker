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
from email import message_from_string
from email.iterators import typed_subpart_iterator

from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from pts.control.commands import CommandFactory, CommandProcessor
from pts.core.utils import extract_email_address_from_header
from pts.core.utils import get_decoded_message_payload

import re

from django.conf import settings
PTS_CONTACT_EMAIL = settings.PTS_CONTACT_EMAIL
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL


def send_response(original_message, message_text, cc=None):
    subject = original_message.get('Subject')
    if not subject:
        subject = 'Your mail'
    message = EmailMessage(
        subject='Re: ' + subject,
        to=[original_message['From']],
        cc=cc,
        from_email=PTS_CONTACT_EMAIL,
        headers={
            'X-Loop': PTS_CONTROL_EMAIL,
            'References': ' '.join((original_message.get('References', ''),
                                    original_message.get('Message-ID', ''))),
            'In-Reply-To': original_message.get('Message-ID', ''),
        },
        body=message_text,
    )

    message.send()


def send_plain_text_warning(original_message):
    WARNING_MESSAGE = render_to_string('control/email-plaintext-warning.txt')
    send_response(original_message, WARNING_MESSAGE)


def process(message):
    msg = message_from_string(message)
    if 'X-Loop' in msg and PTS_CONTROL_EMAIL in msg.get_all('X-Loop'):
        return
    # Get the first plain-text part of the message
    plain_text_part = next(typed_subpart_iterator(msg, 'text', 'plain'), None)
    if not plain_text_part:
        # There is no plain text in the email
        send_plain_text_warning(msg)
        return

    # Decode the plain text into a unicode string
    try:
        text = get_decoded_message_payload(plain_text_part)
    except UnicodeDecodeError:
        send_plain_text_warning(msg)
        return

    lines = extract_command_from_subject(msg) + text.splitlines()
    # Process the commands
    factory = CommandFactory({
        'email': extract_email_address_from_header(msg['From']),
    })
    processor = CommandProcessor(factory)
    processor.process(lines)

    # Send a response only if there were some commands processed
    if processor.is_success():
        send_response(
            msg, processor.get_output(), set(processor.get_sent_mails()))


def extract_command_from_subject(message):
    """
    Returns a command found in the subject of the email.
    """
    subject = message['Subject']
    if not subject:
        return []
    match = re.match(r'(?:Re\s*:\s*)?(.*)$',
                     message.get('Subject', ''),
                     re.IGNORECASE)
    return ['# Message subject', match.group(1)]
