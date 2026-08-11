from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from src.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    theme_preference = Column(String, default="default")

    leagues_owned = relationship("League", back_populates="owner")
    rosters = relationship("Roster", back_populates="user")


class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    max_teams = Column(Integer, default=8)

    # Draft State Management
    draft_status = Column(String, default="PRE_DRAFT")  # PRE_DRAFT, ACTIVE, COMPLETED
    draft_order = Column(String, default="")  # Comma-separated user_ids
    current_pick_index = Column(Integer, default=0)

    owner = relationship("User", back_populates="leagues_owned")
    rosters = relationship("Roster", back_populates="league")
    matchups = relationship("Matchup", back_populates="league")


class Roster(Base):
    __tablename__ = "rosters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    league_id = Column(Integer, ForeignKey("leagues.id"))

    user = relationship("User", back_populates="rosters")
    league = relationship("League", back_populates="rosters")
    teams = relationship("RosterTeam", back_populates="roster", cascade="all, delete-orphan")


class RosterTeam(Base):
    __tablename__ = "roster_teams"

    id = Column(Integer, primary_key=True, index=True)
    roster_id = Column(Integer, ForeignKey("rosters.id"))
    team_key = Column(String, nullable=False)
    position = Column(String, default="STARTER")

    roster = relationship("Roster", back_populates="teams")


class Matchup(Base):
    __tablename__ = "matchups"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    week = Column(Integer, nullable=False)

    roster1_id = Column(Integer, ForeignKey("rosters.id"))
    roster2_id = Column(Integer, ForeignKey("rosters.id"))

    roster1_score = Column(Float, default=0.0)
    roster2_score = Column(Float, default=0.0)
    is_completed = Column(Boolean, default=False)

    league = relationship("League", back_populates="matchups")