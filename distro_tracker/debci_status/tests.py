# -*- coding: utf-8 -*-

# Copyright 2013-2019 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for Debci-specific modules/functionality of Distro Tracker.
"""

from unittest import mock

from django.test.utils import modify_settings, override_settings

from distro_tracker.core.models import ActionItem, PackageName
from distro_tracker.core.utils.packages import package_url
from distro_tracker.debci_status.tracker_package_tables import DebciTableField
from distro_tracker.debci_status.tracker_tasks import UpdateDebciStatusTask
from distro_tracker.test import TemplateTestsMixin, TestCase
from distro_tracker.test.utils import set_mock_response


@override_settings(DISTRO_TRACKER_DEBCI_URL='https://ci.debian.net')
@mock.patch('distro_tracker.core.utils.http.requests')
class UpdateDebciStatusTaskTest(TestCase):
    """
    Tests for the
    :class:`distro_tracker.debci_status.tracker_tasks.UpdateDebciStatusTask`
    task.
    """
    def setUp(self):
        self.source_package = self.create_source_package(name='dummy-package',
                                                         repository='unstable')
        self.package = self.source_package.source_package_name
        self.json_data = [
            {
                "run_id": "20140705_145427",
                "package": "dummy-package",
                "version": "1.0-1",
                "date": "2014-07-05 14:55:57",
                "status": "fail",
                "blame": [],
                "previous_status": "pass",
                "duration_seconds": "91",
                "duration_human": "0h 1m 31s",
                "message": "Tests failed"
            }
        ]

    def run_task(self):
        """
        Runs the debci status update task.
        """
        task = UpdateDebciStatusTask()
        task.execute()

    def test_no_action_item_for_passing_test(self, mock_requests):
        """
        Tests that an ActionItem isn't created for a passing debci status.
        """
        self.json_data[0]['status'] = 'pass'
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        self.assertEqual(0, self.package.action_items.count())

    def test_no_action_item_for_neutral_test(self, mock_requests):
        """
        Tests that an ActionItem isn't created for a passing debci status.
        """
        self.json_data[0]['status'] = 'neutral'
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        self.assertEqual(0, self.package.action_items.count())

    def test_no_action_item_for_unknown_package(self, mock_requests):
        """
        Tests that an ActionItem isn't created for an unknown package.
        """
        self.json_data[0]['package'] = 'unknown-package'
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        self.assertEqual(0, ActionItem.objects.count())

    def test_action_item_for_failing_test(self, mock_requests):
        """
        Tests that a proper ActionItem is created for a failing test
        on a known package.
        """
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        # Check that the ActionItem contains the correct contents.
        self.assertEqual(self.package.action_items.count(), 1)
        action_item = self.package.action_items.all()[0]
        url = "https://ci.debian.net/packages/d/dummy-package"
        log = "https://ci.debian.net/data/packages/unstable/amd64/d/" + \
            "dummy-package/latest-autopkgtest/log.gz"
        self.assertIn(url, action_item.short_description)
        self.assertEqual(action_item.extra_data[0]['duration'], "0h 1m 31s")
        self.assertEqual(action_item.extra_data[0]['previous_status'], "pass")
        self.assertEqual(action_item.extra_data[0]['date'],
                         "2014-07-05 14:55:57")
        self.assertEqual(action_item.extra_data[0]['url'], url)
        self.assertEqual(action_item.extra_data[0]['log'], log)

    def test_action_item_is_dropped_when_test_passes_again(self, mock_requests):
        """
        Tests that ActionItems are dropped when the test passes again.
        """
        set_mock_response(mock_requests, json=self.json_data)
        self.run_task()
        self.json_data[0]['status'] = 'pass'
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        self.assertEqual(self.package.action_items.count(), 0)

    def test_action_item_is_dropped_when_info_vanishes(self, mock_requests):
        """
        Tests that ActionItems are dropped when the debci report doesn't
        mention the package.
        """
        set_mock_response(mock_requests, json=self.json_data)
        self.run_task()
        set_mock_response(mock_requests, json=[])

        self.run_task()

        self.assertEqual(ActionItem.objects.count(), 0)

    def test_lib_package_link(self, mock_requests):
        """
        Tests that links to lib packages' log files are correct.
        """
        source_package = self.create_source_package(name='libpackage')
        package = source_package.source_package_name
        self.json_data[0]['package'] = 'libpackage'
        set_mock_response(mock_requests, json=self.json_data)

        self.run_task()

        ai = package.action_items.all()
        self.assertEqual(1, len(ai))
        action_item = ai[0]
        action_item_log_url = action_item.extra_data[0]['log']
        log_url = "https://ci.debian.net/data/packages/unstable/amd64/libp/" + \
            "libpackage/latest-autopkgtest/log.gz"

        self.assertEqual(action_item_log_url, log_url)

    def test_no_exception_on_unavailable_repository(self, mock_requests):
        """
        Tests that no exception is raised when getting a 404 from debci
        (for instance with a hidden repository), and that no ActionItem
        is created
        """
        set_mock_response(mock_requests, json=self.json_data,
                          status_code=404)

        self.run_task()

        self.assertEqual(0, self.package.action_items.count())

    @override_settings(DISTRO_TRACKER_DEBCI_REPOSITORIES=['debcirepo'])
    def test_debci_repository_variable_enforced(self, mock_requests):
        """
        Tests that DISTRO_TRACKER_DEBCI_REPOSITORIES, when defined,
        takes precedence over default "all repositories" behavior.
        """
        # make sure 'debcirepo' repo exists
        self.add_to_repository(self.source_package, 'debcirepo')

        with mock.patch.object(UpdateDebciStatusTask,
                               'get_debci_status') as get_debci_status:
            get_debci_status.return_value = self.json_data
            self.run_task()
            get_debci_status.assert_called_once_with('debcirepo')


@modify_settings(INSTALLED_APPS={'append': 'distro_tracker.debci_status'})
class DebciLinkTest(TestCase, TemplateTestsMixin):

    """
    Tests that the debci link is added to source package pages.
    """

    def setUp(self):
        self.srcpkg = self.create_source_package(name='dummy',
                                                 repository='unstable')
        self.url = 'https://ci.debian.net/packages/d/dummy'
        self.debci_data = [{
            'result': {'status': 'fail'},
            'repository': 'unstable',
            'url': self.url
        }]

    def get_package_page_response(self, package_name):
        return self.client.get(package_url(package_name))

    def test_package_with_debci_report(self):
        self.add_package_data(self.srcpkg.name, debci=self.debci_data)

        response = self.get_package_page_response(self.srcpkg.name)

        self.assertLinkIsInResponse(response, self.url)

    def test_package_without_debci_report(self):
        response = self.get_package_page_response(self.srcpkg.name)

        self.assertLinkIsNotInResponse(response, self.url)


@modify_settings(INSTALLED_APPS={'append': 'distro_tracker.debci_status'})
@override_settings(
    DISTRO_TRACKER_DEBCI_REPOSITORIES=['unstable', 'stable'],
    DISTRO_TRACKER_DEBCI_URL='https://ci.debian.net')
class DebciTableFieldTest(TestCase):
    """
    Tests that the debci field behaves as expected, with the proper content.
    """

    def setUp(self):
        # Package with a fail result
        self.src1 = self.create_source_package(
            name='dummy', repository='unstable',
            data={'debci': [self.debci_data('fail')]}
        )

        # Package without debci data
        self.src2 = self.create_source_package(
            name='package', repository='unstable')

        # Package with 2 different results in two repositories
        self.src3 = self.create_source_package(
            name='other', repositories=['unstable', 'stable'],
            data={'debci': [
                self.debci_data('fail', 'unstable'),
                self.debci_data('pass', 'stable'),
            ]}
        )

        self.field = DebciTableField()

        packages = PackageName.objects.filter(name=self.src1.name)
        for prefetch in self.field.prefetch_related_lookups:
            packages = packages.prefetch_related(prefetch)
        self.package = packages[0]

        self.package2 = self.src2.source_package_name

        packages = PackageName.objects.filter(name=self.src3.name)
        for prefetch in self.field.prefetch_related_lookups:
            packages = packages.prefetch_related(prefetch)
        self.package3 = packages[0]

    @staticmethod
    def debci_data(result='pass', repository='unstable'):
        return {
            'result': {'status': result},
            'repository': repository,
            'url': 'https://ci.debian.net/packages/p/package',
        }

    def test_field_specific_properties(self):
        """
        Tests field specific properties
        """
        self.assertEqual(self.field.column_name, 'Tests')
        self.assertEqual(self.field.slug, 'debci')
        self.assertEqual(self.field.template_name, 'debci_status/debci.html')
        self.assertEqual(len(self.field.prefetch_related_lookups), 1)

    def test_package_with_debci_report(self):
        """
        Tests field context content when debci data is present
        """
        context = self.field.context(self.package)
        self.assertIn('statuses', context)
        expectedStatus = [{'repository': 'unstable',
                           'status': 'fail'}]
        self.assertEqual(context['statuses'], expectedStatus)

    def test_package_without_debci_report(self):
        """
        Tests field context content when debci data is not present
        """
        context = self.field.context(self.package2)
        self.assertEqual(len(context['statuses']), 0)

    def test_deterministic_order_in_context(self):
        """
        Make sure the order in the context's statuses array is "stable,unstable"
        """
        context = self.field.context(self.package3)
        expectedStatus = [{'repository': 'stable',
                          'status': 'pass'},
                          {'repository': 'unstable',
                          'status': 'fail'}]
        self.assertEqual(context['statuses'], expectedStatus)

    def test_label_warning_for_mixed_results(self):
        """
        Make sure the label is correct when some tests pass while others fail
        """
        context = self.field.context(self.package3)
        self.assertEqual(context['label_type'], 'warning')