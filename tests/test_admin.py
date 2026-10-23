import unittest

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.auth import verify_password
from src.database import Base
from src.manage_admin import provision_admin
from src.migrations import migrate
from src.models import User
from src.routers import admin, auth
from src.schemas import UserAuth


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_provision_login_and_role_refresh(self):
        user = provision_admin(self.db, 'admin', 'test-administrator-password')
        self.assertTrue(user.is_admin)
        self.assertNotEqual(user.hashed_password, 'test-administrator-password')
        self.assertTrue(verify_password('test-administrator-password', user.hashed_password))
        result = auth.login_user(OAuth2PasswordRequestForm(username='admin', password='test-administrator-password'), self.db)
        self.assertTrue(result['is_admin'])
        self.assertTrue(auth.current_account('admin', self.db)['is_admin'])
        self.assertEqual(admin.require_admin(user), user)
        self.assertNotIn('hashed_password', admin.overview(self.db, user)['users'][0])
        provision_admin(self.db, 'admin', 'replacement-test-password')
        self.assertEqual(self.db.query(User).count(), 1)

    def test_registration_cannot_grant_admin_and_revocation_is_immediate(self):
        result = auth.register_user(UserAuth(username='manager', password='manager-password', is_admin=True), self.db)
        self.assertFalse(result['is_admin'])
        user = self.db.query(User).one()
        with self.assertRaises(HTTPException) as error:
            admin.require_admin(user)
        self.assertEqual(error.exception.status_code, 403)
        user.is_admin = True
        self.db.commit()
        self.assertEqual(admin.require_admin(user), user)
        user.is_admin = False
        self.db.commit()
        with self.assertRaises(HTTPException):
            admin.require_admin(user)

    def test_legacy_accounts_remain_non_admin(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, hashed_password VARCHAR, theme_preference VARCHAR)'))
            connection.execute(text("INSERT INTO users VALUES (1, 'legacy', '!google', 'default')"))
        migrate(self.engine)
        migrate(self.engine)
        self.db = Session(self.engine)
        self.assertFalse(self.db.get(User, 1).is_admin)


if __name__ == '__main__':
    unittest.main()
