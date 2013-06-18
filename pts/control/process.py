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

from pts.control.commands import CommandFactory
from pts.control.commands import QuitCommand
from pts.core.utils import extract_email_address_from_header

from django.conf import settings
PTS_OWNER_EMAIL = settings.PTS_OWNER_EMAIL
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL
MAX_ALLOWED_ERRORS = settings.PTS_MAX_ALLOWED_ERRORS_CONTROL_COMMANDS


def send_response(original_message, message_text, cc=None):
    subject = original_message.get('Subject')
    if not subject:
        subject = 'Your mail'
    message = EmailMessage(
        subject='Re: ' + subject,
        to=[original_message['From']],
        cc=cc,
        from_email=PTS_OWNER_EMAIL,
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
    if 'X-Loop' in message and PTS_CONTROL_EMAIL in msg.get_all('X-Loop'):
        return
    # Get the first plain-text part of the message
    plain_text_part = next(typed_subpart_iterator(msg, 'text', 'plain'), None)
    if not plain_text_part:
        # There is no plain text in the email
        send_plain_text_warning(msg)
        return

    # Decode the plain text into a unicode string
    charset = plain_text_part.get_content_charset('ascii')
    try:
        text = plain_text_part.get_payload(decode=True).decode(charset)
    except UnicodeDecodeError:
        send_plain_text_warning(msg)
        return

    # Process the commands
    out = []
    errors = 0
    processed = set()
    cc = []
    factory = CommandFactory({
        'email': extract_email_address_from_header(msg['From']),
    })
    # Each line is a separate command
    for line in text.splitlines():
        line = line.strip().lower()
        out.append('>' + line)

        if not line:
            continue
        command = factory.get_command_function(line)

        if not command:
            errors += 1
            if errors == MAX_ALLOWED_ERRORS:
                out.append('{MAX_ALLOWED_ERRORS} lines contain errors: stopping.')
                break
        else:
            if command.get_command_text() not in processed:
                # Only process the command if it was not previously processed.
                command_output = command()
                if not command_output:
                    command_output = ''
                out.append(command_output)
                # Send a CC of the response message to any email address that
                # the command sent a mail to.
                cc.extend(command.sent_mails)
                processed.add(command.get_command_text())

        if isinstance(command, QuitCommand):
            break

    # Send a response only if there were some commands processed
    if processed:
        send_response(msg, '\n'.join(out), set(cc))
