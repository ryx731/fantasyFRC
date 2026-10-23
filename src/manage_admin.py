"""Provision an administrator locally: python -m src.manage_admin [username]."""
import argparse
from getpass import getpass

from sqlalchemy.orm import Session

from src.auth import get_password_hash
from src.database import engine
from src.migrations import migrate
from src.models import User
from src.schemas import UserAuth


def provision_admin(db, username, password):
    credentials = UserAuth(username=username, password=password)
    user = db.query(User).filter_by(username=credentials.username).first()
    if user is None:
        user = User(username=credentials.username)
        db.add(user)
    user.hashed_password = get_password_hash(credentials.password)
    user.is_admin = True
    db.commit()
    return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('username', nargs='?', default='admin')
    args = parser.parse_args()
    password = getpass('Administrator password: ')
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match')
    migrate(engine)
    with Session(engine) as db:
        user = provision_admin(db, args.username, password)
        print(f'Administrator account ready: {user.username}')


if __name__ == '__main__':
    main()
