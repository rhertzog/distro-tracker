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

from pts.core.models import Package, EmailUser, Subscription
from pts.core.models import Keyword

from pts.control.tests.common import EmailControlTest


class KeywordCommandTest(EmailControlTest):
    def setUp(self):
        EmailControlTest.setUp(self)

        # Setup a subscription
        self.package = Package.objects.create(name='dummy-package')
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_user=self.user
        )
        self.subscription.keywords.create(name='bts')
        Keyword.objects.create(name='cvs')
        Keyword.objects.create(name='contact')

        self.commands = []
        self.set_header('From', self.user.email)

    def _to_command_string(self, command):
        """
        Helper method turning a tuple representing a keyword command into a
        string.
        """
        return ' '.join(
            command[:-1] + (', '.join(command[-1]),)
        )

    def add_keyword_command(self, package, operator, keywords, email=None,
                            use_tag=False):
        if email is None:
            email = ''

        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            package,
            email,
            operator,
            keywords,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def _get_previous_keywords(self):
        """
        Helper method returns all keywords the user's current subscription is
        associated with.
        """
        return tuple(
            str(keyword)
            for keyword in self.subscription.keywords.all()
        )

    def assert_correct_response(self, new_keywords, user=None):
        if not user:
            user = self.user
        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assertEqual(self.subscription.keywords.count(), len(new_keywords))
        self.assert_in_response(
            "Here's the new list of accepted keywords associated to package\n"
            "{package} for {address} :".format(package=self.package.name,
                                               address=user.email))
        self.assert_in_response('\n'.join(sorted(
            '* ' + keyword for keyword in new_keywords
        )))

    def test_add_keyword_to_subscription(self):
        """
        Tests the keyword command version which should add a keyword to the
        subscription.
        """
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['cvs', 'contact'],
                                 self.user.email)

        self.control_process()

        self.assert_correct_response(['cvs', 'contact', 'bts'])

    def test_remove_keyword_from_subscription(self):
        """
        Tests the keyword command version which should remove a keyword from a
        subscription.
        """
        self.add_keyword_command(self.package.name,
                                 '-',
                                 ['bts'],
                                 self.user.email)

        self.control_process()

        self.assert_correct_response([])

    def test_set_keywords_for_subscription(self):
        """
        Tests the keyword command version which should set a new keyword list
        for a subscription.
        """
        self.add_keyword_command(self.package.name,
                                 '=',
                                 ['cvs'],
                                 self.user.email)

        self.control_process()

        self.assert_correct_response(['cvs'])

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        self.add_keyword_command(self.package.name, '+', ['cvs'])

        self.control_process()

        self.assert_correct_response(['cvs', 'bts'])

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when the given keyword does not exist.
        """
        self.add_keyword_command(self.package.name, '=', ['no-exist'])

        self.control_process()

        self.assert_correct_response([])
        self.assert_in_response(
            'Warning: no-exist is not a valid keyword')

    def test_keyword_add_subscription_not_confirmed(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription (it is pending).
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, '+', ['cvs'])

        self.control_process()

        self.assert_correct_response(['cvs', 'bts'])

    def test_keyword_add_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('package-no-exist', '+', ['cvs'])

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response('Package package-no-exist does not exist')
        self.assert_not_in_response("Here's the new list of accepted keywords")

    def test_keyword_user_not_subscribed(self):
        """
        Tests the keyword command when the user is not subscribed to the given
        package.
        """
        other_user = EmailUser.objects.create(email='other-user@domain.com')
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['cvs'],
                                 other_user.email)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response(
            'The user is not subscribed to the package {pkg}'.format(
                pkg=self.package.name))
        self.assert_not_in_response("Here's the new list of accepted keywords")

    def test_keyword_user_doesnt_exist(self):
        """
        Tests the keyword command when the user is not subscribed to any
        package.
        """
        email = 'other-user@domain.com'
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['cvs'],
                                 email)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response('User is not subscribed to any package')
        self.assert_not_in_response("Here's the new list of accepted keywords")

    def test_keyword_alias_tag(self):
        """
        Tests that tag works as an alias for keyword.
        """
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['cvs', 'contact'],
                                 self.user.email,
                                 use_tag=True)

        self.control_process()

        self.assert_correct_response(['cvs', 'contact', 'bts'])
