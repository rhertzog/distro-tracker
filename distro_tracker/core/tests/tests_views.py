# -*- coding: utf-8 -*-

# Copyright 2013-2018 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.

"""
Tests for the Distro Tracker core views.
"""
import json

from django.conf import settings
from django.urls import reverse

from distro_tracker.accounts.models import UserEmail
from distro_tracker.core.forms import AddTeamMemberForm
from distro_tracker.core.models import (
    ActionItem,
    ActionItemType,
    BinaryPackage,
    BinaryPackageName,
    MembershipConfirmation,
    News,
    PackageName,
    PseudoPackageName,
    SourcePackage,
    SourcePackageName,
    Team
)
from distro_tracker.core.utils.packages import package_url
from distro_tracker.test import TemplateTestsMixin, TestCase, UserAuthMixin


class PackageViewTest(TestCase):
    """
    Tests for the package view.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.binary_package = BinaryPackageName.objects.create(
            name='binary-package')
        self.pseudo_package = \
            PseudoPackageName.objects.create(name='pseudo-pkg')
        self.src_pkg = SourcePackage.objects.create(
            source_package_name=self.package, version='1.0.0')
        self.bin_pkg = BinaryPackage.objects.create(
            binary_package_name=self.binary_package,
            source_package=self.src_pkg,
            short_description='a useful package')
        self.src_pkg.binary_packages.set([self.binary_package])
        self.src_pkg.save()
        self.bin_pkg.save()

    def test_source_package_page(self):
        """
        Tests that when visiting the package page for an existing package, a
        response based on the correct template is returned.
        """
        response = self.client.get(package_url(self.package.name))

        self.assertTemplateUsed(response, 'core/package.html')

    def test_source_package_page_with_plus_it_its_name(self):
        """
        Tests that we can visit the page for a package which contains
        a plus its name (non-regression test for bug #754497).
        """
        pkg = SourcePackageName.objects.create(name='libti++')

        response = self.client.get(package_url(pkg))

        self.assertTemplateUsed(response, 'core/package.html')

    def test_binary_package_redirects_to_source(self):
        """
        Tests that when visited a binary package URL, the user is redirected
        to the corresponding source package page.
        """
        response = self.client.get(package_url(self.binary_package))

        self.assertRedirects(response, package_url(self.package))

    def test_pseudo_package_page(self):
        """
        Tests that when visiting a page for a pseudo package the correct
        template is used.
        """
        response = self.client.get(package_url(self.pseudo_package))

        self.assertTemplateUsed(response, 'core/package.html')

    def test_non_existent_package(self):
        """
        Tests that a 404 is returned when the given package does not exist.
        """
        response = self.client.get(package_url('no-exist'))
        self.assertEqual(response.status_code, 404)

    def test_subscriptions_only_package(self):
        """
        Tests that a 404 is returned when the given package is a "subscriptions
        only" package.
        """
        package_name = 'sub-only-pkg'
        # Make sure the package actually exists.
        PackageName.objects.create(name=package_name)

        response = self.client.get(package_url(package_name))
        self.assertEqual(response.status_code, 404)

    def test_old_package_with_news(self):
        """
        Tests that when visiting the package page for an old package with news,
        a response based on the correct template is returned.
        """
        package_name = 'old-pkg-with-news'
        oldpackage = PackageName.objects.create(name=package_name)
        News.objects.create(package=oldpackage, title='sample-title',
                            content='sample-content')

        response = self.client.get(package_url(package_name))

        self.assertTemplateUsed(response, 'core/package.html')

    def test_legacy_url_redirects(self):
        """
        Tests that the old PTS style package URLs are correctly redirected.
        """
        url_template = '/{hash}/{package}.html'

        # Redirects for packages that do not start with "lib"
        url = url_template.format(hash=self.package.name[0],
                                  package=self.package.name)
        response = self.client.get(url)
        self.assertRedirects(response, package_url(self.package),
                             status_code=301)

        # No redirect when the hash does not match the package
        url = url_template.format(hash='q', package=self.package.name)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        # Redirect when the package name starts with "lib"
        lib_package = 'libpackage'
        SourcePackageName.objects.create(name=lib_package)
        url = url_template.format(hash='libp', package=lib_package)
        self.assertRedirects(self.client.get(url),
                             package_url(lib_package),
                             status_code=301)

    def test_catchall_redirect(self):
        """
        Tests that requests made to the root domain are redirected to a package
        page when possible and when it does not conflict with another URL rule.
        """
        url = '/{}'.format(self.package.name)
        response = self.client.get(url, follow=True)
        # User redirected to the existing package page
        self.assertRedirects(response, package_url(self.package))

        # Trailing slash
        url = '/{}/'.format(self.package.name)
        response = self.client.get(url, follow=True)
        # User redirected to the existing package page
        self.assertRedirects(response, package_url(self.package))

        # Admin URLs have precedence to the catch all package redirect
        url = reverse('admin:index')
        response = self.client.get(url, follow=True)
        # No redirects to non-existing /pkg/admin, so no 404 either
        self.assertNotEqual(404, response.status_code)

        # Non existing package
        url = '/{}'.format('no-exist')
        response = self.client.get(url, follow=True)
        self.assertEqual(404, response.status_code)

    def test_short_description(self):
        """
        Tests that the short description is displayed.
        """
        response = self.client.get(package_url(self.package))

        self.assertContains(response, 'a useful package')

    def test_page_does_not_contain_None(self):
        """
        Ensure Python's None never ends up displayed on the web page.
        """
        response = self.client.get(package_url(self.package))
        response_content = response.content.decode('utf-8')

        self.assertNotIn('None', response_content)


class PackageSearchViewTest(TestCase):
    def setUp(self):
        self.pseudo_package = \
            PseudoPackageName.objects.create(name='pseudo-package')
        self.source_package = \
            SourcePackageName.objects.create(name='dummy-package')
        self.binary_package = BinaryPackageName.objects.create(
            name='binary-package')
        src_pkg = SourcePackage.objects.create(
            source_package_name=self.source_package, version='1.0.0')
        src_pkg.binary_packages.set([self.binary_package])
        src_pkg.save()

    def test_package_search_source_package(self):
        """
        Tests the package search when the given package is an existing source
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.source_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_search_pseudo_package(self):
        """
        Tests the package search when the given package is an existing pseudo
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.pseudo_package.name
        })

        self.assertRedirects(response, self.pseudo_package.get_absolute_url())

    def test_package_search_binary_package(self):
        """
        Tests the package search when the given package is an existing binary
        package.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': self.binary_package.name
        })

        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_package_does_not_exist(self):
        """
        Tests the package search when the given package does not exist.
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': 'no-exist'
        })

        self.assertTemplateUsed('core/package_search.html')
        self.assertIn('package_name', response.context)
        self.assertEqual(response.context['package_name'], 'no-exist')

    def test_case_insensitive_package_search(self):
        """
        Tests that package search is case insensitive
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': 'DuMmy-PACKAGE'
        })
        self.assertRedirects(response, self.source_package.get_absolute_url())

    def test_search_package_with_leading_and_trailing_spaces_in_its_name(self):
        """
        Tests that we can visit the page for a package by searching
        the name with leading and trailing spaces
        """
        response = self.client.get(reverse('dtracker-package-search'), {
            'package_name': '    dummy-package    '
        })
        self.assertRedirects(response, self.source_package.get_absolute_url())


class OpenSearchDescriptionTest(TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.OpenSearchDescription`.
    """

    def test_html_head_contains_opensearch_link_entry(self):
        osd_uri = reverse('dtracker-opensearch-description')
        header = '<link type="application/opensearchdescription+xml" title="'
        header += "%s Package Tracker Search" % \
            settings.DISTRO_TRACKER_VENDOR_NAME
        header += '" rel="search" href="' + osd_uri + '"/>'

        response = self.client.get(reverse('dtracker-index'))

        self.assertContains(response, header, html=True)

    def test_opensearch_description_url(self):
        response = self.client.get(reverse('dtracker-opensearch-description'))
        self.assertTemplateUsed(response, 'core/opensearch-description.xml')

    def test_opensearch_description_contains_relevant_urls(self):
        response = self.client.get(reverse('dtracker-opensearch-description'))
        self.assertContains(response, reverse('dtracker-favicon'))
        self.assertContains(response, reverse('dtracker-package-search') +
                            '?package_name={searchTerms}')


class IndexViewTest(TestCase):
    def test_index(self):
        """
        Tests that the correct template is rendered when the index page is
        accessed.
        """
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'core/index.html')


class PackageAutocompleteViewTest(TestCase):
    def setUp(self):
        SourcePackageName.objects.create(name='dummy-package')
        SourcePackageName.objects.create(name='d-package')
        SourcePackageName.objects.create(name='package')
        PseudoPackageName.objects.create(name='pseudo-package')
        PseudoPackageName.objects.create(name='zzz')
        BinaryPackageName.objects.create(name='package-dev')
        BinaryPackageName.objects.create(name='libpackage')
        PackageName.objects.create(name='ppp')

    def test_source_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for source
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'source', 'q': 'd'})

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'd')
        self.assertEqual(len(response[1]), 2)
        self.assertIn('dummy-package', response[1])
        self.assertIn('d-package', response[1])

        # No packages given when there are no matching source packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'source', 'q': 'z'})
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'z')
        self.assertEqual(len(response[1]), 0)

    def test_binary_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for binary
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'binary', 'q': 'p'})

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 2)
        self.assertIn('package-dev', response[1])
        self.assertIn('libpackage', response[1])

        # No packages given when there are no matching binary packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'binary', 'q': 'z'})
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'z')
        self.assertEqual(len(response[1]), 0)

    def test_pseudo_package_autocomplete(self):
        """
        Tests the autocomplete functionality when the client asks for pseudo
        packages.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'pseudo', 'q': 'p'})

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 1)
        self.assertIn('pseudo-package', response[1])

        # No packages given when there are no matching pseudo packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'pseudo', 'q': 'y'})
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'y')
        self.assertEqual(len(response[1]), 0)

    def test_all_packages_autocomplete(self):
        """
        Tests the autocomplete functionality when the client does not specify
        the type of package. The result should only contain source and pseudo
        packages, no binary package.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'q': 'p'})

        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], 'p')
        self.assertEqual(len(response[1]), 4)
        self.assertIn('package', response[1])
        self.assertIn('pseudo-package', response[1])
        self.assertIn('d-package', response[1])
        self.assertIn('dummy-package', response[1])

        # No packages given when there are no matching packages
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'q': '-dev'})
        response = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0], '-dev')
        self.assertEqual(len(response[1]), 0)

    def test_no_query_given(self):
        """
        Tests the autocomplete when there is no query parameter given.
        """
        response = self.client.get(reverse('dtracker-api-package-autocomplete'),
                                   {'package_type': 'source'})

        self.assertEqual(response.status_code, 404)


class ActionItemJsonViewTest(TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.ActionItemJsonView`.
    """
    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.action_type = ActionItemType.objects.create(
            type_name='test',
            full_description_template='action-item-test.html')
        self.add_test_template_dir()

    def test_item_exists(self):
        """
        Tests that the JSON response correctly returns an item's content.
        """
        expected_short_description = 'Short description of item'
        action_item = ActionItem.objects.create(
            package=self.package,
            item_type=self.action_type,
            short_description=expected_short_description)
        response = self.client.get(reverse('dtracker-api-action-item', kwargs={
            'item_pk': action_item.pk,
        }))

        response = json.loads(response.content.decode('utf-8'))
        # Correct short description
        self.assertEqual(
            expected_short_description,
            response['short_description'])
        # Package name included
        self.assertEqual(
            'dummy-package',
            response['package']['name'])
        # Full description from rendered template
        self.assertIn("Item's PK is", response['full_description'])
        # Template name NOT included
        self.assertNotIn('full_description_template', response)

    def test_item_does_not_exist(self):
        """
        Tests that the JSON ActionItem view returns 404 when the item does not
        exist.
        """
        does_not_exist = 100
        # Sanity check - the PK actually does not exist
        self.assertEqual(0,
                         ActionItem.objects.filter(pk=does_not_exist).count())
        response = self.client.get(reverse('dtracker-api-action-item', kwargs={
            'item_pk': does_not_exist,
        }))

        self.assertEqual(response.status_code, 404)


class CreateTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.CreateTeamView`.
    """
    def setUp(self):
        self.setup_users(login=True)
        self.create_POST_data = {
            'maintainer_email': 'john@debian.org',
            'name': 'QA',
            'slug': 'qa',
            'public': 'true',
            'description': 'imaginary team',
        }

    def create_team(self):
        return self.client.post(
            reverse('dtracker-teams-create'), self.create_POST_data)

    def test_team_creation(self):
        """
        Tests that the View correctly creates a new Team and redirects to its
        page.
        """
        self.assertEqual(Team.objects.count(), 0)
        response = self.create_team()
        self.assertEqual(Team.objects.count(), 1)
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': 'qa'
        }))

    def test_invalid_team(self):
        """
        Tests that the View does not create a new Team when it is invalid.
        """
        self.create_POST_data['name'] = ''
        response = self.create_team()
        self.assertEqual(Team.objects.count(), 0)
        self.assertFormError(
            response, 'form', 'name', 'This field is required.')

    def test_authorization_for_team_creation(self):
        """
        Tests the user authorization to create a new Team.
        """
        self.client.logout()
        response = self.create_team()
        self.assertEqual(Team.objects.count(), 0)
        self.assertRedirects(
            response,
            reverse('dtracker-accounts-login') + '?next=/teams/%2Bcreate/'
        )


class TeamDetailsViewTest(UserAuthMixin, TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.TeamDetailsView`.
    """
    def setUp(self):
        self.setup_users(login=True)
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)

    def get_team_page(self, slug='team-name'):
        return self.client.get(reverse('dtracker-team-page', kwargs={
            'slug': slug
        }))

    def test_team_page_for_a_member(self):
        """
        Tests the return of a team page for a team member
        """
        response = self.get_team_page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['user_member_of_team'], True)
        self.assertTemplateUsed(response, 'core/team.html')
        self.assertContains(response, '<h1>Team name</h1>', html=True)

    def test_team_page_for_a_non_member(self):
        """
        Tests the return of a team page for non-team member
        """
        self.client.logout()
        response = self.get_team_page()
        self.assertEqual(response.status_code, 200)
        self.assertFalse('user_member_of_team' in response.context)
        self.assertTemplateUsed(response, 'core/team.html')
        self.assertContains(response, '<h1>Team name</h1>', html=True)

    def test_team_page_not_found(self):
        """
        Tests the request of non-existing team page
        """
        response = self.get_team_page(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)


class DeleteTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.DeleteTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)

    def post_team_delete(self, slug='team-name'):
        return self.client.post(
            reverse('dtracker-team-delete', kwargs={'slug': slug}))

    def test_delete_intermediary_screen(self):
        """
        Tests the confirmation popup to delete a team
        """
        response = self.client.get(
            reverse('dtracker-team-delete', kwargs={'slug': self.team.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/team-confirm-delete.html')
        self.assertContains(
            response,
            '<h3>Are you sure you want to delete the team?</h3>',
            html=True
        )

    def test_delete_team_as_owner(self):
        """
        Tests deleting a team loggedin as the team owner
        """
        response = self.post_team_delete()
        self.assertRedirects(response, reverse('dtracker-team-deleted'))
        self.assertDoesNotExist(self.team)

    def test_delete_team_as_non_owner(self):
        """
        Tests the permission denied when an user who is not the team owner
        tries to delete a team
        """
        self.login(username='paul')
        response = self.post_team_delete()
        self.assertEqual(response.status_code, 403)
        self.assertDoesExist(self.team)

    def test_delete_non_existing_team(self):
        """
        Tests the attempt to destroy a non existing team
        """
        response = self.post_team_delete(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)


class UpdateTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the :class:`distro_tracker.core.views.UpdateTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.update_POST_data = {
            'name': 'New name',
            'slug': 'new-name',
            'maintainer_email': 'newmaintainer@debian.org',
            'public': False,
            'description': 'New description',
        }

    def post_team_update(self, slug='team-name'):
        return self.client.post(
            reverse('dtracker-team-update', kwargs={'slug': slug}),
            self.update_POST_data
        )

    def test_update_team_as_owner(self):
        """
        Tests updating a team loggedin as the team owner
        """
        response = self.post_team_update()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': 'new-name'
        }))
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, self.update_POST_data['name'])
        self.assertEqual(self.team.slug, self.update_POST_data['slug'])
        self.assertEqual(
            self.team.maintainer_email.email,
            self.update_POST_data['maintainer_email']
        )
        self.assertEqual(
            self.team.description, self.update_POST_data['description'])
        self.assertFalse(self.team.public)

    def test_update_team_with_invalid_data(self):
        """
        Tests updating a team with invalid data
        """
        self.update_POST_data['name'] = ''
        response = self.post_team_update()
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response, 'form', 'name', 'This field is required.')

    def test_update_team_as_non_owner(self):
        """
        Tests the permission denied when an user who is not the team owner
        tries to update a team
        """
        self.login(username='paul')
        response = self.post_team_update()
        self.assertEqual(response.status_code, 403)
        self.team.refresh_from_db()
        self.assertNotEqual(self.team.name, self.update_POST_data['name'])
        self.assertNotEqual(self.team.slug, self.update_POST_data['slug'])
        self.assertIsNone(self.team.maintainer_email)
        self.assertNotEqual(
            self.team.description, self.update_POST_data['description'])
        self.assertTrue(self.team.public)

    def test_update_non_existing_team(self):
        """
        Tests the attempt to update a non existing team
        """
        response = self.post_team_update(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_check_update_team_maintainer_email(self):
        """
        Tests that the update team form shows the current maintainer email
        :return:
        """
        self.post_team_update()
        self.team.refresh_from_db()

        response = self.client.get(
            reverse('dtracker-team-update', kwargs={'slug': self.team.slug})
        )

        self.assertContains(response, self.team.maintainer_email.email)

    def test_reset_maintainers_email(self):
        """
        Tests passing an empty value to the maintainer email field resets it.
        :return:
        """
        self.post_team_update()
        self.team.refresh_from_db()

        data = self.update_POST_data.copy()
        data['maintainer_email'] = ''

        self.client.post(
            reverse('dtracker-team-update', kwargs={'slug': self.team.slug}),
            data
        )

        self.team.refresh_from_db()
        self.assertIsNone(self.team.maintainer_email)


class AddPackageToTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.AddPackageToTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.package = SourcePackageName.objects.create(name='dummy-package')

    def post_team_add_package(
            self, slug='team-name', package_name='dummy-package'):
        return self.client.post(
            reverse('dtracker-team-add-package', kwargs={
                'slug': slug
            }),
            {'package': package_name}
        )

    def test_add_package_as_team_member(self):
        """
        Tests adding a package to a team loggedin as a team member
        """
        response = self.post_team_add_package()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.team.packages.count(), 1)

    def test_add_non_existing_package(self):
        """
        Tests adding a non-existing package to a team loggedin as a team member
        """
        self.post_team_add_package(package_name='does-not-exist')
        self.assertEqual(self.team.packages.count(), 0)

    def test_add_package_as_no_team_member(self):
        """
        Tests the permission denied when an user who is not a team member
        tries to add a package to the team
        """
        self.login(username='paul')
        response = self.post_team_add_package()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.team.packages.count(), 0)

    def test_add_package_to_non_existing_team(self):
        """
        Tests the attempt of adding a package to a non-existing team
        """
        response = self.post_team_add_package(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)


class RemovePackageFromTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.RemovePackageFromTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.team.packages.add(self.package)

    def request_team_remove_package(self, method='post', slug='team-name',
                                    package_name='dummy-package'):
        path = reverse('dtracker-team-remove-package', kwargs={'slug': slug})
        data = {'package': package_name}
        if method == 'post':
            return self.client.post(path, data)
        else:
            return self.client.get(path, data)

    def test_remove_package_intermediary_screen(self):
        """
        Tests the confirmation popup to remove a package from a team
        """
        response = self.request_team_remove_package(method='get')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, 'core/team-remove-package-confirm.html')
        self.assertContains(
            response,
            "Are you sure you want to remove this package from the team?",
            html=True
        )

    def test_intermediary_screen_for_non_team_member(self):
        """
        Tests the confirmation popup for removing a package from a team
        loggedin as a non-team member
        """
        self.login(username='paul')
        response = self.request_team_remove_package(method='get')
        self.assertEqual(response.status_code, 403)

    def test_intermediary_screen_for_non_existing_team(self):
        """
        Tests the confirmation popup to the attempt of removing a package
        from a non-existing team
        """
        response = self.request_team_remove_package(
            method='get', slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_intermediary_screen_without_package_parameter(self):
        """
        Tests the confirmation popup to remove a package when the package
        parameter is not informed
        """
        response = self.client.get(
            reverse(
                'dtracker-team-remove-package',
                kwargs={'slug': self.team.slug}
            ),
            {}
        )
        self.assertEqual(response.status_code, 404)

    def test_remove_package_as_team_member(self):
        """
        Tests removing a package from a team loggedin as a team member
        """
        response = self.request_team_remove_package()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.team.packages.count(), 0)

    def test_remove_non_existing_package(self):
        """
        Tests removing a non-existing package from a team loggedin as a team
        member
        """
        response = self.request_team_remove_package(
            package_name='does-not-exist')
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.team.packages.count(), 1)

    def test_remove_package_as_no_team_member(self):
        """
        Tests the permission denied when an user who is not a team member
        tries to remove a package from the team
        """
        self.login(username='paul')
        response = self.request_team_remove_package()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.team.packages.count(), 1)

    def test_remove_package_from_non_existing_team(self):
        """
        Tests the attempt of removing a package from a non-existing team
        """
        response = self.request_team_remove_package(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)


class AddTeamMemberTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.AddTeamMember`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))
        self.prev_user_email_count = UserEmail.objects.count()

    def post_add_team_member(self, email=None, slug='team-name', follow=False):
        if email is None:
            email = self.get_user('paul').main_email
        return self.client.post(
            reverse('dtracker-team-add-member', kwargs={'slug': slug}),
            {'email': email},
            follow=follow
        )

    def test_add_existing_user_as_team_member(self):
        """
        Tests adding an existing user as team member logged in as the team
        owner
        """
        paul_email = self.get_user('paul').main_email
        response = self.post_add_team_member(email=paul_email)
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        self.assertIn(
            UserEmail.objects.get(email=paul_email),
            self.team.members.all()
        )
        self.assertEqual(MembershipConfirmation.objects.count(), 1)

    def test_add_non_existing_user_as_team_member(self):
        """
        Tests adding a non-existing user as team member logged in as the team
        owner
        """
        response = self.post_add_team_member(email='newuser@example.com')
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        self.assertIn(
            UserEmail.objects.get(email='newuser@example.com'),
            self.team.members.all()
        )
        self.assertEqual(
            self.prev_user_email_count + 1, UserEmail.objects.count())
        self.assertEqual(MembershipConfirmation.objects.count(), 1)

    def test_add_team_member_to_non_existing_team(self):
        """
        Tests adding a team member to a non existing team
        """
        response = self.post_add_team_member(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(MembershipConfirmation.objects.count(), 0)

    def test_add_team_member_as_not_owner(self):
        """
        Tests the permission denied when an user who is not the team owner
        tries to add a member to this team
        """
        self.login('paul')
        response = self.post_add_team_member()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MembershipConfirmation.objects.count(), 0)

    def test_add_team_member_with_invalid_email(self):
        """
        Tests adding a team member with an invalid email parameter
        """
        response = self.post_add_team_member(email='invalid-email')
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.prev_user_email_count, UserEmail.objects.count())
        self.assertEqual(MembershipConfirmation.objects.count(), 0)

    def test_add_team_member_with_an_email_already_added(self):
        """
        Tests the attempt of adding a team member with an email that
        has already been added before.
        """
        response = self.post_add_team_member(
            email=self.get_user('john').main_email, follow=True)
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        message = list(response.context['messages'])[0]
        self.assertEqual(message.level_tag, "danger")
        self.assertIn(
            ("The email address %s is already a member of the team"
                % self.get_user('john').main_email),
            message.message
        )


class JoinTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.JoinTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='paul')
        self.team = Team.objects.create_with_slug(
            owner=self.get_user('john'), name="Team name", public=True)
        self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))

    def request_join_team(self, email=None, method='post', slug='team-name'):
        path = reverse('dtracker-team-join', kwargs={'slug': slug})
        if email is None:
            email = self.get_user('paul').main_email
        data = {'email': email}
        if method == 'post':
            return self.client.post(path, data)
        else:
            return self.client.get(path)

    def test_join_team_page(self):
        """
        Tests rendering the page to join a team
        """
        response = self.request_join_team(method='get')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, 'core/team-join-choose-email.html')
        self.assertContains(
            response, "Choose an email with which to join the team")

    def test_join_team_page_for_non_existing_team(self):
        """
        Tests rendering the page to join a non existing team
        """
        response = self.request_join_team(method='get', slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_join_team_page_for_logged_out_user(self):
        """
        Tests rendering the page to join a team as a logged out user
        """
        self.client.logout()
        response = self.request_join_team(method='get')
        self.assertRedirects(
            response,
            (reverse('dtracker-accounts-login') +
                '?next=/teams/' + self.team.slug + '/%2Bjoin/')
        )

    def test_join_a_team_as_no_member(self):
        """
        Tests joining a team logged in as a no-team member
        """
        response = self.request_join_team()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertIn(
            UserEmail.objects.get(email=self.current_user.main_email),
            self.team.members.all()
        )

    def test_join_a_non_existing_team(self):
        """
        Tests joining a non-existing team
        """
        response = self.request_join_team(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_join_team_without_email_parameter(self):
        """
        Tests joining a team without the email parameter
        """
        response = self.client.post(
            reverse('dtracker-team-join', kwargs={'slug': self.team.slug}), {})
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertNotIn(
            UserEmail.objects.get(email=self.current_user.main_email),
            self.team.members.all()
        )

    def test_join_team_with_an_email_not_registered(self):
        """
        Tests the permission denied when an user tries to join a team with
        an email not registered in his/her account
        """
        response = self.request_join_team(email='paul@notregistered.com')
        self.assertEqual(response.status_code, 403)

    def test_join_a_non_public_team(self):
        """
        Tests the attempt of joining a non-public team
        """
        self.team.public = False
        self.team.save()
        response = self.request_join_team()
        self.assertEqual(response.status_code, 403)


class LeaveTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.LeaveTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))

    def request_leave_team(self, method='post', slug='team-name'):
        path = reverse('dtracker-team-leave', kwargs={'slug': slug})
        if method == 'post':
            return self.client.post(path)
        else:
            return self.client.get(path)

    def test_leave_team_page(self):
        """
        Tests rendering the page to leave a team
        """
        response = self.request_leave_team(method='get')
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))

    def test_leave_team_page_for_non_existing_team(self):
        """
        Tests rendering the page to leave a non existing team
        """
        response = self.request_leave_team(method='get', slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_leave_team_page_for_logged_out_user(self):
        """
        Tests rendering the page to leave a team as a logged out user
        """
        self.client.logout()
        response = self.request_leave_team(method='get')
        self.assertRedirects(
            response,
            (reverse('dtracker-accounts-login') +
                '?next=/teams/' + self.team.slug + '/%2Bleave/')
        )

    def test_leave_a_team_as_member(self):
        """
        Tests leaving a team logged in as a team member
        """
        response = self.request_leave_team()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertNotIn(
            UserEmail.objects.get(email=self.current_user.main_email),
            self.team.members.all()
        )

    def test_leave_a_non_existing_team(self):
        """
        Tests leaving a non-existing team
        """
        response = self.request_leave_team(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_leave_team_as_non_member(self):
        """
        Tests the permission denied when a no-team member tries to leave
        the team
        """
        self.login('paul')
        response = self.request_leave_team()
        self.assertEqual(response.status_code, 403)


class ManageTeamMembersTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.ManageTeamMembers`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))
        self.team.add_members(
            UserEmail.objects.filter(email=self.get_user('paul').main_email))

    def get_manage_team_members(self, slug='team-name'):
        return self.client.get(
            reverse('dtracker-team-manage', kwargs={'slug': slug}))

    def test_manage_team_members_as_owner(self):
        """
        Tests rendering manage team members page for team owner
        """
        response = self.get_manage_team_members()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, 'core/team-manage.html')
        self.assertContains(response, "Member management for team")
        self.assertContains(response, "<h3>Team members</h3>", html=True)
        self.assertEqual(response.context['team'], self.team)
        self.assertTrue(isinstance(response.context['form'], AddTeamMemberForm))

    def test_manage_team_members_as_not_owner(self):
        """
        Tests rendering manage team members page for a user who is not the
        team owner
        """
        self.login('paul')
        response = self.get_manage_team_members()
        self.assertEqual(response.status_code, 403)

    def test_manage_team_members_for_non_existing_team(self):
        """
        Tests rendering manage team members page for a non existing team
        """
        response = self.get_manage_team_members(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)


class RemoveTeamMemberTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.RemoveTeamMember`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))
        self.team.add_members(
            UserEmail.objects.filter(email=self.get_user('paul').main_email))

    def post_remove_team_member(self, slug='team-name', email=None):
        if email is None:
            email = self.get_user('paul').main_email
        return self.client.post(
            reverse('dtracker-team-remove-member', kwargs={'slug': slug}),
            {'email': email}
        )

    def test_remove_team_member_as_owner(self):
        """
        Tests removing a team member as owner
        """
        response = self.post_remove_team_member()
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        self.assertNotIn(
            UserEmail.objects.get(email=self.get_user('paul').main_email),
            self.team.members.all()
        )

    def test_remove_team_member_from_non_existing_team(self):
        """
        Tests removing a team member of a non existing team
        """
        response = self.post_remove_team_member(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_remove_team_member_as_not_owner(self):
        """
        Tests the permission denied when an user who is not the team owner
        tries to remove a member of this team
        """
        self.login('paul')
        response = self.post_remove_team_member()
        self.assertEqual(response.status_code, 403)

    def test_remove_team_member_without_email_parameter(self):
        """
        Tests removing a team member without the email parameter
        """
        response = self.client.post(
            reverse(
                'dtracker-team-remove-member',
                kwargs={'slug': self.team.slug}
            ),
            {}
        )
        self.assertRedirects(response, reverse('dtracker-team-manage', kwargs={
            'slug': self.team.slug
        }))
        self.assertIn(
            UserEmail.objects.get(email=self.current_user.main_email),
            self.team.members.all()
        )


class ConfirmMembershipViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.ConfirmMembershipView`.
    """
    def setUp(self):
        self.setup_users(login=True)
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.membership = self.team.add_members(
            [UserEmail.objects.create(email='joe@debian.org')], muted=True)[0]
        self.confirmation = MembershipConfirmation.objects.create_confirmation(
            membership=self.membership)
        self.client.logout()

    def get_confirm_membership(self, slug='team-name', confirmation_key=None):
        if not confirmation_key:
            confirmation_key = self.confirmation.confirmation_key
        return self.client.get(reverse(
            'dtracker-team-confirm-membership',
            kwargs={'confirmation_key': confirmation_key}
        ))

    def test_confirm_membership(self):
        """
        Tests a valid request to confirm membership
        """
        response = self.get_confirm_membership()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.membership.refresh_from_db()
        self.assertFalse(self.membership.muted)
        self.assertDoesNotExist(self.confirmation)

    def test_confirm_membership_with_invalid_key(self):
        """
        Tests the attempt to confirm membership with a invalid key
        """
        response = self.get_confirm_membership(confirmation_key='invalid-key')
        self.assertEqual(response.status_code, 404)

    def test_confirm_membership_twice(self):
        """
        Tests the attempt to confirm membership twice
        """
        response = self.get_confirm_membership()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        response = self.get_confirm_membership()
        self.assertEqual(response.status_code, 404)


class TeamListViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.TeamListView`.
    """
    def setUp(self):
        self.setup_users(login=True)
        self.first_team = Team.objects.create_with_slug(
            owner=self.current_user, name="First team", public=True)
        self.second_team = Team.objects.create_with_slug(
            owner=self.current_user, name="Second team", public=True)
        self.third_team = Team.objects.create_with_slug(
            owner=self.current_user, name="Third team", public=False)
        self.response = self.client.get(reverse('dtracker-team-list'))

    def test_team_list_page(self):
        """
        Tests rendering the team list page
        """
        self.assertEqual(self.response.status_code, 200)
        self.assertTemplateUsed(self.response, 'core/team-list.html')
        self.assertContains(self.response, "<h1>List of teams</h1>", html=True)

    def test_team_list_contains_public_teams_only(self):
        """
        Tests the inclusion of public teams only in the team list
        """
        self.assertIn(self.first_team, self.response.context['team_list'])
        self.assertIn(self.second_team, self.response.context['team_list'])
        self.assertNotIn(self.third_team, self.response.context['team_list'])

    def test_team_list_is_ordered_by_name(self):
        """
        Tests the order of the team list
        """
        self.assertEqual(
            [{'name': 'First team'}, {'name': 'Second team'}],
            list(self.response.context['team_list'].values('name'))
        )


class SetMuteTeamViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.SetMuteTeamView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.membership = self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))[0]
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.team.packages.add(self.package)

    def post_set_mute_team(self, slug='team-name', action='mute',
                           email='john@example.com', package=None,
                           next_url=None):
        data = {}
        if email:
            data['email'] = email
        if package:
            data['package'] = package
        if next_url:
            data['next'] = next_url
        return self.client.post(
            reverse('dtracker-team-' + action, kwargs={'slug': slug}), data)

    def assert_membership_muted(self, action='mute', muted=True):
        response = self.post_set_mute_team(action=action)
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.muted, muted)

    def test_mute_team_membership(self):
        """
        Tests muting a team membership as a team member
        """
        self.assert_membership_muted()

    def test_unmute_team_membership(self):
        """
        Tests unmuting a team membership as a team member
        """
        self.membership.muted = True
        self.membership.save()
        self.assert_membership_muted(action='unmute', muted=False)

    def test_mute_team_membership_redirection_to_next_url(self):
        """
        Tests muting a team membership and redirecting to the url
        informed in 'next' parameter
        """
        next_url = self.package.get_absolute_url()
        response = self.post_set_mute_team(next_url=next_url)
        self.assertRedirects(response, next_url)

    def test_mute_team_membership_as_no_team_member(self):
        """
        Tests muting a team membership as a no-team member
        """
        self.login('paul')
        response = self.post_set_mute_team(email=self.current_user.main_email)
        self.assertEqual(response.status_code, 404)

    def test_mute_team_membership_for_non_existing_team(self):
        """
        Tests muting a team membership for a non-existing team
        """
        response = self.post_set_mute_team(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_mute_team_membership_without_email_parameter(self):
        """
        Tests muting a team membership without send the email parameter
        """
        response = self.post_set_mute_team(email=None)
        self.assertEqual(response.status_code, 404)

    def test_mute_team_membership_with_unregistered_email(self):
        """
        Tests muting a team membership with an email that does not belong to
        the logged user
        """
        response = self.post_set_mute_team(email='unregistered@example.com')
        self.assertEqual(response.status_code, 403)

    def test_mute_package_in_team_membership(self):
        """
        Tests muting a particular package in a team membership as a team member
        """
        response = self.post_set_mute_team(package=self.package.name)
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertTrue(self.membership.is_muted(self.package))


class SetMembershipKeywordsTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.SetMembershipKeywords`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.membership = self.team.add_members(
            self.team.owner.emails.filter(email=self.team.owner.main_email))[0]
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.team.packages.add(self.package)

    def post_set_membership_keywords(
        self,
        slug='team-name',
        email='john@example.com',
        keyword=['translation', 'derivatives'],
        package=None,
        next_url=None
    ):
        data = {}
        if email:
            data['email'] = email
        if package:
            data['package'] = package
        if next_url:
            data['next'] = next_url
        if keyword:
            data['keyword[]'] = keyword
        return self.client.post(
            reverse('dtracker-team-set-keywords', kwargs={'slug': slug}), data)

    def test_set_membership_keywords(self):
        """
        Tests setting membership keywords as a team member
        """
        response = self.post_set_membership_keywords()
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.membership.default_keywords.count(), 2)

    def test_set_membership_keywords_through_ajax_request(self):
        """
        Tests setting membership keywords as a team member through Ajax request
        """
        response = self.client.post(
            reverse(
                'dtracker-team-set-keywords', kwargs={'slug': self.team.slug}),
            {'email': self.current_user.main_email, 'keyword[]': ['bts']},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertJSONEqual(
            str(response.content, encoding='utf8'), {'status': 'ok'})

    def test_set_membership_keywords_with_redirection_to_next_url(self):
        """
        Tests setting membership keywords and redirecting to the url
        informed in 'next' parameter
        """
        next_url = self.package.get_absolute_url()
        response = self.post_set_membership_keywords(next_url=next_url)
        self.assertRedirects(response, next_url)
        self.assertEqual(self.membership.default_keywords.count(), 2)

    def test_set_membership_keywords_as_no_team_member(self):
        """
        Tests setting membership keywords as a no-team member
        """
        self.login('paul')
        response = self.post_set_membership_keywords(
            email=self.current_user.main_email)
        self.assertEqual(response.status_code, 404)

    def test_set_membership_keywords_for_non_existing_team(self):
        """
        Tests setting membership keywords for a non-existing team
        """
        response = self.post_set_membership_keywords(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_set_membership_keywords_without_email_parameter(self):
        """
        Tests setting membership keywords without send the email parameter
        """
        response = self.post_set_membership_keywords(email=None)
        self.assertEqual(response.status_code, 404)

    def test_set_membership_keywords_without_keyword_parameter(self):
        """
        Tests setting membership keywords without send the keyword[] parameter
        """
        response = self.post_set_membership_keywords(keyword=None)
        self.assertEqual(response.status_code, 404)

    def test_set_membership_keywords_with_unregistered_email(self):
        """
        Tests setting membership keywords with an email that does not belong
        to the logged user
        """
        response = self.post_set_membership_keywords(
            email='unregistered@example.com')
        self.assertEqual(response.status_code, 403)

    def test_set_membership_keywords_for_package_in_team(self):
        """
        Tests setting package-specific keywords as a team member
        """
        response = self.post_set_membership_keywords(package=self.package.name)
        self.assertRedirects(response, reverse('dtracker-team-page', kwargs={
            'slug': self.team.slug
        }))
        self.assertEqual(self.membership.get_keywords(self.package).count(), 2)


class EditMembershipViewTest(UserAuthMixin, TestCase):
    """
    Tests for the
    :class:`distro_tracker.core.views.EditMembershipView`.
    """
    USERS = {
        'john': {},
        'paul': {},
    }

    def setUp(self):
        self.setup_users(login='john')
        self.team = Team.objects.create_with_slug(
            owner=self.current_user, name="Team name", public=True)
        self.membership = self.team.add_members(
            UserEmail.objects.filter(email=self.team.owner.main_email))[0]
        self.first_package = SourcePackageName.objects.create(
            name='first-package')
        self.second_package = SourcePackageName.objects.create(
            name='second-package')
        self.team.packages.add(self.first_package)
        self.team.packages.add(self.second_package)
        self.membership.set_mute_package(self.second_package, True)

    def get_edit_membership(self, slug='team-name', email='john@example.com'):
        data = {}
        if email:
            data['email'] = email
        return self.client.get(
            reverse('dtracker-team-manage-membership', kwargs={'slug': slug}),
            data
        )

    def test_edit_membership(self):
        """
        Tests rendering the edit membership page
        """
        response = self.get_edit_membership()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, 'core/edit-team-membership.html')
        self.assertContains(response, "Membership management for ")
        self.assertEqual(
            self.membership,
            response.context['membership']
        )
        self.assertIn(
            self.first_package, response.context['package_list'])
        self.assertIn(
            self.second_package, response.context['package_list'])
        for package in response.context['package_list']:
            self.assertIn(package.is_muted, [True, False])

    def test_edit_membership_in_non_existing_team(self):
        """
        Tests the attempt to render edit membership page for non-existing team
        """
        response = self.get_edit_membership(slug='does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_edit_membership_without_email_parameter(self):
        """
        Tests the attempt to render edit membership page without the email
        parameter
        """
        response = self.get_edit_membership(email=None)
        self.assertEqual(response.status_code, 404)

    def test_edit_membership_with_unregistered_email(self):
        """
        Tests the attempt to render edit membership page with an unregistered
        email
        """
        response = self.get_edit_membership(email='unregistered@example.com')
        self.assertEqual(response.status_code, 403)

    def test_edit_membership_as_no_team_member(self):
        """
        Tests the attempt to render edit membership page as no-team member
        """
        self.login('paul')
        response = self.get_edit_membership(email=self.current_user.main_email)
        self.assertEqual(response.status_code, 404)


class NewsViewTest(TestCase, TemplateTestsMixin):
    """
    Tests for the :class:`distro_tracker.core.views.PackageNews`.
    """

    NEWS_LIMIT = settings.DISTRO_TRACKER_NEWS_PANEL_LIMIT

    def setUp(self):
        self.package = SourcePackageName.objects.create(name='dummy-package')
        self.src_pkg = SourcePackage.objects.create(
            source_package_name=self.package, version='1.0.0')
        self.src_pkg.save()
        self.news_url = reverse('dtracker-package-news',
                                kwargs={'package_name': self.package.name})
        # add some news
        for i in range(2 * self.NEWS_LIMIT + 1):
            self.package.news_set.create(title="News {}".format(i),
                                         created_by="Author {}".format(i))

    def get_package_news(self, page=None):
        if not page:
            return self.client.get(self.news_url)
        else:
            return self.client.get('%s?page=%s' % (self.news_url, page))

    def test_news_page_urls(self):
        """
        Tests all possibile urls to access the page of a single news
        """
        news = self.package.news_set.first()
        url = reverse('dtracker-news-page', kwargs={'news_id': news.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(url + '/')
        self.assertEqual(response.status_code, 200)
        response = self.client.get(news.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_news_page_has_link_to_package_page(self):
        response = self.get_package_news()
        self.assertLinkIsInResponse(response, package_url(self.package))

    def test_news_page_has_paginated_link_to_page_2(self):
        response = self.get_package_news()
        self.assertLinkIsInResponse(response, '?page=2')

    def test_news_page_has_no_invalid_paginated_link(self):
        response = self.get_package_news()
        self.assertLinkIsNotInResponse(response, '?page=4')

    def test_page_2_of_news_page_has_link_to_page_1(self):
        response = self.get_package_news(page=2)
        self.assertLinkIsInResponse(response, '?page=1')
