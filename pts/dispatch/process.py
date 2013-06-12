from __future__ import unicode_literals
from django.core.mail import EmailMessage
from django.core.mail import get_connection

from email import message_from_string
from email.iterators import typed_subpart_iterator

from core.utils import extract_email_address_from_header
from core.utils import DuplicateDict
from core.utils import get_or_none

from core.models import Package
from django.conf import settings
OWNER_EMAIL_ADDRESS = getattr(settings, 'OWNER_EMAIL_ADDRESS')
CONTROL_EMAIL_ADDRESS = getattr(settings, 'CONTROL_EMAIL_ADDRESS')


def process(message, local_part=None):
    """
    Handles the dispatching of received messages.
    """
    msg = message_from_string(message)

    if local_part is None:
        from_email = extract_email_address_from_header(msg['To'])
        local_part = from_email.split('@')[0]

    package_name = local_part

    send_to_subscribers(msg, package_name)


def prepare_message(received_message, package_name, to_email):
    headers = extract_headers(received_message)
    add_new_headers(headers, package_name)
    content = extract_content(received_message)
    message = EmailMessage(
        subject=headers['Subject'],
        from_email=headers['From'],
        headers=headers,
        body=content,
        to=[to_email]
    )

    return message


def add_new_headers(headers, package_name):
    new_headers = [
        ('X-Loop', '{package}@packages.qa.debian.org'.format(
            package=package_name)),
        ('X-PTS-Package', package_name),
        ('X-Debian-Package', package_name),
        ('X-Debian', 'PTS'),
        ('Precedence', 'list'),
        ('List-Unsubscribe',
            '<mailto:{control_email}?body=unsubscribe%20{package}>'.format(
                control_email=CONTROL_EMAIL_ADDRESS,
                package=package_name)),
    ]
    for header_name, header_value in new_headers:
        headers.add(header_name, header_value)


def extract_headers(received_message):
    headers = DuplicateDict()
    for key, value in received_message.items():
        if key.lower() == 'to':
            continue
        headers.add(key, value)
    return headers


def extract_content(msg):
    plain_text_part = next(typed_subpart_iterator(msg, 'text', 'plain'), None)
    if not plain_text_part:
        # There is no plain text in the email
        return ''

    # Decode the plain text into a unicode string
    charset = plain_text_part.get_content_charset('ascii')
    try:
        text = plain_text_part.get_payload(decode=True).decode(charset)
    except UnicodeDecodeError:
        return ''
    return text


def send_to_subscribers(received_message, package_name):
    package = get_or_none(Package, name=package_name)
    if not package:
        return
    # Build a list of all messages to be sent
    messages_to_send = [
        prepare_message(received_message,
                        package_name,
                        subscriber.email)
        for subscriber in package.subscriptions.all()
    ]
    # Send all messages over a single SMTP connection
    connection = get_connection()
    connection.send_messages(messages_to_send)
