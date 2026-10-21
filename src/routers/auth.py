import os
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests

from src.database import get_db
from src.models import User
from src.auth import get_password_hash, verify_password, create_access_token
from src.schemas import UserAuth

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class GoogleToken(BaseModel):
    credential: str


def auth_response(user: User) -> dict:
    return {
        "access_token": create_access_token(data={"sub": user.username}),
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.username,
    }


@router.post("/register")
def register_user(auth_data: UserAuth, db: Session = Depends(get_db)):
    # Check if user already exists
    existing_user = db.query(User).filter(User.username == auth_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Hash password and create user
    hashed_pw = get_password_hash(auth_data.password)
    new_user = User(username=auth_data.username, hashed_password=hashed_pw)

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Username already exists") from None

    return auth_response(new_user)


@router.post("/login")
def login_user(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return auth_response(user)


@router.post("/google")
def google_auth(token: GoogleToken, db: Session = Depends(get_db)):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        info = id_token.verify_oauth2_token(token.credential, requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token") from None
    if not info.get("email_verified") or not info.get("email"):
        raise HTTPException(status_code=401, detail="A verified Google email is required")

    # Use the full verified email, avoiding collisions between email local parts.
    # Never attach a Google identity to an existing password account automatically.
    username = info["email"]
    user = db.query(User).filter(User.username == username).first()
    if user and user.hashed_password != "!google":
        raise HTTPException(status_code=409, detail="Use your password to sign in to this account")
    if not user:
        user = User(username=username, hashed_password="!google")
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Account already exists. Please sign in again") from None
    return auth_response(user)

@router.get('/config')
def auth_config():
    return {'google_client_id': GOOGLE_CLIENT_ID}
