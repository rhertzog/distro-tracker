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

from pts.core.models import PackageName, EmailUser, Subscription, Keyword

from pts.control.tests.common import EmailControlTest


class KeywordCommandHelperMixin(object):
    """
    Contains some methods which are used for testing all forms of the keyword
    command.
    """
    def assert_keywords_in_response(self, keywords):
        """
        Checks if the given keywords are found in the response.
        """
        for keyword in keywords:
            self.assert_list_item_in_response(keyword)

    def assert_keywords_not_in_response(self, keywords):
        """
        Checks that the given keywords are not found in the response.
        """
        for keyword in keywords:
            self.assert_list_item_not_in_response(keyword)


class KeywordCommandSubscriptionSpecificTest(EmailControlTest,
                                             KeywordCommandHelperMixin):
    """
    Tests for the keyword command when modifying subscription specific
    keywords.
    """
    def setUp(self):
        super(KeywordCommandSubscriptionSpecificTest, self).setUp()

        # Setup a subscription
        self.package = PackageName.objects.create(name='dummy-package')
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

    def get_new_list_of_keywords_text(self, package, email):
        """
        Returns the status text which should precede a new list of keywords.
        """
        return (
            "Here's the new list of accepted keywords associated to package\n"
            "{package} for {address} :".format(package=package,
                                               address=self.user.email)
        )

    def assert_error_user_not_subscribed_in_response(self, email, package):
        """
        Checks whether an error saying the user is not subscribed to a package
        is in the response.
        """
        self.assert_error_in_response(
            '{email} is not subscribed to the package {package}'.format(
                email=email, package=package)
        )

    def assert_subscription_keywords_equal(self, keywords):
        """
        Asserts that the subscription of the test user to the test package is
        equal to the given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_user=self.user
        )
        all_keywords = self.subscription.keywords.all()
        self.assertEqual(all_keywords.count(), len(keywords))
        for keyword in all_keywords:
            self.assertIn(keyword.name, keywords)

    def assert_subscription_has_keywords(self, keywords):
        """
        Check if the subscription of the test user to the test package has the
        given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_user=self.user
        )
        all_keywords = self.subscription.keywords.all()
        for keyword in keywords:
            self.assertIn(Keyword.objects.get(name=keyword), all_keywords)

    def assert_subscription_not_has_keywords(self, keywords):
        """
        Assert that the subscription of the test user to the test package does
        not have the given keywords.
        """
        self.subscription = Subscription.objects.get(
            package=self.package,
            email_user=self.user
        )
        all_keywords = self.subscription.keywords.all()
        for keyword in keywords:
            self.assertNotIn(Keyword.objects.get(name=keyword), all_keywords)

    def test_add_keyword_to_subscription(self):
        """
        Tests the keyword command version which should add a keyword to the
        subscription.
        """
        keywords = ['vcs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_keywords_in_response(keywords)
        self.assert_subscription_has_keywords(keywords)

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

        self.assert_keywords_not_in_response(keywords)
        self.assert_subscription_not_has_keywords(keywords)

    def test_set_keywords_for_subscription(self):
        """
        Tests the keyword command version which should set a new keyword list
        for a subscription.
        """
        keywords = ['vcs', 'bts']
        self.add_keyword_command(self.package.name,
                                 '=',
                                 keywords,
                                 self.user.email)

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_subscription_keywords_equal(keywords)

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given.
        """
        self.add_keyword_command(self.package.name, '+', ['vcs'])

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(['vcs'])
        self.assert_subscription_has_keywords(['vcs'])

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when the given keyword does not exist.
        """
        self.add_keyword_command(self.package.name, '+', ['no-exist'])

        self.control_process()

        self.assert_warning_in_response('no-exist is not a valid keyword')
        # Subscription has not changed.
        self.assert_keywords_in_response(self.default_keywords)
        self.assert_subscription_keywords_equal(self.default_keywords)

    def test_keyword_add_subscription_not_confirmed(self):
        """
        Tests the keyword command when the user has not yet confirmed the
        subscription (it is pending).
        """
        self.subscription.active = False
        self.subscription.save()
        self.add_keyword_command(self.package.name, '+', ['vcs'])

        self.control_process()

        self.assert_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))
        self.assert_keywords_in_response(['vcs'])
        self.assert_subscription_has_keywords(['vcs'])

    def test_keyword_add_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('package-no-exist', '+', ['vcs'])

        self.control_process()

        self.assert_in_response('Package package-no-exist does not exist')
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))

    def test_keyword_user_not_subscribed(self):
        """
        Tests the keyword command when the user is not subscribed to the given
        package.
        """
        other_user = EmailUser.objects.create(email='other-user@domain.com')
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['vcs'],
                                 other_user.email)

        self.control_process()

        self.assert_error_user_not_subscribed_in_response(other_user.email,
                                                          self.package.name)
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, other_user.email))

    def test_keyword_user_doesnt_exist(self):
        """
        Tests the keyword command when the user is not subscribed to any
        package.
        """
        email = 'other-user@domain.com'
        self.add_keyword_command(self.package.name,
                                 '+',
                                 ['vcs'],
                                 email)

        self.control_process()

        self.assert_error_user_not_subscribed_in_response(email,
                                                          self.package.name)
        self.assert_not_in_response(self.get_new_list_of_keywords_text(
            self.package.name, self.user.email))

    def test_keyword_alias_tag(self):
        """
        Tests that tag works as an alias for keyword.
        """
        keywords = ['vcs', 'contact']
        self.add_keyword_command(self.package.name,
                                 '+',
                                 keywords,
                                 self.user.email,
                                 use_tag=True)

        self.control_process()

        self.assert_keywords_in_response(keywords)
        self.assert_subscription_has_keywords(keywords)


class KeywordCommandListSubscriptionSpecific(EmailControlTest,
                                             KeywordCommandHelperMixin):
    """
    Tests the keyword command when used to list keywords associated with a
    subscription.
    """
    def setUp(self):
        super(KeywordCommandListSubscriptionSpecific, self).setUp()

        # Setup a subscription
        self.package = PackageName.objects.create(name='dummy-package')
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

    def get_list_of_keywords(self, package, email):
        return (
            "Here's the list of accepted keywords associated to package\n"
            "{package} for {user}".format(
                package=self.package.name, user=self.user.email)
        )

    def test_keyword_user_default(self):
        """
        Tests the keyword command when the subscription is using the user's
        default keywords.
        """
        self.user.default_keywords.add(
            Keyword.objects.create(name='new-keyword'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_keyword_subscription_specific(self):
        """
        Tests the keyword command when the subscription has specific keywords
        associated with it.
        """
        self.subscription.keywords.add(Keyword.objects.get(name='vcs'))
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_keyword_package_doesnt_exist(self):
        """
        Tests the keyword command when the given package does not exist.
        """
        self.add_keyword_command('no-exist', self.user.email)

        self.control_process()

        self.assert_error_in_response('Package no-exist does not exist')
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

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

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
            '{email} is not subscribed to the package {pkg}'.format(
                email=self.user.email,
                pkg=self.package.name)
        )
        self.assert_not_in_response("Here's the list of accepted keywords")

    def test_keyword_email_not_given(self):
        """
        Tests the keyword command when the email is not given in the command.
        """
        self.add_keyword_command(self.package.name)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())

    def test_tag_same_as_keyword(self):
        """
        Tests that "tag" acts as an alias for "keyword"
        """
        self.add_keyword_command(self.package.name, self.user.email)

        self.control_process()

        self.assert_in_response(
            self.get_list_of_keywords(self.package.name, self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.subscription.keywords.all())


class KeywordCommandModifyDefault(EmailControlTest, KeywordCommandHelperMixin):
    """
    Tests the keyword command version which modifies a user's list of default
    keywords.
    """
    def setUp(self):
        super(KeywordCommandModifyDefault, self).setUp()

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

    def get_new_default_list_output_message(self, email):
        """
        Returns the message which should precede the list of new default
        keywords.
        """
        return (
            "Here's the new default list of accepted "
            "keywords for {email} :".format(email=email)
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

    def assert_keywords_in_user_default_list(self, keywords):
        """
        Asserts that the given keywords are found in the user's list of default
        keywords.
        """
        default_keywords = self.user.default_keywords.all()
        for keyword in keywords:
            self.assertIn(Keyword.objects.get(name=keyword), default_keywords)

    def assert_keywords_not_in_user_default_list(self, keywords):
        """
        Asserts that the given keywords are not found in the user's list of
        default keywords.
        """
        default_keywords = self.user.default_keywords.all()
        for keyword in keywords:
            self.assertNotIn(
                Keyword.objects.get(name=keyword), default_keywords)

    def assert_keywords_user_default_list_equal(self, keywords):
        """
        Asserts that the user's list of default keywords exactly matches the
        given keywords.
        """
        default_keywords = self.user.default_keywords.all()
        self.assertEqual(default_keywords.count(), len(keywords))
        for keyword in default_keywords:
            self.assertIn(keyword.name, keywords)

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

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_in_user_default_list(keywords)

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

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_not_in_response(keywords)
        self.assert_keywords_not_in_user_default_list(keywords)

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

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_user_default_list_equal(keywords)

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

        self.assert_in_response(
            self.get_new_default_list_output_message(self.user.email))
        self.assert_keywords_in_response(keywords)
        self.assert_keywords_in_user_default_list(keywords)

    def test_keyword_doesnt_exist(self):
        """
        Tests the keyword command when a nonexistant keyword is given.
        """
        self.add_keyword_command('+', ['no-exist'])

        self.control_process()

        self.assert_warning_in_response('no-exist is not a valid keyword')
        self.assert_keywords_not_in_response(['no-exist'])

    def test_user_doesnt_exist(self):
        """
        Tests adding a keyword to a user's default list of subscriptions when
        the given user is not subscribed to any packages (it does not exist yet)
        """
        all_default_keywords = [
            keyword.name
            for keyword in Keyword.objects.filter(default=True)
        ]
        new_user = 'doesnt-exist@domain.com'
        keywords = [Keyword.objects.filter(default=False)[0].name]
        self.add_keyword_command('+', keywords, new_user)

        self.control_process()

        # User created
        self.assertEqual(EmailUser.objects.filter(email=new_user).count(), 1)
        self.assert_in_response(
            self.get_new_default_list_output_message(new_user))
        self.assert_keywords_in_response(keywords + all_default_keywords)


class KeywordCommandShowDefault(EmailControlTest, KeywordCommandHelperMixin):
    def setUp(self):
        super(KeywordCommandShowDefault, self).setUp()
        self.user = EmailUser.objects.create(email='user@domain.com')
        self.user.default_keywords.add(
            Keyword.objects.filter(default=False)[0])
        self.set_header('From', self.user.email)

    def get_default_keywords_list_message(self, email):
        """
        Returns the message which should precede the list of all default
        keywords in the output of the command.
        """
        return (
            "Here's the default list of accepted keywords for {email}:".format(
                email=email)
        )

    def test_show_default_keywords(self):
        """
        Tests that the keyword command outputs all default keywords of a user.
        """
        self.set_input_lines(['keyword ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.user.default_keywords.all()
        )

    def test_show_default_keywords_email_not_given(self):
        """
        Tests that the keyword command shows all default keywords of a user
        when the email is not given in the command.
        """
        self.set_input_lines(['keyword'])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.user.default_keywords.all()
        )

    def test_show_default_keywords_email_no_subscriptions(self):
        """
        Tests that the keyword command returns a list of default keywords for
        users that are not subscribed to any packages.
        """
        email = 'no-exist@domain.com'
        self.set_input_lines(['keyword ' + email])

        self.control_process()

        # User created first...
        self.assertEqual(EmailUser.objects.filter(email=email).count(), 1)
        user = EmailUser.objects.get(email=email)
        self.assert_in_response(
            self.get_default_keywords_list_message(user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in user.default_keywords.all()
        )

    def test_tag_alias_for_keyword(self):
        """
        Tests that "tag" is an alias for "keyword"
        """
        self.set_input_lines(['tag ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.user.default_keywords.all()
        )

    def test_tags_alias_for_keyword(self):
        """
        Tests that 'tags' is an alias for 'keyword'
        """
        self.set_input_lines(['tags ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.user.default_keywords.all()
        )

    def test_keywords_alias_for_keyword(self):
        """
        Tests that 'keywords' is an alias for 'keyword'
        """
        self.set_input_lines(['keywords ' + self.user.email])

        self.control_process()

        self.assert_in_response(
            self.get_default_keywords_list_message(self.user.email))
        self.assert_keywords_in_response(
            keyword.name for keyword in self.user.default_keywords.all()
        )
