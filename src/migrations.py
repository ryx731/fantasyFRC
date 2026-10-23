"""Additive SQLite upgrades. Existing accounts, leagues, picks and scores are retained."""
import secrets
import sqlite3
from pathlib import Path
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from src.database import Base

COLUMNS = {
    'users': {'is_admin': 'BOOLEAN NOT NULL DEFAULT 0'},
    'leagues': {
        'invite_code': 'VARCHAR', 'roster_size': 'INTEGER DEFAULT 5',
        'starter_count': 'INTEGER DEFAULT 3', 'regular_weeks': 'INTEGER DEFAULT 6',
        'playoff_teams': 'INTEGER DEFAULT 0', 'scoring_json': "TEXT DEFAULT '{}'",
        'scoring_active': 'BOOLEAN DEFAULT 0', 'revision': 'INTEGER DEFAULT 0',
    },
    'rosters': {'team_name': "VARCHAR DEFAULT ''", 'waiver_priority': 'INTEGER DEFAULT 1',
                'watchlist': "TEXT DEFAULT '[]'"},
}

def migrate(engine):
    # Back up a legacy file before changing its schema. Do not overwrite the backup.
    if engine.dialect.name == 'sqlite' and engine.url.database not in (None, '', ':memory:'):
        path = Path(engine.url.database).resolve()
        if path.exists() and 'leagues' in inspect(engine).get_table_names():
            columns = {c['name'] for c in inspect(engine).get_columns('leagues')}
            backup = path.with_suffix(path.suffix + '.pre-season-upgrade.bak')
            if 'invite_code' not in columns and not backup.exists():
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
                    with sqlite3.connect(backup) as destination:
                        source.backup(destination)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, fields in COLUMNS.items():
            existing = {c['name'] for c in inspect(connection).get_columns(table)}
            for name, sql in fields.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {sql}'))
        for row in connection.execute(text('SELECT id FROM leagues WHERE invite_code IS NULL')).fetchall():
            connection.execute(text('UPDATE leagues SET invite_code=:code WHERE id=:id'),
                               {'code': secrets.token_hex(6).upper(), 'id': row.id})
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_league_invite ON leagues(invite_code)'))
    # Upgrade existing drafts without deleting picks. Legacy drafts put every
    # robot in STARTER; move only excess starters to BENCH.
    from src.models import League, Period
    from src.routers.leagues import schedule
    with Session(engine) as db:
        for league in db.query(League):
            for roster in league.rosters:
                league.roster_size = max(league.roster_size, len(roster.teams))
                starters = sorted((t for t in roster.teams if t.position == 'STARTER'), key=lambda t: t.id)
                for team in starters[league.starter_count:]:
                    team.position = 'BENCH'
            if league.draft_status == 'COMPLETED' and len(league.rosters) >= 2 and not db.query(Period).filter_by(league_id=league.id).first():
                # Existing matchups cannot safely be assigned to a new scoring
                # contract; preserve them and avoid manufacturing a second schedule.
                if not league.matchups:
                    schedule(db, league)
        db.commit()
