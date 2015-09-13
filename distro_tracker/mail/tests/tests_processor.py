# -*- coding: utf-8 -*-

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
Tests for :mod:`distro_tracker.mail.processor`.
"""
from __future__ import unicode_literals
from email.message import Message

from django.conf import settings
from django.test.utils import override_settings
from django.utils.six.moves import mock

from distro_tracker.test import TestCase
from distro_tracker.mail.processor import MailProcessor
from distro_tracker.mail.processor import ConflictingDeliveryAddresses
from distro_tracker.mail.processor import InvalidDeliveryAddress
from distro_tracker.mail.processor import MissingDeliveryAddress


@override_settings(DISTRO_TRACKER_FQDN='tracker.debian.org')
class MailProcessorTest(TestCase):
    def setUp(self):
        """Create a MailProcessor object"""
        self.msg = Message()
        self.processor = MailProcessor(self.msg)
        self.DOMAIN = settings.DISTRO_TRACKER_FQDN

    def _test_find_addr_with(self, field):
        to_addr = 'foo@{}'.format(self.DOMAIN)
        self.msg.add_header(field, to_addr)
        addr = self.processor.find_delivery_address(self.msg)
        self.assertEqual(to_addr, addr)

    def test_find_addr_with_delivered_to(self):
        """Delivered-To is found and used"""
        self._test_find_addr_with('Delivered-To')

    def test_find_addr_with_envelope_to(self):
        """Envelope-To is found and used"""
        self._test_find_addr_with('Envelope-To')

    def test_find_addr_with_x_original_to(self):
        """X-Original-To is found and used"""
        self._test_find_addr_with('X-Original-To')

    def test_find_addr_with_x_envelope_to(self):
        """X-Envelope-To is found and used"""
        self._test_find_addr_with('X-Envelope-To')

    @override_settings(DISTRO_TRACKER_FQDN='domain.test')
    def test_find_addr_ignores_bad_domain(self):
        """Headers pointing to domain that do not match the FQDN are ignored """
        to_addr = 'foo@{}'.format(self.DOMAIN)
        # Entirely different domain should be ignored
        self.msg.add_header('Envelope-To', to_addr)
        self.msg.add_header('Delivered-To', to_addr)
        # Subdomains should be ignored too
        self.msg.add_header('Delivered-To', 'foo@bar.domain.test')
        addr = self.processor.find_delivery_address(self.msg)
        self.assertIsNone(addr)

    def test_find_addr_with_multiple_field_copies(self):
        """All copies of the same fields are parsed"""
        to_addr = 'foo@{}'.format(self.DOMAIN)
        self.msg.add_header('Delivered-To', 'foo@bar')
        self.msg.add_header('Delivered-To', to_addr)
        self.msg.add_header('Delivered-To', 'foo@baz')
        addr = self.processor.find_delivery_address(self.msg)
        self.assertEqual(to_addr, addr)

    def test_find_addr_conflicting(self):
        """Fails when encountering multiple headers with the same domain"""
        self.msg.add_header('Delivered-To', 'foo@{}'.format(self.DOMAIN))
        self.msg.add_header('Delivered-To', 'bar@{}'.format(self.DOMAIN))
        with self.assertRaises(ConflictingDeliveryAddresses):
            self.processor.find_delivery_address(self.msg)

    def test_identify_service_without_details(self):
        """identify_service(foo@bar) returns (foo, None)"""
        (service, details) = self.processor.identify_service('foo@bar')
        self.assertEqual(service, 'foo')
        self.assertIsNone(details)

    def test_identify_service_with_details(self):
        """identify_service(foo+baz@bar) returns (foo, baz)"""
        (service, details) = self.processor.identify_service('foo+baz@bar')
        self.assertEqual(service, 'foo')
        self.assertEqual(details, 'baz')

    def test_identify_service_with_details_with_plus(self):
        """identify_service(foo+baz+baz@bar) returns (foo, baz+baz)"""
        (service, details) = self.processor.identify_service('foo+baz+baz@bar')
        self.assertEqual(service, 'foo')
        self.assertEqual(details, 'baz+baz')

    def _test_process_for_addr(self, local_part, method_name, *args, **kwargs):
        self.msg.add_header('Delivered-To',
                            '{}@{}'.format(local_part, self.DOMAIN))
        with mock.patch.object(self.processor, method_name) as func:
            self.processor.process()
            func.assert_called_once_with(*args, **kwargs)

    def test_process_control(self):
        '''control@ is processed by handle_control()'''
        self._test_process_for_addr('control', 'handle_control')

    def test_process_dispatch(self):
        '''dispatch@ is processed by handle_dispatch(None, None)'''
        self._test_process_for_addr('dispatch', 'handle_dispatch', None, None)

    def test_process_dispatch_with_package(self):
        '''dispatch+foo@ is processed by handle_dispatch(foo, None)'''
        self._test_process_for_addr('dispatch+foo', 'handle_dispatch',
                                    'foo', None)

    def test_process_dispatch_with_package_and_keyword(self):
        '''dispatch+foo_bar@ is processed by handle_dispatch(foo, bar)'''
        self._test_process_for_addr('dispatch+foo_bar', 'handle_dispatch',
                                    'foo', 'bar')

    def test_process_bounces(self):
        '''bounces+foo@ is processed by handle_bounces()'''
        self._test_process_for_addr('bounces+foo', 'handle_bounces', 'foo')

    def test_process_without_delivery_address(self):
        '''process() fails when no delivery address can be identified'''
        with self.assertRaises(MissingDeliveryAddress):
            self.processor.process()

    @override_settings(DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS=False)
    def test_process_unknown_service_fails(self):
        '''process() fails when delivery address is not a known service'''
        self.msg.add_header('Delivered-To', 'unknown@{}'.format(self.DOMAIN))
        with self.assertRaises(InvalidDeliveryAddress):
            self.processor.process()

    @override_settings(DISTRO_TRACKER_ACCEPT_UNQUALIFIED_EMAILS=True)
    def test_process_unknown_service_works_as_dispatch(self):
        '''process() fails when delivery address is not a known service'''
        self._test_process_for_addr('unknown', 'handle_dispatch', 'unknown',
                                    None)
