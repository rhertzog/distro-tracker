# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at http://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at http://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""
Implements all commands which deal with teams.
"""
from __future__ import unicode_literals

from distro_tracker.mail.control.commands.base import Command
from distro_tracker.mail.control.commands.confirmation import needs_confirmation

from distro_tracker.core.models import Team
from distro_tracker.core.models import UserEmail
from distro_tracker.core.utils import get_or_none


@needs_confirmation
class JoinTeam(Command):
    """
    Command which lets users join an existing public team.
    """
    META = {
        'description': """join-team <team-slug> [<email>]
  Adds <email> to team with the slug given by <team-slug>. If
  <email> is not given, it adds the From address email to the team.
  If the team is not public or it does not exist, a warning is
  returned.""",
        'name': 'join-team',
    }
    REGEX_LIST = (
        r'\s+(?P<team_slug>\S+)(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, team_slug, email):
        super(JoinTeam, self).__init__()
        self.user_email = email
        self.team_slug = team_slug

    def get_team_and_user(self):
        team = get_or_none(Team, slug=self.team_slug)
        if not team:
            self.error('Team with the slug "{}" does not exist.'.format(
                self.team_slug))
            return
        if not team.public:
            self.error(
                "The given team is not public. "
                "Please contact {} if you wish to join".format(
                    team.owner.main_email))
            return

        user_email, _ = UserEmail.objects.get_or_create(email=self.user_email)
        if user_email in team.members.all():
            self.warn("You are already a member of the team.")
            return

        return team, user_email

    def pre_confirm(self):
        packed = self.get_team_and_user()
        if packed is None:
            return False

        self.reply('A confirmation mail has been sent to ' + self.user_email)
        return True

    def get_command_text(self):
        return super(JoinTeam, self).get_command_text(
            self.team_slug, self.user_email)

    def handle(self):
        packed = self.get_team_and_user()
        if packed is None:
            return
        team, user_email = packed
        team.add_members([user_email])
        self.reply('You have successfully joined the team "{}"'.format(team))


@needs_confirmation
class LeaveTeam(Command):
    """
    Command which lets users leave a team they are already a member of.
    """
    META = {
        'description': """leave-team <team-slug> [<email>]
  Removes <email> from the team with the slug given by <team-slug>. If
  <email> is not given, it uses the From address email.
  If the user is not a member of the team, a warning is returned.""",
        'name': 'leave-team',
    }
    REGEX_LIST = (
        r'\s+(?P<team_slug>\S+)(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, team_slug, email):
        super(LeaveTeam, self).__init__()
        self.user_email = email
        self.team_slug = team_slug

    def get_team_and_user(self):
        team = get_or_none(Team, slug=self.team_slug)
        if not team:
            self.error('Team with the slug "{}" does not exist.'.format(
                self.team_slug))
            return
        user_email, _ = UserEmail.objects.get_or_create(email=self.user_email)
        if user_email not in team.members.all():
            self.warn("You are not a member of the team.")
            return

        return team, user_email

    def pre_confirm(self):
        packed = self.get_team_and_user()
        if packed is None:
            return False

        self.reply('A confirmation mail has been sent to ' + self.user_email)
        return True

    def get_command_text(self):
        return super(LeaveTeam, self).get_command_text(
            self.team_slug, self.user_email)

    def handle(self):
        packed = self.get_team_and_user()
        if packed is None:
            return
        team, user_email = packed
        team.remove_members([user_email])
        self.reply('You have successfully left the team "{}" (slug: {})'.format(
            team, team.slug))


class ListTeamPackages(Command):
    """
    Lists all the packages of a particular team, provided that the team is
    public or the email doing the query is a member of the team.
    """
    META = {
        'description': """list-team-packages <team-slug>
  Lists all packages of the team with the slug given by <team-slug>.
  If the team is private, the packages are returned only if the From email
  is a member of the team.""",
        'name': 'list-team-packages',
    }
    REGEX_LIST = (
        r'\s+(?P<team_slug>\S+)$',
    )

    def __init__(self, team_slug):
        super(ListTeamPackages, self).__init__()
        self.team_slug = team_slug

    @property
    def user_email(self):
        return self.context['email']

    def get_team(self):
        team = get_or_none(Team, slug=self.team_slug)
        if not team:
            self.error('Team with the slug "{}" does not exist.'.format(
                self.team_slug))
            return
        return team

    def get_user_email(self):
        user_email, _ = UserEmail.objects.get_or_create(email=self.user_email)
        return user_email

    def get_command_text(self):
        return super(ListTeamPackages, self).get_command_text(
            self.team_slug)

    def handle(self):
        team = self.get_team()
        if not team:
            return
        if not team.public:
            user_email = self.get_user_email()
            if user_email not in team.members.all():
                self.error(
                    "The team is private. "
                    "Only team members can see its packages.")
                return

        self.reply("Packages found in team {}:".format(team))
        self.list_reply(package for package in
                        team.packages.all().order_by('name'))


class WhichTeams(Command):
    """
    Returns a list of teams that the given email is a member of.
    """
    META = {
        'description': """which-teams [<email>]
  Lists all teams that <email> is a member of. If <email> is not given, the
  sender's email is used.""",
        'name': 'which-teams',
    }
    REGEX_LIST = (
        r'(?:\s+(?P<email>\S+))?$',
    )

    def __init__(self, email):
        super(WhichTeams, self).__init__()
        self.user_email = email

    def get_user_email(self):
        user_email, _ = UserEmail.objects.get_or_create(email=self.user_email)
        return user_email

    def handle(self):
        user_email = self.get_user_email()

        if user_email.teams.count() == 0:
            self.warn("{} is not a member of any team.".format(self.user_email))
        else:
            self.reply("Teams that {} is a member of:".format(self.user_email))
            self.list_reply(
                team.slug
                for team in user_email.teams.all().order_by('name'))
