from __future__ import unicode_literals


def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns None if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None


def extract_email_address_from_header(header):
    """
    Extracts the email address from the From email header.

    >>> str(extract_email_address_from_header('Real Name <foo@domain.com>'))
    'foo@domain.com'
    >>> str(extract_email_address_from_header('foo@domain.com'))
    'foo@domain.com'
    """
    from email.utils import parseaddr
    real_name, from_address = parseaddr(header)
    return from_address
