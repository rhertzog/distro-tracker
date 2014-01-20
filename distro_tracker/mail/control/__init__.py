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
Module implementing the processing of email control messages.
"""
from __future__ import unicode_literals
from email.iterators import typed_subpart_iterator

from django.core.mail import EmailMessage
from django.utils import six
from django.template.loader import render_to_string
from distro_tracker.core.utils import pts_render_to_string
from distro_tracker.core.utils import message_from_bytes
from distro_tracker.core.utils import extract_email_address_from_header
from distro_tracker.core.utils import get_decoded_message_payload

from distro_tracker.mail.control.commands import CommandFactory
from distro_tracker.mail.control.commands import CommandProcessor
from distro_tracker.mail.models import CommandConfirmation

import re

from django.conf import settings
PTS_CONTACT_EMAIL = settings.PTS_CONTACT_EMAIL
PTS_BOUNCES_EMAIL = settings.PTS_BOUNCES_EMAIL
PTS_CONTROL_EMAIL = settings.PTS_CONTROL_EMAIL


def send_response(original_message, message_text, cc=None):
    """
    Helper function which sends an email message in response to a control
    message.

    :param original_message: The received control message.
    :type original_message: :py:class:`email.message.Message` or an object with
        an equivalent interface
    :param message_text: The text which should be included in the body of the
        response.
    :param cc: A list of emails which should receive a CC of the response.
    """
    subject = original_message.get('Subject')
    if not subject:
        subject = 'Your mail'
    message = EmailMessage(
        subject='Re: ' + subject,
        to=[original_message['From']],
        cc=cc,
        from_email=PTS_BOUNCES_EMAIL,
        headers={
            'From': PTS_CONTACT_EMAIL,
            'X-Loop': PTS_CONTROL_EMAIL,
            'References': ' '.join((original_message.get('References', ''),
                                    original_message.get('Message-ID', ''))),
            'In-Reply-To': original_message.get('Message-ID', ''),
        },
        body=message_text,
    )

    message.send()


def send_plain_text_warning(original_message):
    """
    Sends an email warning the user that his control message could not be
    decoded due to not being a text/plain message.

    :param original_message: The received control message.
    :type original_message: :py:class:`email.message.Message` or an object with
        an equivalent interface
    """
    WARNING_MESSAGE = render_to_string('control/email-plaintext-warning.txt')
    send_response(original_message, WARNING_MESSAGE)


class ConfirmationSet(object):
    """
    A class which keeps track of all confirmations which are required during a
    single control process run.  This is necessary in order to send the emails
    asking for confirmation only when all commands are processed.
    """
    def __init__(self):
        self.commands = {}
        self.confirmation_messages = {}

    def add_command(self, email, command_text, confirmation_message):
        """
        Adds a command to the list of all commands which need to be confirmed.

        :param email: The email of the user the command references.
        :param command_text: The text of the command which needs to be
            confirmed.
        :param confirmation_message: An extra message to be included in the
            email when asking for confirmation of this command. This is usually
            an explanation of what the effect of the command is.
        """
        self.commands.setdefault(email, [])
        self.confirmation_messages.setdefault(email, [])

        self.commands[email].append(command_text)
        self.confirmation_messages[email].append(confirmation_message)

    def _ask_confirmation(self, email, commands, messages):
        """
        Sends a confirmation mail to a single user. Includes all commands that
        the user needs to confirm.
        """
        command_confirmation = CommandConfirmation.objects.create_for_commands(
            commands=commands)
        message = pts_render_to_string(
            'control/email-confirmation-required.txt', {
                'command_confirmation': command_confirmation,
                'confirmation_messages': self.confirmation_messages[email],
            }
        )
        subject = 'CONFIRM ' + command_confirmation.confirmation_key

        EmailMessage(
            subject=subject,
            to=[email],
            from_email=PTS_BOUNCES_EMAIL,
            headers={
                'From': PTS_CONTROL_EMAIL,
            },
            body=message,
        ).send()

    def ask_confirmation_all(self):
        """
        Sends a confirmation mail to all users which have been registered by
        using :py:meth:`add_command`.
        """
        for email, commands in self.commands.items():
            self._ask_confirmation(
                email, commands, self.confirmation_messages[email])

    def get_emails(self):
        """
        :returns: A unique list of emails which will receive a confirmation
            mail since there exists at least one command which references
            this user's email.
        """
        return self.commands.keys()


def process(message):
    """
    The function which actually processes a received command email message.

    :param message: The received command email message.
    :type message: ``bytes``
    """
    assert isinstance(message, six.binary_type), 'Message must be given as bytes'
    msg = message_from_bytes(message)
    # msg = message_from_string(message)
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
    confirmation_set = ConfirmationSet()
    processor = CommandProcessor(factory)
    processor.confirmation_set = confirmation_set
    processor.process(lines)

    confirmation_set.ask_confirmation_all()
    # Send a response only if there were some commands processed
    if processor.is_success():
        send_response(
            msg, processor.get_output(), set(confirmation_set.get_emails()))


def extract_command_from_subject(message):
    """
    Returns a command found in the subject of the email.

    :param message: An email message.
    :type message: :py:class:`email.message.Message` or an object with
        an equivalent interface
    """
    subject = message['Subject']
    if not subject:
        return []
    match = re.match(r'(?:Re\s*:\s*)?(.*)$',
                     message.get('Subject', ''),
                     re.IGNORECASE)
    return ['# Message subject', match.group(1)]
