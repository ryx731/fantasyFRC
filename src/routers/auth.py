import os
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    access_token = create_access_token(data={"sub": new_user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_user.id,
        "username": new_user.username
    }


@router.post("/login")
def login_user(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "username": user.username}


@router.post("/google")
def google_auth(token: GoogleToken, db: Session = Depends(get_db)):
    try:
        idinfo = id_token.verify_oauth2_token(token.credential, requests.Request(), GOOGLE_CLIENT_ID)
        email = idinfo['email']
        username = email.split('@')[0]

        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(username=username, hashed_password=get_password_hash("google_oauth_dummy"))
            db.add(user)
            db.commit()
            db.refresh(user)

        access_token = create_access_token(data={"sub": user.username})
        return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "username": user.username}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google Token")