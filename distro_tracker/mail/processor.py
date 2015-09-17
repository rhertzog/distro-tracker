# Copyright 2015 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Module implementing the processing of incoming email messages.
"""
from __future__ import unicode_literals
from itertools import chain

from django.conf import settings

import distro_tracker.mail.control
import distro_tracker.mail.dispatch


class MailProcessorException(Exception):
    pass


class ConflictingDeliveryAddresses(MailProcessorException):
    """
    The message contained multiple headers with possible delivery addresses
    for the domain defined in settings.DISTRO_TRACKER_FQDN.
    """
    pass


class MissingDeliveryAddress(MailProcessorException):
    """
    The message contained no header with a delivery address for the domain
    defined in settings.DISTRO_TRACKER_FQDN.
    """
    pass


class InvalidDeliveryAddress(MailProcessorException):
    """
    The message contained a delivery address for the domain defined in
    settings.DISTRO_TRACKER_FQDN but it did not match any known Distro Tracker
    service.
    """
    pass


class MailProcessor(object):
    """
    Takes an incoming email and do something useful out of it.

    To this end, it must find out where the email was sent
    and adjust the processing depending on the role of
    the target address.
    """

    def __init__(self, message):
        self.message = message

    @staticmethod
    def find_delivery_address(message):
        """
        Identify the email address the message was delivered to.

        The message headers Delivered-To, Envelope-To, X-Original-To, and
        X-Envelope-To are scanned to find out an email that matches the FQDN of
        the Distro Tracker setup.
        """
        addresses = []
        for field in chain(message.get_all('Delivered-To', []),
                           message.get_all('Envelope-To', []),
                           message.get_all('X-Original-To', []),
                           message.get_all('X-Envelope-To', [])):
            if field.endswith('@' + settings.DISTRO_TRACKER_FQDN):
                addresses.append(field)
        if len(addresses) > 1:
            raise ConflictingDeliveryAddresses()
        elif len(addresses) == 1:
            return addresses[0]

    @staticmethod
    def identify_service(address):
        """
        Identify service associated to target email and extract optional args.

        The address has the generic form <service>+<details>@<fqdn>.
        """
        local_part = address.split('@', 1)[0]
        if '+' in local_part:
            return local_part.split('+', 1)
        else:
            return (local_part, None)

    def process(self):
        """
        Process the message stored in self.message.

        Find out the delivery address and identify the associated service.
        Then defer to handle_*() for service-specific processing. Can raise
        MissingDeliveryAddress and UnknownService
        """
        addr = self.find_delivery_address(self.message)
        if addr is None:
            raise MissingDeliveryAddress()
        service, details = self.identify_service(addr)
        if service == 'dispatch':
            package, keyword = (details, None)
            if details and '_' in details:
                package, keyword = details.split('_', 1)
            self.handle_dispatch(package, keyword)
        elif service == 'bounces':
            self.handle_bounces(details)
        elif service == 'control':
            self.handle_control()
        elif settings.DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS:
            package, keyword = (addr.split('@', 1)[0], None)
            if package and '_' in package:
                package, keyword = package.split('_', 1)
            self.handle_dispatch(package, keyword)
        else:
            raise InvalidDeliveryAddress(
                '{} is not a valid Distro Tracker address'.format(addr))

    @staticmethod
    def build_delivery_address(service, details):
        local_part = service
        if details:
            local_part += '+' + details
        return '{}@{}'.format(local_part, settings.DISTRO_TRACKER_FQDN)

    def handle_control(self):
        distro_tracker.mail.control.process(self.message)

    def handle_bounces(self, details):
        sent_to_addr = self.build_delivery_address('bounces', details)
        distro_tracker.mail.dispatch.handle_bounces(sent_to_addr)

    def handle_dispatch(self, package=None, keyword=None):
        distro_tracker.mail.dispatch.process(self.message, package=package,
                                             keyword=keyword)
