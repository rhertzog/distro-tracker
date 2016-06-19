# -*- coding: utf-8 -*-

# Copyright 2013-2016 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core utils.
"""
from __future__ import unicode_literals
import datetime
from email import encoders
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
import os
import time
import tempfile

from debian import deb822
from django.core import mail
from django.test.utils import override_settings
from django.utils import six
from django.utils.http import http_date
from django.utils.functional import curry
from django.utils.six.moves import mock

from distro_tracker.core.models import Repository
from distro_tracker.core.utils import verp
from distro_tracker.core.utils import message_from_bytes
from distro_tracker.core.utils import now
from distro_tracker.core.utils import SpaceDelimitedTextField
from distro_tracker.core.utils import PrettyPrintList
from distro_tracker.core.utils import verify_signature
from distro_tracker.core.utils.packages import AptCache
from distro_tracker.core.utils.packages import extract_vcs_information
from distro_tracker.core.utils.packages import extract_dsc_file_name
from distro_tracker.core.utils.packages import package_hashdir
from distro_tracker.core.utils.datastructures import DAG, InvalidDAGException
from distro_tracker.core.utils.email_messages import CustomEmailMessage
from distro_tracker.core.utils.email_messages import decode_header
from distro_tracker.core.utils.email_messages import (
    name_and_address_from_string,
    names_and_addresses_from_string)
from distro_tracker.core.utils.email_messages import unfold_header
from distro_tracker.core.utils.linkify import linkify
from distro_tracker.core.utils.linkify import LinkifyDebianBugLinks
from distro_tracker.core.utils.linkify import LinkifyUbuntuBugLinks
from distro_tracker.core.utils.linkify import LinkifyHttpLinks
from distro_tracker.core.utils.linkify import LinkifyCVELinks
from distro_tracker.core.utils.http import HttpCache
from distro_tracker.core.utils.http import get_resource_content
from distro_tracker.test import TestCase, SimpleTestCase
from distro_tracker.test.utils import set_mock_response
from distro_tracker.test.utils import make_temp_directory


class VerpModuleTest(SimpleTestCase):
    """
    Tests for the ``distro_tracker.core.utils.verp`` module.
    """
    def test_encode(self):
        """
        Tests for the encode method.
        """
        self.assertEqual(
            verp.encode('itny-out@domain.com', 'node42!ann@old.example.com'),
            'itny-out-node42+21ann=old.example.com@domain.com')

        self.assertEqual(
            verp.encode('itny-out@domain.com', 'tom@old.example.com'),
            'itny-out-tom=old.example.com@domain.com')

        self.assertEqual(
            verp.encode('itny-out@domain.com', 'dave+priority@new.example.com'),
            'itny-out-dave+2Bpriority=new.example.com@domain.com')

        self.assertEqual(
            verp.encode('bounce@dom.com', 'user+!%-:@[]+@other.com'),
            'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com')

    def test_decode(self):
        """
        Tests the decode method.
        """
        self.assertEqual(
            verp.decode('itny-out-dave+2Bpriority=new.example.com@domain.com'),
            ('itny-out@domain.com', 'dave+priority@new.example.com'))

        self.assertEqual(
            verp.decode('itny-out-node42+21ann=old.example.com@domain.com'),
            ('itny-out@domain.com', 'node42!ann@old.example.com'))

        self.assertEqual(
            verp.decode('bounce-addr+2B40=dom.com@asdf.com'),
            ('bounce@asdf.com', 'addr+40@dom.com'))

        self.assertEqual(
            verp.decode(
                'bounce-user+2B+21+25+2D+3A+40+5B+5D+2B=other.com@dom.com'),
            ('bounce@dom.com', 'user+!%-:@[]+@other.com'))

    def test_decode_lowercase_code(self):
        """Encoding of special characters with lowercase should work"""
        self.assertEqual(
            verp.decode(
                'bounce-user+2b+2d+3a=other.com@dom.com'),
            ('bounce@dom.com', 'user+-:@other.com'))

    def test_invariant_encode_decode(self):
        """
        Tests that decoding an encoded address returns the original pair.
        """
        from_email, to_email = 'bounce@domain.com', 'user@other.com'
        self.assertEqual(
            verp.decode(verp.encode(from_email, to_email)),
            (from_email, to_email))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
class CustomMessageFromBytesTest(TestCase):
    """
    Tests the ``distro_tracker.core.utils.message_from_bytes`` function.
    """
    def setUp(self):
        self.message_bytes = b"""MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Disposition: inline
Content-Transfer-Encoding: 8bit

"""
        self.body = "üßščć한글ᥡ╥ສए"
        self.message_bytes = self.message_bytes + self.body.encode('utf-8')

    def get_mock_connection(self):
        """
        Helper method returning a mock SMTP connection object.
        """
        import smtplib
        return mock.create_autospec(smtplib.SMTP, return_value={})

    def test_as_string_returns_bytes(self):
        """
        Tests that the as_string message returns bytes.
        """
        message = message_from_bytes(self.message_bytes)

        self.assertEqual(self.message_bytes, message.as_string())
        self.assertTrue(isinstance(message.as_string(), six.binary_type))

    def test_get_payload_decode_idempotent(self):
        """
        Tests that the get_payload method returns bytes which can be decoded
        using the message's encoding and that they are identical to the
        ones given to the function in the first place.
        """
        message = message_from_bytes(self.message_bytes)

        self.assertEqual(self.body,
                         message.get_payload(decode=True).decode('utf-8'))

    def test_integrate_with_django(self):
        """
        Tests that the message obtained by the message_from_bytes function can
        be sent out using the Django email API.

        In the same time, this test makes sure that Django keeps using
        the as_string method as expected.
        """
        from django.core.mail import get_connection
        backend = get_connection()
        # Replace the backend's SMTP connection with a mock.
        mock_connection = self.get_mock_connection()
        backend.connection = mock_connection
        # Send the message over the backend
        message = message_from_bytes(self.message_bytes)
        custom_message = CustomEmailMessage(
            msg=message,
            from_email='from@domain.com',
            to=['to@domain.com'])

        backend.send_messages([custom_message])
        backend.close()

        # The backend sent the mail over SMTP & it is not corrupted
        mock_connection.sendmail.assert_called_with(
            'from@domain.com',
            ['to@domain.com'],
            mock.ANY)
        self.assertEqual(
            mock_connection.sendmail.call_args[0][2].replace(b"\r\n", b"\n"),
            message.as_string())


class EmailUtilsTest(SimpleTestCase):
    def test_name_and_address_from_string(self):
        """
        Tests retrieving a name and address from a string which contains
        unquoted commas.
        """
        self.assertDictEqual(
            name_and_address_from_string(
                'John H. Robinson, IV <jaqque@debian.org>'),
            {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'}
        )

        self.assertDictEqual(
            name_and_address_from_string('email@domain.com'),
            {'name': '', 'email': 'email@domain.com'}
        )

        self.assertDictEqual(
            name_and_address_from_string('Name <email@domain.com>'),
            {'name': 'Name', 'email': 'email@domain.com'}
        )

        self.assertIsNone(name_and_address_from_string(''))

    def test_names_and_addresses_from_string(self):
        """
        Tests extracting names and emails from a string containing a list of
        them.
        """
        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'Name <email@domain.com>'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': 'Name', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(
            names_and_addresses_from_string(
                'John H. Robinson, IV <jaqque@debian.org>, '
                'email@domain.com'
            ), [
                {'name': 'John H. Robinson, IV', 'email': 'jaqque@debian.org'},
                {'name': '', 'email': 'email@domain.com'}
            ]
        )

        self.assertSequenceEqual(names_and_addresses_from_string(''), [])

    def test_unfold_header(self):
        test_values = {
            'a\n b': 'a b',
            'a\r\n b': 'a b',
            'a\n\tb': 'a\tb',
            'a\r\n\tb\n c\n\td': 'a\tb c\td',
            'a\n\t bc\n  d': 'a\t bc  d',
        }
        for folded, unfolded in test_values.items():
            self.assertEqual(unfold_header(folded), unfolded)


class CustomEmailMessageTest(TestCase):
    """
    Tests the ``CustomEmailMessage`` class.
    """
    def create_multipart(self):
        """
        Helper method creates a multipart message.
        """
        msg = MIMEMultipart()
        msg.attach(self.prepare_part(b'data'))
        return msg

    def prepare_part(self, data):
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(data)
        encoders.encode_base64(part)
        return part

    def test_sent_message_same_as_original(self):
        """
        Tests that an ``email.message.Message`` instance sent by using the
        ``CustomEmailMessage`` class is the same as the original message.
        """
        msg = self.create_multipart()
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertEqual(msg.as_string(), mail.outbox[0].message().as_string())

    def test_attachment_included(self):
        """
        Tests that an attachment included in the ``CustomEmailMessage``
        instance is sent with the rest of the message.
        """
        msg = self.create_multipart()
        attachment = self.prepare_part(b'new_data')
        msg.attach(attachment)
        custom_message = CustomEmailMessage(msg=msg, to=['recipient'])

        custom_message.send()

        self.assertIn(attachment, mail.outbox[0].message().get_payload())


class DAGTests(SimpleTestCase):
    """
    Tests for the `DAG` class.
    """
    def test_add_nodes(self):
        """
        Tests adding nodes to a DAG.
        """
        g = DAG()

        # A single node
        g.add_node(1)
        self.assertEqual(len(g.all_nodes), 1)
        self.assertEqual(g.all_nodes[0], 1)
        # Another one
        g.add_node(2)
        self.assertEqual(len(g.all_nodes), 2)
        self.assertIn(2, g.all_nodes)
        # When adding a same node again, nothing changes.
        g.add_node(1)
        self.assertEqual(len(g.all_nodes), 2)

    def test_add_edge(self):
        """
        Tests adding edges to a DAG.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)

        g.add_edge(1, 2)
        self.assertEqual(len(g.dependent_nodes(1)), 1)
        self.assertIn(2, g.dependent_nodes(1))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[1].id], 0)
        self.assertEqual(g.in_degree[g.nodes_map[2].id], 1)

        g.add_node(3)
        g.add_edge(1, 3)
        self.assertEqual(len(g.dependent_nodes(1)), 2)
        self.assertIn(3, g.dependent_nodes(1))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[1].id], 0)
        self.assertEqual(g.in_degree[g.nodes_map[3].id], 1)

        g.add_edge(2, 3)
        self.assertEqual(len(g.dependent_nodes(2)), 1)
        self.assertIn(3, g.dependent_nodes(2))
        # In-degrees updated
        self.assertEqual(g.in_degree[g.nodes_map[3].id], 2)

        # Add a same edge again - nothing changed?
        g.add_edge(1, 3)
        self.assertEqual(len(g.dependent_nodes(1)), 2)

        # Add an edge resulting in a cycle
        with self.assertRaises(InvalidDAGException):
            g.add_edge(3, 1)

    def test_remove_node(self):
        """
        Tests removing a node from the graph.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(1, 3)
        g.add_edge(2, 3)

        g.remove_node(3)
        self.assertNotIn(3, g.all_nodes)
        self.assertEqual(len(g.dependent_nodes(1)), 1)
        self.assertIn(2, g.dependent_nodes(1))
        self.assertEqual(len(g.dependent_nodes(2)), 0)

        g.remove_node(1)
        self.assertEqual(g.in_degree[g.nodes_map[2].id], 0)

    def test_find_no_dependency_node(self):
        """
        Tests that the DAG correctly returns nodes with no dependencies.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        self.assertEqual(g._get_node_with_no_dependencies().original, 1)

        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(3, 2)
        g.add_edge(2, 1)
        self.assertEqual(g._get_node_with_no_dependencies().original, 3)

        g = DAG()
        g.add_node(1)
        self.assertEqual(g._get_node_with_no_dependencies().original, 1)

    def test_topsort_simple(self):
        """
        Tests the topological sort of the DAG class.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        topsort = list(g.topsort_nodes())

        self.assertSequenceEqual([1, 2, 3], topsort)

    def test_topsort_no_dependencies(self):
        """
        Tests the toplogical sort of the DAG class when the given DAG has no
        dependencies between the nodes.
        """
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)

        topsort = list(g.topsort_nodes())

        nodes = [1, 2, 3]
        # The order in this case cannot be mandated, only that all the nodes
        # are in the output
        for node in nodes:
            self.assertIn(node, topsort)

    def test_topsort_complex(self):
        """
        Tests the toplogical sort when a more complex graph is given.
        """
        g = DAG()
        nodes = list(range(13))
        for node in nodes:
            g.add_node(node)
        edges = (
            (0, 1),
            (0, 2),
            (0, 3),
            (0, 5),
            (0, 6),
            (2, 3),
            (3, 4),
            (3, 5),
            (4, 9),
            (6, 4),
            (6, 9),
            (7, 6),
            (8, 7),
            (9, 10),
            (9, 11),
            (9, 12),
            (11, 12),
        )
        for edge in edges:
            g.add_edge(*edge)

        topsort = list(g.topsort_nodes())
        # Make sure all nodes are found in the toplogical sort
        for node in nodes:
            self.assertIn(node, topsort)
        # Make sure that all dependent nodes are found after the nodes they
        # depend on.
        # Invariant: for each edge (n1, n2) position(n2) in the topological
        # sort must be strictly greater than the position(n1).
        for node1, node2 in edges:
            self.assertTrue(topsort.index(node2) > topsort.index(node1))

    def test_topsort_string_nodes(self):
        """
        Tests the toplogical sort when strings are used for node objects.
        """
        g = DAG()
        nodes = ['shirt', 'pants', 'tie', 'belt', 'shoes', 'socks', 'pants']
        for node in nodes:
            g.add_node(node)
        edges = (
            ('shirt', 'tie'),
            ('shirt', 'belt'),
            ('belt', 'tie'),
            ('pants', 'tie'),
            ('pants', 'belt'),
            ('pants', 'shoes'),
            ('pants', 'shirt'),
            ('socks', 'shoes'),
            ('socks', 'pants'),
        )
        for edge in edges:
            g.add_edge(*edge)

        topsort = list(g.topsort_nodes())
        for node in nodes:
            self.assertIn(node, topsort)
        for node1, node2 in edges:
            self.assertTrue(topsort.index(node2) > topsort.index(node1))

    def test_nodes_reachable_from(self):
        """
        Tests finding all nodes reachable from a single node.
        """
        # Simple situation first.
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        self.assertEqual(len(g.nodes_reachable_from(1)), 2)
        self.assertIn(2, g.nodes_reachable_from(1))
        self.assertIn(3, g.nodes_reachable_from(1))
        self.assertEqual(len(g.nodes_reachable_from(2)), 1)
        self.assertIn(3, g.nodes_reachable_from(1))

        # No nodes reachable from the given node
        g = DAG()
        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_edge(2, 3)

        self.assertEqual(len(g.nodes_reachable_from(1)), 0)

        # More complex graph
        g = DAG()

        g.add_node(1)
        g.add_node(2)
        g.add_node(3)
        g.add_node(4)
        g.add_node(5)
        g.add_edge(1, 3)
        g.add_edge(2, 4)
        g.add_edge(2, 5)
        g.add_edge(4, 5)
        g.add_edge(5, 3)

        self.assertEqual(len(g.nodes_reachable_from(2)), 3)
        for node in range(3, 6):
            self.assertIn(node, g.nodes_reachable_from(2))
        self.assertEqual(len(g.nodes_reachable_from(1)), 1)
        self.assertIn(3, g.nodes_reachable_from(1))


class PrettyPrintListTest(SimpleTestCase):
    """
    Tests for the PrettyPrintList class.
    """
    def test_string_output(self):
        """
        Tests the output of a PrettyPrintList.
        """
        l = PrettyPrintList(['a', 'b', 'abe', 'q'])
        self.assertEqual(str(l), 'a b abe q')

        l = PrettyPrintList()
        self.assertEqual(str(l), '')

        l = PrettyPrintList([0, 'a', 1])
        self.assertEqual(str(l), '0 a 1')

    def test_list_methods_accessible(self):
        """
        Tests that list methods are accessible to the PrettyPrintList object.
        """
        l = PrettyPrintList()
        l.append('a')
        self.assertEqual(str(l), 'a')

        l.extend(['q', 'w'])
        self.assertEqual(str(l), 'a q w')

        l.pop()
        self.assertEqual(str(l), 'a q')

        # len works?
        self.assertEqual(len(l), 2)
        # Iterable?
        self.assertSequenceEqual(l, ['a', 'q'])
        # Indexable?
        self.assertEqual(l[0], 'a')
        # Comparable?
        l2 = PrettyPrintList(['a', 'q'])
        self.assertTrue(l == l2)
        l3 = PrettyPrintList()
        self.assertFalse(l == l3)
        # Comparable to plain lists?
        self.assertTrue(l == ['a', 'q'])
        self.assertFalse(l == ['a'])


class SpaceDelimitedTextFieldTest(SimpleTestCase):
    """
    Tests the SpaceDelimitedTextField class.
    """
    def setUp(self):
        self.field = SpaceDelimitedTextField()

    def test_list_to_field(self):
        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList(['a', 'b', 3])),
            'a b 3'
        )

        self.assertEqual(
            self.field.get_db_prep_value(PrettyPrintList()),
            ''
        )

    def test_field_to_list(self):
        self.assertEqual(
            self.field.to_python('a b 3'),
            PrettyPrintList(['a', 'b', '3'])
        )

        self.assertEqual(
            self.field.to_python(''),
            PrettyPrintList()
        )

    def test_sane_inverse(self):
        l = PrettyPrintList(['a', 'b', 'c'])
        self.assertEqual(
            self.field.to_python(self.field.get_db_prep_value(l)),
            l
        )


class PackageUtilsTests(SimpleTestCase):
    """
    Tests the distro_tracker.core.utils.packages utlity functions.
    """
    def test_get_vcs(self):
        browser_url = 'http://other-url.com'
        vcs_url = 'git://url.com'
        d = {
            'Vcs-Git': vcs_url,
            'Vcs-Browser': browser_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'browser': browser_url,
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Browser not found
        d = {
            'Vcs-Git': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'git',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # A VCS type longer than three letters
        d = {
            'Vcs-Darcs': vcs_url,
        }
        self.assertDictEqual(
            {
                'type': 'darcs',
                'url': vcs_url,
            },
            extract_vcs_information(d)
        )

        # Empty dict
        self.assertDictEqual({}, extract_vcs_information({}))
        # No vcs information in the dict
        self.assertDictEqual({}, extract_vcs_information({
            'stuff': 'that does not',
            'have': 'anything to do',
            'with': 'vcs'
        }))

    def test_package_hash_dir(self):
        self.assertEqual(package_hashdir("dpkg"), "d")
        self.assertEqual(package_hashdir("lua"), "l")
        self.assertEqual(package_hashdir("lib"), "lib")
        self.assertEqual(package_hashdir("libc6"), "libc")
        self.assertEqual(package_hashdir("lib+fancy"), "lib+")
        self.assertEqual(package_hashdir(""), "")
        self.assertEqual(package_hashdir(None), None)

    def test_extract_dsc_file_name(self):

        stanza = deb822.Sources(
            """Package: curl
Binary: curl
Version: 7.26.0
Maintainer: Maintainer <maintainer@domain.com>
Architecture: any
Standards-Version: 3.9.3
Format: 3.0 (quilt)
Files:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Checksums-Sha1:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Checksums-Sha256:
 {} 2531 dummy-package_7.26.0.dsc
 {} 3073624 dummy-package_7.26.0.orig.tar.gz
 {} 33360 dummy-package_7.26.0-1+wheezy3.debian.tar.gz
Directory: pool/updates/main/c/curl
Priority: source
Section: libs
""".format(
    '602b2a11624744e2e92353f5e76ad7e6',  # noqa
    '3fa4d5236f2a36ca5c3af6715e837691',  # noqa
    '2972826d5b1ebadace83f236e946b33f',  # noqa
    '50fd8c0de138e80903443927365565151291338c',  # noqa
    '66e1fd0312f62374b96fe02e644f66202fd6324b',  # noqa
    'a0f16b381d3ac3e02de307dced481eaf01b3ead1',  # noqa
    'daf4c6c8ad485f98cc6ad684b5de30d7d07e45e521a1a6caf148406f7c9993cd',  # noqa
    '79ccce9edb8aee17d20ad4d75e1f83a789f8c2e71e68f468e1bf8abf8933193f',  # noqa
    '335bf9f847e68df71dc0b9bd14863c6a8951198af3ac19fc67b8817835fd0e17',  # noqa
))  # noqa

        self.assertEqual(
            'dummy-package_7.26.0.dsc',
            extract_dsc_file_name(stanza)
        )

        # No input given
        self.assertIsNone(extract_dsc_file_name({}))
        # No files entry...
        self.assertIsNone(extract_dsc_file_name({
            'package': 'name',
            'version': 'version'
        }))


class HttpCacheTest(SimpleTestCase):
    def set_mock_response(self, mock_requests, headers=None, status_code=200):
        set_mock_response(
            mock_requests,
            text=self.response_content.decode('utf-8'),
            headers=headers,
            status_code=status_code)

    def setUp(self):
        # Set up a cache directory to use in the tests
        self.cache_directory = tempfile.mkdtemp(suffix='test-cache')
        # Set up a simple response content
        self.response_content = 'Simple response'
        self.response_content = self.response_content.encode('utf-8')

    def tearDown(self):
        # Remove the test directory
        import shutil
        shutil.rmtree(self.cache_directory)

    def test_parse_cache_control_header(self):
        """
        Tests the utility function for parsing a Cache-Control header into a
        dict.
        """
        from distro_tracker.core.utils.http import parse_cache_control_header
        header = 'must-revalidate, max-age=3600'
        d = parse_cache_control_header(header)
        self.assertIn('must-revalidate', d)
        self.assertIn('max-age', d)
        self.assertEqual(d['max-age'], '3600')

        header = 'max-age=0, private'
        d = parse_cache_control_header(header)
        self.assertIn('private', d)
        self.assertIn('max-age', d)
        self.assertEqual(d['max-age'], '0')

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_update_cache_new_item(self, mock_requests):
        """
        Tests the simple case of updating the cache with a new URL's response.
        """
        headers = {
            'Connection': 'Keep-Alive',
            'Content-Type': 'text/plain',
        }
        self.set_mock_response(mock_requests, headers=headers)
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        # The URL cannot be found in the cache at this point
        self.assertFalse(url in cache)

        response, updated = cache.update(url)

        # The returned response is correct
        self.assertEqual(self.response_content, response.content)
        self.assertEqual(200, response.status_code)
        # The return value indicates the cache has been updated
        self.assertTrue(updated)
        # The URL is now found in the cache
        self.assertTrue(url in cache)
        # The content is accessible through the cache
        self.assertEqual(self.response_content, cache.get_content(url))
        # The returned headers are accessible through the cache
        cached_headers = cache.get_headers(url)
        for key, value in headers.items():
            self.assertIn(key, cached_headers)
            self.assertEqual(value, cached_headers[key])

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_not_expired(self, mock_requests):
        """
        Tests that the cache knows a response is not expired based on its
        Cache-Control header.
        """
        self.set_mock_response(mock_requests, headers={
            'Cache-Control': 'must-revalidate, max-age=3600',
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertTrue(url in cache)
        self.assertFalse(cache.is_expired(url))

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_expired(self, mock_requests):
        """
        Tests that the cache knows when an entry with a stale Cache-Control
        header is expired.
        """
        self.set_mock_response(mock_requests, headers={
            'Cache-Control': 'must-revalidate, max-age=0',
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertTrue(url in cache)
        self.assertTrue(cache.is_expired(url))

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_conditional_get_last_modified(self, mock_requests):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with a Last-Modified header.
        """
        last_modified = http_date(time.time())
        self.set_mock_response(mock_requests, headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.response_content = b''
        self.set_mock_response(mock_requests, status_code=304)
        # Run the update again
        response, updated = cache.update(url)

        self.assertFalse(updated)
        mock_requests.get.assert_called_with(
            url, verify=False, allow_redirects=True,
            headers={'If-Modified-Since': last_modified})
        # The actual server's response is returned
        self.assertEqual(response.status_code, 304)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_conditional_get_last_modified_expired(self, mock_requests):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with a Last-Modified header, which has
        since expired.
        """
        last_modified = http_date(time.time() - 3600)
        self.set_mock_response(mock_requests, headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Set a new Last-Modified and content value
        new_last_modified = http_date(time.time())
        self.response_content = b'Response'
        self.set_mock_response(mock_requests, headers={
            'Last-Modified': new_last_modified
        })

        # Run the update again
        response, updated = cache.update(url)

        self.assertTrue(updated)
        self.assertEqual(200, response.status_code)
        # The new content is found in the cache
        self.assertEqual(self.response_content, cache.get_content(url))
        # The new Last-Modified is found in the headers cache
        self.assertEqual(
            new_last_modified,
            cache.get_headers(url)['Last-Modified']
        )

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_expires_header(self, mock_requests):
        """
        Tests that the cache knows that a cached response is not expired based
        on its Expires header.
        """
        expires = http_date(time.time() + 3600)
        self.set_mock_response(mock_requests, headers={
            'Expires': expires
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'

        cache.update(url)

        self.assertFalse(cache.is_expired(url))

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_expires_header_expired(self, mock_requests):
        """
        Tests that the cache knows that a cached response is expired based
        on its Expires header.
        """
        expires = http_date(time.time() - 3600)
        self.set_mock_response(mock_requests, headers={
            'Expires': expires
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.assertTrue(cache.is_expired(url))

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_cache_remove_url(self, mock_requests):
        """
        Tests removing a cached response.
        """
        self.set_mock_response(mock_requests)
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Sanity check - the url is cached
        self.assertTrue(url in cache)

        cache.remove(url)

        self.assertFalse(url in cache)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_conditional_get_etag(self, mock_requests):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with an ETag header
        """
        etag = '"466010a-11bf9-4e17efa8afb81"'
        self.set_mock_response(mock_requests, headers={
            'ETag': etag,
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        self.response_content = b''
        self.set_mock_response(mock_requests, status_code=304)
        # Run the update again
        response, updated = cache.update(url)

        self.assertFalse(updated)
        mock_requests.get.assert_called_with(
            url, verify=False, allow_redirects=True,
            headers={'If-None-Match': etag, })
        # The actual server's response is returned
        self.assertEqual(response.status_code, 304)

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_conditional_get_etag_expired(self, mock_requests):
        """
        Tests that the cache performs a conditional GET request when asked to
        update the response for a URL with an ETag header, which has since
        expired.
        """
        etag = '"466010a-11bf9-4e17efa8afb81"'
        self.set_mock_response(mock_requests, headers={
            'ETag': etag,
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)
        # Set a new ETag and content value
        new_etag = '"57ngfhty11bf9-9t831116kn1qw1'
        self.response_content = b'Response'
        self.set_mock_response(mock_requests, headers={
            'ETag': new_etag
        })

        # Run the update again
        response, updated = cache.update(url)

        self.assertTrue(updated)
        self.assertEqual(200, response.status_code)
        # The new content is found in the cache
        self.assertEqual(self.response_content, cache.get_content(url))
        # The new Last-Modified is found in the headers cache
        self.assertEqual(
            new_etag,
            cache.get_headers(url)['ETag']
        )

    @mock.patch('distro_tracker.core.utils.http.requests')
    def test_conditional_force_unconditional_get(self, mock_requests):
        """
        Tests that the users can force the cache to perform an unconditional
        GET when updating a cached resource.
        """
        last_modified = http_date(time.time())
        self.set_mock_response(mock_requests, headers={
            'Last-Modified': last_modified
        })
        cache = HttpCache(self.cache_directory)
        url = 'http://example.com'
        cache.update(url)

        # Run the update again
        response, updated = cache.update(url, force=True)

        # Make sure that we ask for a non-cached version
        mock_requests.get.assert_called_with(
            url, verify=False, allow_redirects=True,
            headers={'Cache-Control': 'no-cache'})
        self.assertTrue(updated)

    def test_get_resource_content_utlity_function_cached(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function when the resource is cached in the given cache
        instance.
        """
        mock_cache = mock.create_autospec(HttpCache)
        mock_cache.is_expired.return_value = False
        expected_content = b"Some content"
        mock_cache.get_content.return_value = expected_content
        url = 'http://some.url.com'

        content = get_resource_content(url, mock_cache)

        # The expected content is retrieved
        self.assertEqual(content, expected_content)
        # The function did not update the cache
        self.assertFalse(mock_cache.update.called)

    def test_get_resource_content_utility_function_not_cached(self):
        """
        Tests the :func:`distro_tracker.core.utils.http.get_resource_content`
        utility function when the resource is not cached in the given cache
        instance.
        """
        mock_cache = mock.create_autospec(HttpCache)
        mock_cache.is_expired.return_value = True
        expected_content = b"Some content"
        mock_cache.get_content.return_value = expected_content
        url = 'http://some.url.com'

        content = get_resource_content(url, mock_cache)

        self.assertEqual(content, expected_content)
        # The function updated the cache
        mock_cache.update.assert_called_once_with(url)


class VerifySignatureTest(SimpleTestCase):
    """
    Tests the :func:`distro_tracker.core.utils.verify_signature` function.
    """

    def setUp(self):
        self.TEST_KEYRING_DIRECTORY = tempfile.mkdtemp(suffix='-test-keyring')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.TEST_KEYRING_DIRECTORY)

    def test_signed_message(self):
        """
        Tests extracting the signature from a correctly signed message when the
        signer is found in the keyring.
        """
        self.import_key_into_keyring('key1.pub')
        file_path = self.get_test_data_path('signed-message')
        expected = [
            ('PTS Tests', 'fake-address@domain.com')
        ]

        with open(file_path, 'rb') as f:
            self.assertEqual(expected, verify_signature(f.read()))

    def test_signed_message_unknown_key(self):
        """
        Tests extracting the signature from a correctly signed message when the
        signer is not found in the keyring.
        """
        file_path = self.get_test_data_path('signed-message')

        with open(file_path, 'rb') as f:
            self.assertSequenceEqual([], verify_signature(f.read()))

    def test_incorrect_signature(self):
        """
        Tests extracting signature information when the signature itself is
        wrong.
        """
        with self.settings(
                DISTRO_TRACKER_KEYRING_DIRECTORY=self.TEST_KEYRING_DIRECTORY):
            self.assertIsNone(verify_signature(b"This is not a signature"))

    def test_utf8_content(self):
        """
        Tests extracting the signature from a message passed as unicode text
        instead of bytes.
        """
        self.import_key_into_keyring('key1.pub')
        file_path = self.get_test_data_path('signed-message')
        expected = [
            ('PTS Tests', 'fake-address@domain.com')
        ]

        with open(file_path, 'rb') as f:
            content = f.read().decode('utf-8')
            self.assertEqual(expected, verify_signature(content))


class DecodeHeaderTest(SimpleTestCase):
    """
    Tests for :func:`distro_tracker.core.utils.email_messages.decode_header`.
    """
    def test_decode_header_iso(self):
        """
        Single part iso-8859-1 encoded text.
        """
        h = Header(b'M\xfcnchen', 'iso-8859-1')
        header_text = decode_header(h)
        self.assertEqual('München', header_text)

    def test_decode_header_utf8(self):
        """
        Single part utf-8 encoded text.
        """
        h = Header(b'M\xc3\xbcnchen', 'utf-8')
        header_text = decode_header(h)
        self.assertEqual('München', header_text)

    def test_decode_header_multipart(self):
        """
        Two part header: iso-8859-1 and utf-8
        """
        h = Header(b'M\xfcnchen', 'iso-8859-1')
        h.append(b' M\xc3\xbcnchen', 'utf-8')
        header_text = decode_header(h)
        self.assertEqual('München München', header_text)

    def test_decode_header_none(self):
        self.assertIsNone(decode_header(None))


class AptCacheTests(TestCase):
    """
    Tests for :class:`distro_tracker.core.utils.packages.AptCache`.
    """
    @staticmethod
    def stub_acquire(source_records, dest_dir, debian_dir_only, content):
        # Create a file in the destination directory
        file_name = 'temp'
        file_path = os.path.join(dest_dir, file_name)
        # Create a file of the given size
        with open(file_path, 'wb') as f:
            f.write(content)
        return None, 'ekrem'

    def create_cache(self):
        """
        Helper method which creates an
        :class:`distro_tracker.core.utils.packages.AptCache` instance which is
        used for testing. Some of its methods are replaced by mocks and stubs to
        avoid HTTP calls.
        """
        self.cache = AptCache()
        self.cache._get_apt_source_records = mock.MagicMock()
        self.cache._get_format = mock.MagicMock(return_value='1.0')
        self.cache._extract_dpkg_source = mock.MagicMock()
        self.cached_files = []
        self.cache._get_all_cached_files = mock.MagicMock(
            return_value=self.cached_files)
        self.cache._match_index_file_to_repository = mock.MagicMock()

    def set_stub_acquire_content(self, content):
        """
        Helper method which sets the content of a file which is created by the
        cache instance when retrieve_source is called.
        """
        self.cache._apt_acquire_package = mock.MagicMock(side_effect=curry(
            AptCacheTests.stub_acquire, content=content))

    def set_stub_cached_files_for_repository(self, repository, files):
        """
        Helper method adds the given list of files to the stub list of cached
        files for a given repository.

        :param repository: The repository to which these files are associated.
        :type repository: :class:`Repository
            <distro_tracker.core.models.Repository>`
        :param files: List of cached file names. The function uses the list to
            build the stub by prefixing the names with expected repository
            identifiers.
        """
        # Build the prefix from the repository's URI and suite
        base_uri = repository.uri.rstrip('/')
        if base_uri.startswith('http://'):
            base_uri = base_uri[7:]
        prefix = base_uri + '/' + repository.suite + '/'
        prefix = prefix.replace('/', '_')
        for file_name in files:
            self.cached_files.append(prefix + file_name)
        self.cache._match_index_file_to_repository.return_value = repository

    def assert_cache_size_equal(self, size):
        self.assertEqual(size, self.cache.cache_size)

    def test_cache_size_increase_after_acquire(self):
        """
        Tests that the cache correctly increases its size after acquiring new
        files.
        """
        with make_temp_directory('-dtracker-cache') as cache_directory:
            with self.settings(
                    DISTRO_TRACKER_CACHE_DIRECTORY=cache_directory,
                    DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
                self.create_cache()
                # Sanity check: old size is 0 as nothing was ever cached in the
                # brand new directory
                self.assert_cache_size_equal(0)
                content = b'a' * 5  # 5 bytes
                self.set_stub_acquire_content(content)

                self.cache.retrieve_source('dummy-package', '1.0.0')

                self.assert_cache_size_equal(5)

    def test_cache_multiple_insert_no_remove(self):
        """
        Tests that the cache does not remove packages unless the size limit is
        exceeded.
        """
        with make_temp_directory('-dtracker-cache') as cache_directory:
            with self.settings(
                    DISTRO_TRACKER_CACHE_DIRECTORY=cache_directory,
                    DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
                self.create_cache()
                # Sanity check: old size is 0 as nothing was ever cached in the
                # brand new directory
                self.assert_cache_size_equal(0)
                content = b'a' * 5  # 5 bytes
                self.set_stub_acquire_content(content)
                # Add one file.
                self.cache.retrieve_source('dummy-package', '1.0.0')
                self.assert_cache_size_equal(5)
                # Same content in another file
                self.set_stub_acquire_content(content)

                self.cache.retrieve_source('package', '1.0.0')

                # Both files are now saved.
                self.assert_cache_size_equal(10)

    def test_clear_cache(self):
        """
        Tests that the cache removes packages when it exceeds its allocated
        size.
        """
        with make_temp_directory('-dtracker-cache') as cache_directory:
            with self.settings(
                    DISTRO_TRACKER_CACHE_DIRECTORY=cache_directory,
                    DISTRO_TRACKER_APT_CACHE_MAX_SIZE=10):
                self.create_cache()
                # Sanity check: old size is 0 as nothing was ever cached in the
                # brand new directory
                self.assert_cache_size_equal(0)
                initial_content = b'a' * 11
                self.set_stub_acquire_content(initial_content)
                # Set initial source content
                self.cache.retrieve_source('dummy-package', '1.0.0')
                self.assert_cache_size_equal(11)
                content = b'a' * 7
                self.set_stub_acquire_content(content)

                self.cache.retrieve_source('package', '1.0.0')

                # Only the second content is found in the package
                self.assert_cache_size_equal(7)

    def test_get_sources_for_repository(self):
        """
        Tests that the cache correctly returns a list of cached Sources files
        for a given repository.
        """
        with make_temp_directory('-dtracker-cache') as cache_directory:
            with self.settings(DISTRO_TRACKER_CACHE_DIRECTORY=cache_directory):
                self.create_cache()
                repository = Repository.objects.create(
                    name='stable',
                    shorthand='stable',
                    uri='http://httpredir.debian.org/debian/dists',
                    suite='stable')
                expected_source_files = [
                    'main_source_Sources',
                    'contrib_source_Sources',
                ]
                files = expected_source_files + [
                    'Release',
                    'main_binary-amd64_Packages',
                ]
                self.set_stub_cached_files_for_repository(repository, files)

                sources = \
                    self.cache.get_sources_files_for_repository(repository)

                self.assertEqual(len(expected_source_files), len(sources))
                for expected_source, returned_source in zip(
                        expected_source_files, sources):
                    self.assertTrue(returned_source.endswith(expected_source))

    def test_get_packages_for_repository(self):
        """
        Tests that the cache correctly returns a list of cached Packages files
        for a given repository.
        """
        with make_temp_directory('-dtracker-cache') as cache_directory:
            with self.settings(DISTRO_TRACKER_CACHE_DIRECTORY=cache_directory):
                self.create_cache()
                repository = Repository.objects.create(
                    name='stable',
                    shorthand='stable',
                    uri='http://httpredir.debian.org/debian/dists',
                    suite='stable')
                expected_packages_files = [
                    'main_binary-amd64_Packages',
                    'main_binary-i386_Packages',
                ]
                files = expected_packages_files + [
                    'Release',
                    'main_source_Sources',
                ]
                self.set_stub_cached_files_for_repository(repository, files)

                packages = \
                    self.cache.get_packages_files_for_repository(repository)

                self.assertEqual(len(expected_packages_files), len(packages))
                for expected, returned in zip(
                        expected_packages_files, packages):
                    self.assertTrue(returned.endswith(expected))


class LinkifyTests(TestCase):
    """
    Tests for :func:`distro_tracker.core.utils.linkify`.
    """
    sample_url = "http://www.example.com/foo/"
    https_url = "https://www.example.com.foo/"

    @staticmethod
    def link(url):
        return '<a href="{url}">{url}</a>'.format(url=url)

    @staticmethod
    def debian_bug(bug, baseurl='https://bugs.debian.org/'):
        bugno = bug[1:] if bug[0] == '#' else bug
        return '<a href="{}{}">{}</a>'.format(baseurl, bugno, bug)

    @classmethod
    def lp_bug(cls, bug):
        return cls.debian_bug(bug, 'https://bugs.launchpad.net/bugs/')

    @staticmethod
    def cve_link(cve,
                 baseurl='https://cve.mitre.org/cgi-bin/cvename.cgi?name='):
        return '<a href="{}{}">{}</a>'.format(baseurl, cve, cve)

    def setUp(self):
        self.data = {
            'LinkifyHttpLinks': {
                'simple': (self.sample_url, self.link(self.sample_url)),
                'https': (self.https_url, self.link(self.https_url)),
                # Default case, link in text
                'intext': ('see ' + self.sample_url + ' for example',
                           'see ' + self.link(self.sample_url) +
                           ' for example'),
                # Existing HTML links are not re-processed
                'htmllink': (self.link(self.sample_url),
                             self.link(self.sample_url)),
                # Ensure xhttp:// is not recognized as a link
                'badlink': ('x' + self.sample_url, 'x' + self.sample_url)
            },
            'LinkifyDebianBugLinks': {
                'simple': ('closes: ' + '1234', 'closes: ' +
                           self.debian_bug(bug='1234')),
                'withsharp': ('Closes: ' + '#1234', 'Closes: ' +
                              self.debian_bug(bug='#1234')),
                'intext': ('see closes: ' + '#1234' +
                           'for informations',
                           'see closes: ' + self.debian_bug(bug='#1234') +
                           'for informations'),
                'multipleintext': ('see Closes: ' + '1234, 5678,\n9123' +
                                   'or closes: ' + '456' + 'for example',
                                   'see Closes: ' +
                                   self.debian_bug(bug='1234') + ', ' +
                                   self.debian_bug(bug='5678') + ',\n' +
                                   self.debian_bug(bug='9123') + 'or ' +
                                   'closes: ' +
                                   self.debian_bug(bug='456') + 'for example'),
                # Case of a Closes field on its single line (space-separated)
                'closesfield': ('\nCloses: 123 456\n',
                                '\nCloses: ' + self.debian_bug('123') + ' ' +
                                self.debian_bug('456') + '\n'),
                'txtbeforefield': ('\nFinally Closes: 123 456\n',
                                   '\nFinally Closes: ' +
                                   self.debian_bug('123') + ' 456\n'),
                'txtafterfield': ('\nCloses: 123 456 foobar\n',
                                  '\nCloses: ' + self.debian_bug('123') +
                                  ' 456 foobar\n'),
            },
            'LinkifyUbuntuBugLinks': {
                'simple': ('lp: ' + '1234', 'lp: ' +
                           self.lp_bug(bug='1234')),
                'withsharp': ('Lp: ' + '#1234', 'Lp: ' +
                              self.lp_bug(bug='#1234')),
                'intext': ('see lp: ' + '#1234' +
                           'for informations',
                           'see lp: ' + self.lp_bug('#1234') +
                           'for informations'),
                'multipleintext': ('see lp: ' + '1234, 5678,\n9123' +
                                   'or lp: ' + '456' + 'for example',
                                   'see lp: ' +
                                   self.lp_bug(bug='1234') + ', ' +
                                   self.lp_bug(bug='5678') + ',\n' +
                                   self.lp_bug(bug='9123') + 'or lp: ' +
                                   self.lp_bug(bug='456') + 'for example')
            },
            'LinkifyCVELinks': {
                'oldformat': ('CVE-2012-1234',
                              self.cve_link('CVE-2012-1234')),
                'newformat': ('CVE-2014-1234567',
                              self.cve_link('CVE-2014-1234567')),
                'intext': ('see ' + 'cve-2014-67890' + ' for informations',
                           'see ' + self.cve_link('cve-2014-67890') +
                           ' for informations'),
                'notinurl': ('foo.debian.org/CVE-2014-1234',
                             'foo.debian.org/CVE-2014-1234'),
            },
        }

    def _test_linkify_class(self, cls):
        linkifier = cls()
        for name, data in self.data[cls.__name__].items():
            output = linkifier.linkify(data[0])
            self.assertEqual(output, data[1],
                             '{} failed with "{}" test data'.format(
                                 cls.__name__, name))

    def test_linkify_http(self):
        """Test the linkifyHttpLinks class"""
        self._test_linkify_class(LinkifyHttpLinks)

    def test_linkify_debian_bug(self):
        """Test the linkifyDebianbug class"""
        self._test_linkify_class(LinkifyDebianBugLinks)

    def test_linkify_ubuntu_bug(self):
        """Test the linkifyUbuntubug class"""
        self._test_linkify_class(LinkifyUbuntuBugLinks)

    def test_linkify_CVE_links(self):
        """Test the LinkifyCVELinks class"""
        self._test_linkify_class(LinkifyCVELinks)

    @override_settings(
        DISTRO_TRACKER_CVE_URL='https://security-tracker.debian.org/tracker/')
    def test_linkify_CVE_links_custom_url(self):
        """Test LinkifyCVELinks with a custom DISTRO_TRACKER_CVE_URL"""
        url = 'https://security-tracker.debian.org/tracker/'
        # Replace the URL in the expected data
        for key, content in self.data['LinkifyCVELinks'].items():
            self.data['LinkifyCVELinks'][key] = (
                content[0],
                content[1].replace(
                    "https://cve.mitre.org/cgi-bin/cvename.cgi?name=", url)
            )
        self._test_linkify_class(LinkifyCVELinks)

    def test_linkify(self):
        """Test the linkify function as a combination of all the individual
        tests."""
        text = ''
        expected = ''
        for linkifier_test_data in self.data.values():
            for before, after in linkifier_test_data.values():
                text += before + '\n'
                expected += after + '\n'
        linkify_output = linkify(text)
        self.assertEqual(linkify_output, expected)


class UtilsTests(TestCase):
    def test_now(self):
        """Ensure distro_tracker.core.utils.now() exists"""
        self.assertIsInstance(now(), datetime.datetime)
