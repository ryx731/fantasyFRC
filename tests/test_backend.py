import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.auth import verify_password
from src.database import Base
from src.models import League, Roster, RosterTeam, User
from src.routers import auth, leagues
from src.schemas import DraftPick, LeagueCreate


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.owner = User(username='owner', hashed_password='!google')
        self.member = User(username='member', hashed_password='!google')
        self.other = User(username='other', hashed_password='!google')
        self.db.add_all([self.owner, self.member, self.other])
        self.db.commit()
        result = leagues.create_league(LeagueCreate(name='  Test league  ', max_teams=2), self.db, self.owner)
        self.league = self.db.get(League, result['league_id'])

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def assert_error(self, status, operation):
        with self.assertRaises(HTTPException) as error:
            operation()
        self.assertEqual(error.exception.status_code, status)

    def test_create_assigns_owner_and_roster(self):
        self.assertEqual(self.league.name, 'Test league')
        self.assertEqual(self.league.owner_id, self.owner.id)
        self.assertEqual(self.db.query(Roster).count(), 1)

    def test_join_missing_league(self):
        self.assert_error(404, lambda: leagues.join_league(999, self.db, self.member))

    def test_duplicate_join(self):
        self.assert_error(400, lambda: leagues.join_league(self.league.id, self.db, self.owner))

    def test_capacity(self):
        leagues.join_league(self.league.id, self.db, self.member)
        self.assert_error(400, lambda: leagues.join_league(self.league.id, self.db, self.other))
        self.assertEqual(self.db.query(Roster).count(), 2)

    def test_join_after_start(self):
        self.league.draft_status = 'ACTIVE'
        self.assert_error(400, lambda: leagues.join_league(self.league.id, self.db, self.member))

    def test_draft_turn_duplicate_and_completion(self):
        leagues.join_league(self.league.id, self.db, self.member)
        self.league.draft_status = 'ACTIVE'
        self.league.draft_order = f'{self.owner.id},{self.member.id}'
        pick = DraftPick(league_id=self.league.id, team_number=254)
        self.assert_error(400, lambda: leagues.draft_team(pick, self.db, self.member))
        leagues.draft_team(pick, self.db, self.owner)
        self.assert_error(400, lambda: leagues.draft_team(pick, self.db, self.member))
        leagues.draft_team(DraftPick(league_id=self.league.id, team_number=1690), self.db, self.member)
        self.assertEqual(self.league.draft_status, 'COMPLETED')
        self.assertEqual(self.db.query(RosterTeam).count(), 2)

    def test_exhausted_active_draft(self):
        self.league.draft_status = 'ACTIVE'
        self.league.draft_order = str(self.owner.id)
        self.league.current_pick_index = 1
        self.assert_error(400, lambda: leagues.draft_team(DraftPick(league_id=self.league.id, team_number=254), self.db, self.owner))
        state = leagues.get_draft_state(self.league.id, self.db, self.owner)
        self.assertEqual(state['current_picker_name'], 'None')

    def test_payload_validation(self):
        for payload in ({'name': '  '}, {'name': 'Test', 'max_teams': 0}):
            with self.assertRaises(ValidationError):
                LeagueCreate(**payload)
        with self.assertRaises(ValidationError):
            DraftPick(league_id=1, team_number=-1)

    def test_google_accounts_cannot_use_password_login(self):
        self.assertFalse(verify_password('google_oauth_dummy', '!google'))

    @patch.object(auth, 'GOOGLE_CLIENT_ID', 'test-client')
    @patch.object(auth.id_token, 'verify_oauth2_token')
    def test_google_does_not_match_local_part(self, verify):
        verify.return_value = {'email': 'owner@example.com', 'email_verified': True}
        result = auth.google_auth(auth.GoogleToken(credential='test'), self.db)
        self.assertNotEqual(result['user_id'], self.owner.id)
        self.assertEqual(result['username'], 'owner@example.com')

    @patch.object(auth, 'GOOGLE_CLIENT_ID', 'test-client')
    @patch.object(auth.id_token, 'verify_oauth2_token')
    def test_google_does_not_link_password_account(self, verify):
        self.db.add(User(username='owner@example.com', hashed_password='password-account'))
        self.db.commit()
        verify.return_value = {'email': 'owner@example.com', 'email_verified': True}
        self.assert_error(409, lambda: auth.google_auth(auth.GoogleToken(credential='test'), self.db))


if __name__ == '__main__':
    unittest.main()
