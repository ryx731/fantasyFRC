from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    theme_preference = Column(String, default="default")
    is_admin = Column(Boolean, default=False, nullable=False)

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
    invite_code = Column(String, unique=True, nullable=True)
    roster_size = Column(Integer, default=5)
    starter_count = Column(Integer, default=3)
    regular_weeks = Column(Integer, default=6)
    playoff_teams = Column(Integer, default=0)
    scoring_json = Column(Text, default="{}")
    scoring_active = Column(Boolean, default=False)
    revision = Column(Integer, default=0)

    owner = relationship("User", back_populates="leagues_owned")
    rosters = relationship("Roster", back_populates="league")
    matchups = relationship("Matchup", back_populates="league")


class Roster(Base):
    __tablename__ = "rosters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    league_id = Column(Integer, ForeignKey("leagues.id"))
    team_name = Column(String, default="")
    waiver_priority = Column(Integer, default=1)
    watchlist = Column(Text, default="[]")

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


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (UniqueConstraint("league_id", "week"),)
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    week = Column(Integer, nullable=False)
    status = Column(String, default="SCHEDULED")
    kind = Column(String, default="REGULAR")
    lineups_json = Column(Text, default="{}")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("league_id", "week", "match_key", "team_key"),)
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    week = Column(Integer, nullable=False)
    match_key = Column(String, nullable=False)
    team_key = Column(String, nullable=False)
    metrics_json = Column(Text, nullable=False)
    points = Column(Float, default=0)


class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    kind = Column(String, default="TRANSACTION")
    text = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("rosters.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("rosters.id"), nullable=False)
    give_key = Column(String, nullable=False)
    receive_key = Column(String, nullable=False)
    status = Column(String, default="PENDING")


class Claim(Base):
    __tablename__ = "claims"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    roster_id = Column(Integer, ForeignKey("rosters.id"), nullable=False)
    add_key = Column(String, nullable=False)
    drop_key = Column(String, nullable=True)
    status = Column(String, default="PENDING")
