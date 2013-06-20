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

from pts.core.models import Package, EmailUser, Subscription, Keyword

from pts.control.tests.common import EmailControlTest
from operator import attrgetter


class KeywordCommandSubscriptionSpecificTest(EmailControlTest):
    """
    Tests for the keyword command when modifying subscription specific
    keywords.
    """
    def setUp(self):
        EmailControlTest.setUp(self)

        # Setup a subscription
        self.package = Package.objects.create(name='dummy-package')
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_user=self.user
        )
        self.default_keywords = set(
            keyword.name
            for keyword in self.subscription.keywords.filter(default=True))

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

    def assert_correct_response(self, new_keywords, user=None):
        if not user:
            user = self.user
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_user=self.user
        )
        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assertEqual(self.subscription.keywords.count(), len(new_keywords))
        self.assert_in_response(
            "Here's the new list of accepted keywords associated to package\n"
            "{package} for {address} :".format(package=self.package.name,
                                               address=user.email))
        self.assert_list_in_response(sorted(new_keywords))

    def test_add_keyword_to_subscription(self):
        """
        Tests the keyword command version which should add a keyword to the
        subscription.
        """
        keywords = ['cvs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(keywords))

    def test_remove_keyword_from_subscription(self):
        """
        Tests the keyword command version which should remove a keyword from a
        subscription.
        """
        keywords = ['bts']
        self.add_keyword_command(self.package.name,
                                 '-',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_correct_response(self.default_keywords - set(keywords))

    def test_set_keywords_for_subscription(self):
        """
        Tests the keyword command version which should set a new keyword list
        for a subscription.
        """
        keywords = ['cvs']
        self.add_keyword_command(self.package.name,
                                 '=',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_correct_response(keywords)

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        self.add_keyword_command(self.package.name, '+', ['cvs'])

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(['cvs']))

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when the given keyword does not exist.
        """
        self.add_keyword_command(self.package.name, '=', ['no-exist'])

        self.control_process()

        self.assert_correct_response([])
        self.assert_warning_in_response('no-exist is not a valid keyword')

    def test_keyword_add_subscription_not_confirmed(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription (it is pending).
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, '+', ['cvs'])

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(['cvs']))

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

        self.assert_error_in_response(
            '{email} is not subscribed to the package {pkg}'.format(
                email='other-user@domain.com',
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

        self.assert_error_in_response(
            'other-user@domain.com is not subscribed to any package')
        self.assert_not_in_response("Here's the new list of accepted keywords")

    def test_keyword_alias_tag(self):
        """
        Tests that tag works as an alias for keyword.
        """
        keywords = ['cvs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email,
                                 use_tag=True)

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(keywords))


class KeywordCommandListSubscriptionSpecific(EmailControlTest):
    """
    Tests the keyword command when used to list keywords associated with a
    subscription.
    """
    def setUp(self):
        EmailControlTest.setUp(self)

        # Setup a subscription
        self.package = Package.objects.create(name='dummy-package')
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.subscription = Subscription.objects.create(
            package=self.package,
            email_user=self.user
        )

        self.commands = []
        self.set_header('From', self.user.email)

    def _to_command_string(self, command):
        return ' '.join(command)

    def add_keyword_command(self, package, email='', use_tag=False):
        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            package,
            email,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def assert_correct_response(self):
        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_user=self.user
        )
        self.assert_in_response(
            "Here's the list of accepted keywords associated to package")
        self.assert_in_response("{package} for {user}".format(
            package=self.package.name, user=self.user.email))
        self.assert_list_in_response(
            sorted(self.subscription.keywords.all(), key=attrgetter('name')))

    def test_keyword_user_default(self):
        """
        Tests the keyword command when the subscription is using the user's
        default keywords.
        """
        self.user.default_keywords.add(
            Keyword.objects.create(name='new-keyword'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_correct_response()

    def test_keyword_subscription_specific(self):
        """
        Tests the keyword command when the subscription has specific keywords
        associated with it.
        """
        self.subscription.keywords.add(Keyword.objects.get(name='cvs'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_correct_response()

    def test_keyword_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('no-exist', self.user.email)

        self.control_process()

        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response('Package no-exist does not exist')
        self.assert_not_in_response("Here's the list of accepted keywords")

    def test_keyword_subscription_not_active(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription to the given package.
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_correct_response()

    def test_keyword_user_not_subscribed(self):
        """
        Tests the keyword command when the given user is not subscribed to the
        given package.
        """
        self.subscription.delete()
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_response_sent()
        self.assert_error_in_response(
            '{email} is not subscribed to the package'.format(
                email=self.user.email))
        self.assert_not_in_response("Here's the list of accepted keywords")

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given in the command.
        """
        self.add_keyword_command(self.package.name)

        self.control_process()

        self.assert_correct_response()

    def test_tag_same_as_keyword(self):
        """
        Tests that "tag" acts as an alias for "keyword"
        """
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_correct_response()


class KeywordCommandModifyDefault(EmailControlTest):
    """
    Tests the keyword command version which modifies a user's list of default
    keywords.
    """
    def setUp(self):
        EmailControlTest.setUp(self)

        # Setup a subscription
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.default_keywords = set([
            keyword.name
            for keyword in self.user.default_keywords.all()
        ])
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

    def add_keyword_command(self, operator, keywords, email='', use_tag=False):
        command = 'keyword' if not use_tag else 'tag'
        self.commands.append((
            command,
            email,
            operator,
            keywords,
        ))
        self.set_input_lines(self._to_command_string(command)
                             for command in self.commands)

    def assert_correct_response(self, new_keywords, user=None):
        if not user:
            user = self.user
        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assertEqual(user.default_keywords.count(), len(new_keywords))
        self.assert_in_response(
            "Here's the new default list of accepted "
            "keywords for {email} :".format(email=user.email))
        self.assert_list_in_response(sorted(new_keywords))

    def test_keyword_add_default(self):
        """
        Tests that the keyword command adds a new keyword to the user's list of
        default keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:3]
        ]
        self.add_keyword_command('+', keywords, self.user.email)

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(keywords))

    def test_keyword_remove_default(self):
        """
        Tests that the keyword command removes keywords from the user's list of
        default keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=True)[:3]
        ]
        self.add_keyword_command('-', keywords, self.user.email)

        self.control_process()

        self.assert_correct_response(self.default_keywords - set(keywords))

    def test_keyword_set_default(self):
        """
        Tests that the keyword command sets a new list of the user's default
        keywords.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:5]
        ]
        keywords.extend(
            keyword.name
            for keyword in Keyword.objects.filter(default=True)[:2]
        )
        self.add_keyword_command(' = ', keywords, self.user.email)

        self.control_process()

        self.assert_correct_response(set(keywords))

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=False)[:3]
        ]
        self.add_keyword_command('   +', keywords)

        self.control_process()

        self.assert_correct_response(self.default_keywords | set(keywords))

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when a nonexistant keyword is given.
        """
        self.add_keyword_command('+', ['no-exist'])

        self.control_process()

        self.assert_correct_response(self.default_keywords)
        self.assert_in_response('Warning: no-exist is not a valid keyword')

    def test_user_doesnt_exist(self):
        """
        Tests adding a keyword to a user's default list of subscriptions when
        the given user is not subscribed to any package (it does not exist yet)
        """
        all_default_keywords = set([
            keyword.name
            for keyword in Keyword.objects.filter(default=True)
        ])
        new_user = 'doesnt-exist@domain.com'
        keywords = [Keyword.objects.filter(default=False)[0].name]
        self.add_keyword_command('+', keywords, new_user)

        self.control_process()

        self.assertEqual(EmailUser.objects.filter(email=new_user).count(), 1)
        self.assert_correct_response(all_default_keywords | set(keywords),
                                     EmailUser.objects.get(email=new_user))


class KeywordCommandShowDefault(EmailControlTest):
    def setUp(self):
        EmailControlTest.setUp(self)
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.user.default_keywords.add(
            Keyword.objects.filter(default=False)[0])
        self.set_header('From', self.user.email)

    def assert_correct_response(self, user=None):
        if not user:
            user = self.user
        self.assert_response_sent()
        self.assert_correct_response_headers()
        self.assert_in_response(
            "Here's the default list of accepted keywords for {email}:".format(
                email=user.email))
        self.assert_list_in_response(
            sorted(user.default_keywords.all(), key=attrgetter('name')))

    def test_show_default_keywords(self):
        """
        Tests that the keyword command outputs all default keywords of a user.
        """
        self.set_input_lines(['keyword ' + self.user.email])

        self.control_process()

        self.assert_correct_response()

    def test_show_default_keywords_email_not_given(self):
        """
        Tests that the keyword command shows all default keywords of a user
        when the email is not given in the command.
        """
        self.set_input_lines(['keyword'])

        self.control_process()

        self.assert_correct_response()

    def test_show_default_keywords_email_no_subscriptions(self):
        """
        Tests that the keyword command returns a list of default keywords for
        users that are not subscribed to any package.
        """
        email = 'no-exist@domain.com'
        all_default_keywords = Keyword.objects.filter(default=True)
        self.set_input_lines(['keyword ' + email])

        self.control_process()

        self.assertEqual(EmailUser.objects.filter(email=email).count(), 1)
        user = EmailUser.objects.get(email=email)
        self.assertEqual(user.default_keywords.count(),
                         all_default_keywords.count())
        self.assertSequenceEqual(
            sorted(user.default_keywords.all(), key=lambda x: x.name),
            sorted(all_default_keywords.all(), key=lambda x: x.name))
        self.assert_correct_response(user=user)

    def test_tag_alias_for_keyword(self):
        """
        Tests that "tag" is an alias for "keyword"
        """
        self.set_input_lines(['tag ' + self.user.email])

        self.control_process()

        self.assert_correct_response()

    def test_tags_alias_for_keyword(self):
        """
        Tests that 'tags' is an alias for 'keyword'
        """
        self.set_input_lines(['tags ' + self.user.email])

        self.control_process()

        self.assert_correct_response()

    def test_keywords_alias_for_keyword(self):
        """
        Tests that 'keywords' is an alias for 'keyword'
        """
        self.set_input_lines(['keywords ' + self.user.email])

        self.control_process()

        self.assert_correct_response()
