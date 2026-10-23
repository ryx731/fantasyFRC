"""Regression checks for boolean defaults in legacy deployment upgrades."""
import re
import unittest

from sqlalchemy import create_engine, event, false, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from src.migrations import COLUMNS, migrate
from src.models import League, User


class PortableMigrationTests(unittest.TestCase):
    def test_boolean_defaults_use_postgresql_literals(self):
        # Check every added boolean, not just the admin column that failed on Render.
        postgres_false = str(false().compile(dialect=postgresql.dialect())).upper()
        for table, columns in COLUMNS.items():
            for name, definition in columns.items():
                if definition.startswith('BOOLEAN'):
                    with self.subTest(table=table, column=name):
                        default = re.search(r'\bDEFAULT\s+(\S+)', definition)
                        self.assertIsNotNone(default)
                        self.assertEqual(default.group(1), postgres_false)

    def test_legacy_boolean_upgrade_keeps_data_and_is_repeatable(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, hashed_password VARCHAR, theme_preference VARCHAR)'))
            connection.execute(text('CREATE TABLE leagues (id INTEGER PRIMARY KEY, name VARCHAR, owner_id INTEGER, max_teams INTEGER, draft_status VARCHAR, draft_order VARCHAR, current_pick_index INTEGER)'))
            connection.execute(text("INSERT INTO users VALUES (1, 'keep-account', 'keep-hash', 'orbit')"))
            connection.execute(text("INSERT INTO leagues VALUES (1, 'Keep league', 1, 8, 'PRE_DRAFT', '', 0)"))

        statements = []
        event.listen(engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: statements.append(statement))
        migrate(engine)
        self.assertTrue(any('ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE' in sql for sql in statements))
        self.assertTrue(any('ADD COLUMN scoring_active BOOLEAN DEFAULT FALSE' in sql for sql in statements))
        with Session(engine) as db:
            user, league = db.get(User, 1), db.get(League, 1)
            self.assertFalse(user.is_admin)
            self.assertFalse(league.scoring_active)
            self.assertEqual(user.hashed_password, 'keep-hash')
            self.assertEqual(user.theme_preference, 'orbit')
            self.assertEqual(league.name, 'Keep league')
            user.is_admin = True
            league.scoring_active = True
            db.commit()

        migrate(engine)
        with Session(engine) as db:
            self.assertTrue(db.get(User, 1).is_admin)
            self.assertTrue(db.get(League, 1).scoring_active)
