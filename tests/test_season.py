import unittest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.database import Base
from src.migrations import migrate
from src.models import User, League, Roster, RosterTeam, Matchup, Period, Observation, Claim, Trade
from src.routers import leagues as api
from src.schemas import LeagueCreate, JoinLeague, DraftPick, Lineup, TeamAction, TradeOffer, Decision, ScoringRules, ScoreImport
from src.scoring import default_rules, score_metrics


class SeasonTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.users = [User(username=f'manager{i}', hashed_password='!google') for i in range(5)]
        self.db.add_all(self.users); self.db.commit()
        self.owner = self.users[0]
        result = api.create_league(LeagueCreate(name='District', max_teams=4, roster_size=2, starter_count=1, regular_weeks=3), self.db, self.owner)
        self.id = result['league_id']; self.league = self.db.get(League, self.id)

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def denied(self, status, fn):
        with self.assertRaises(HTTPException) as error: fn()
        self.assertEqual(error.exception.status_code, status)
        self.db.rollback()

    def draft(self, count=2):
        for u in self.users[1:count]: api.join_by_code(JoinLeague(code=self.league.invite_code.lower()), self.db, u)
        api.start_draft(self.id, self.db, self.owner)
        for i, uid in enumerate(self.league.draft_order.split(',')):
            api.draft_team(DraftPick(league_id=self.id, team_number=100+i), self.db, self.db.get(User, int(uid)))

    def activate(self):
        data = default_rules(); data.pop('preset')
        api.set_scoring(self.id, ScoringRules(**data, active=True), self.db, self.owner)

    def records(self, week=1):
        return ScoreImport(rules_version=default_rules()['version'], records=[
            {'match_key': f'event{week}_qm1', 'team_number': int(t.team_key[3:]),
             'metrics': {'auto': 10, 'teleop': 20, 'endgame': 3, 'cycles': 2, 'win': 1, 'fouls': 0}}
            for t in self.db.query(RosterTeam)])

    def test_private_invites_and_rotation(self):
        self.assertEqual(len(self.league.invite_code), 12)
        self.denied(403, lambda: api.league_home(self.id, self.db, self.users[4]))
        self.denied(403, lambda: api.get_draft_state(self.id, self.db, self.users[4]))
        self.denied(403, lambda: api.rotate_invite(self.id, self.db, self.users[1]))
        old = self.league.invite_code
        api.rotate_invite(self.id, self.db, self.owner)
        self.denied(404, lambda: api.join_by_code(JoinLeague(code=old), self.db, self.users[1]))
        self.assertEqual(len(api.my_leagues(self.db, self.owner)), 1)
        self.assertEqual(len(api.my_leagues(self.db, self.users[1])), 0)

    def test_snake_and_round_robin(self):
        self.draft(4)
        seq = self.league.draft_order.split(',')
        self.assertEqual(seq[4:], seq[:4][::-1])
        self.assertEqual(self.league.draft_status, 'COMPLETED')
        matches = self.db.query(Matchup).all()
        self.assertEqual(len(matches), 6)
        self.assertEqual(len({frozenset((m.roster1_id, m.roster2_id)) for m in matches}), 6)
        for r in self.league.rosters:
            self.assertEqual(len(r.teams), 2)
            self.assertEqual(sum(t.position == 'STARTER' for t in r.teams), 1)

    def test_odd_manager_byes(self):
        self.draft(3)
        matches = self.db.query(Matchup).all()
        self.assertEqual(len(matches), 3)
        for r in self.league.rosters:
            self.assertEqual(sum(r.id in (m.roster1_id, m.roster2_id) for m in matches), 2)

    def test_commissioner_proxy_pick_is_authorized_and_uses_current_turn(self):
        api.join_by_code(JoinLeague(code=self.league.invite_code), self.db, self.users[1])
        api.start_draft(self.id, self.db, self.owner)
        uid = int(self.league.draft_order.split(',')[0])
        self.denied(403, lambda: api.commissioner_pick(self.id, TeamAction(team_number=254), self.db, self.users[1]))
        api.commissioner_pick(self.id, TeamAction(team_number=254), self.db, self.owner)
        self.assertEqual(api.held(self.db, self.league, 'frc254').roster.user_id, uid)
        self.assertEqual(self.league.current_pick_index, 1)

    def test_lineup_ownership_and_limits(self):
        self.draft()
        r = self.league.rosters[0]
        self.denied(400, lambda: api.save_lineup(self.id, Lineup(starters=[int(t.team_key[3:]) for t in r.teams]), self.db, self.owner))
        self.denied(400, lambda: api.save_lineup(self.id, Lineup(starters=[9999]), self.db, self.owner))
        api.save_lineup(self.id, Lineup(starters=[int(r.teams[-1].team_key[3:])]), self.db, self.owner)
        self.assertEqual(r.teams[-1].position, 'STARTER')

    def test_scoring_locks_corrections_and_finalization(self):
        self.draft()
        self.denied(400, lambda: api.open_period(self.id, 1, self.db, self.owner))
        self.activate(); api.open_period(self.id, 1, self.db, self.owner)
        self.denied(400, lambda: api.save_lineup(self.id, Lineup(starters=[]), self.db, self.owner))
        self.denied(400, lambda: api.create_claim(self.id, TeamAction(team_number=500), self.db, self.owner))
        self.denied(400, self.activate)
        data = self.records()
        api.import_scores(self.id, 1, data, self.db, self.owner)
        api.import_scores(self.id, 1, data, self.db, self.owner)
        self.assertEqual(self.db.query(Observation).count(), 4)
        self.assertEqual(self.db.query(Matchup).filter_by(week=1).first().roster1_score, 38)
        data.records[0].metrics['auto'] = 40
        api.import_scores(self.id, 1, data, self.db, self.owner)
        self.assertEqual(self.db.query(Observation).count(), 4)
        api.finalize_period(self.id, 1, self.db, self.owner)
        self.denied(400, lambda: api.import_scores(self.id, 1, data, self.db, self.owner))
        self.denied(400, lambda: api.open_period(self.id, 3, self.db, self.owner))
        api.open_period(self.id, 2, self.db, self.owner)
        self.assertEqual(sum(r['wins'] + r['ties'] for r in api.league_home(self.id, self.db, self.owner)['standings']), 1)

    def test_bad_import_has_no_partial_changes(self):
        self.draft(); self.activate(); api.open_period(self.id, 1, self.db, self.owner)
        data = self.records(); data.records[-1].metrics.pop('auto')
        self.denied(400, lambda: api.import_scores(self.id, 1, data, self.db, self.owner))
        self.assertEqual(self.db.query(Observation).count(), 0)
        data = self.records(); data.rules_version = 'wrong'
        self.denied(400, lambda: api.import_scores(self.id, 1, data, self.db, self.owner))

    def test_average_and_bench_exclusion(self):
        self.draft(); self.activate(); api.open_period(self.id, 1, self.db, self.owner)
        data = self.records(); extra = data.records[0].copy(deep=True)
        extra.match_key = 'another_qm2'; extra.metrics['auto'] = 30
        data.records.append(extra); api.import_scores(self.id, 1, data, self.db, self.owner)
        r = self.db.get(RosterTeam, 1).roster
        m = self.db.query(Matchup).filter_by(week=1).first()
        self.assertEqual(m.roster1_score if m.roster1_id == r.id else m.roster2_score, 48)

    def test_remove_bad_record_and_cross_period_duplicate(self):
        self.draft(); self.activate(); api.open_period(self.id, 1, self.db, self.owner)
        data = self.records(); api.import_scores(self.id, 1, data, self.db, self.owner)
        record = self.db.query(Observation).first(); rid = record.id
        self.denied(403, lambda: api.remove_score(self.id, 1, rid, self.db, self.users[1]))
        api.remove_score(self.id, 1, rid, self.db, self.owner)
        self.assertEqual(self.db.query(Observation).count(), 3)
        api.import_scores(self.id, 1, data, self.db, self.owner)
        api.finalize_period(self.id, 1, self.db, self.owner)
        self.denied(400, lambda: api.remove_score(self.id, 1, self.db.query(Observation).first().id, self.db, self.owner))
        api.open_period(self.id, 2, self.db, self.owner)
        self.denied(400, lambda: api.import_scores(self.id, 2, data, self.db, self.owner))
        self.assertEqual(self.db.query(Observation).filter_by(week=2).count(), 0)

    def test_sum_scoring(self):
        self.draft()
        data = default_rules(); data.pop('preset'); data['aggregation'] = 'sum'
        api.set_scoring(self.id, ScoringRules(**data, active=True), self.db, self.owner)
        api.open_period(self.id, 1, self.db, self.owner)
        payload = self.records(); extra = payload.records[0].copy(deep=True); extra.match_key = 'event_qm2'
        payload.records.append(extra); api.import_scores(self.id, 1, payload, self.db, self.owner)
        r = self.db.get(RosterTeam, 1).roster
        m = self.db.query(Matchup).filter_by(week=1).first()
        self.assertEqual(m.roster1_score if m.roster1_id == r.id else m.roster2_score, 76)

    def test_waiver_conflict_and_rolling_priority(self):
        self.draft()
        a, b = sorted(self.league.rosters, key=lambda r: r.waiver_priority)
        for r in (b, a): api.create_claim(self.id, TeamAction(team_number=999, drop_team_number=int(r.teams[-1].team_key[3:])), self.db, r.user)
        api.process_waivers(self.id, self.db, self.owner)
        self.assertEqual(api.held(self.db, self.league, 'frc999').roster_id, a.id)
        self.assertEqual(a.waiver_priority, 2)
        self.assertEqual(sorted(c.status for c in self.db.query(Claim)), ['FAILED', 'SUCCESS'])
        self.assertEqual(self.db.query(RosterTeam).count(), 4)

    def test_trade_permission_and_position_swap(self):
        self.draft(); a, b = self.league.rosters
        give, receive = a.teams[0].team_key, b.teams[-1].team_key
        api.propose_trade(self.id, TradeOffer(receiver_id=b.id, give_number=int(give[3:]), receive_number=int(receive[3:])), self.db, a.user)
        t = self.db.query(Trade).first()
        self.denied(403, lambda: api.decide_trade(self.id, t.id, Decision(action='accept'), self.db, a.user))
        api.decide_trade(self.id, t.id, Decision(action='accept'), self.db, b.user)
        self.assertEqual(api.held(self.db, self.league, give).roster_id, b.id)
        self.assertEqual(api.held(self.db, self.league, receive).roster_id, a.id)
        self.db.expire_all()
        for r in self.league.rosters: self.assertEqual(sum(t.position == 'STARTER' for t in r.teams), 1)

    def test_playoff_progression_and_season_end(self):
        self.league.playoff_teams = 4; self.league.regular_weeks = 1; self.db.commit()
        self.draft(4); self.activate()
        for week in (1, 2, 3):
            api.open_period(self.id, week, self.db, self.owner)
            api.import_scores(self.id, week, self.records(week), self.db, self.owner)
            api.finalize_period(self.id, week, self.db, self.owner)
        self.assertEqual([p.kind for p in self.db.query(Period).order_by(Period.week)], ['REGULAR', 'SEMIFINAL', 'FINAL'])
        self.assertEqual(self.db.query(Matchup).filter_by(week=3).count(), 1)
        self.denied(400, lambda: api.drop_team(self.id, TeamAction(team_number=100), self.db, self.owner))

    def test_scoring_contract(self):
        self.assertEqual(score_metrics({'auto': 1, 'teleop': 2, 'endgame': 3, 'win': 0.5, 'fouls': 1}, default_rules()), 7.5)
        with self.assertRaises(ValueError): score_metrics({'auto': float('nan')}, default_rules())
        with self.assertRaises(ValueError): score_metrics({'auto': 3}, default_rules())
        self.assertEqual(score_metrics({'auto': 0, 'teleop': 0, 'endgame': 0, 'cycles': 5, 'win': 0, 'fouls': 0}, default_rules('ppr')), 5)


class MigrationTests(unittest.TestCase):
    def test_legacy_additive_and_repeatable(self):
        engine = create_engine('sqlite:///:memory:')
        with engine.begin() as c:
            c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, hashed_password VARCHAR, theme_preference VARCHAR)'))
            c.execute(text('CREATE TABLE leagues (id INTEGER PRIMARY KEY, name VARCHAR, owner_id INTEGER, max_teams INTEGER, draft_status VARCHAR, draft_order VARCHAR, current_pick_index INTEGER)'))
            c.execute(text('CREATE TABLE rosters (id INTEGER PRIMARY KEY, user_id INTEGER, league_id INTEGER)'))
            c.execute(text("INSERT INTO users VALUES (1,'legacy','hash','default')"))
            c.execute(text("INSERT INTO leagues VALUES (1,'Keep me',1,8,'PRE_DRAFT','',0)"))
            c.execute(text('INSERT INTO rosters VALUES (1,1,1)'))
        migrate(engine); migrate(engine)
        with Session(engine) as db:
            league = db.get(League, 1)
            self.assertEqual(league.name, 'Keep me'); self.assertEqual(len(league.invite_code), 12)
            self.assertEqual(db.query(Roster).count(), 1); self.assertEqual(league.roster_size, 5)
        engine.dispose()
