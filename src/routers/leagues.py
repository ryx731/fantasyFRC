from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.database import get_db
from src.models import User, League, Roster, RosterTeam, Matchup
from src.schemas import LeagueCreate, DraftPick
from src.auth import get_current_user
import random

router = APIRouter(prefix="/api/leagues", tags=["Leagues & Draft"])


@router.post("/create")
def create_league(
        league_data: LeagueCreate,
        db: Session = Depends(get_db),
        current_username: str = Depends(get_current_user)
):
    # Get user from database
    current_user = db.query(User).filter(User.username == current_username).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    league = League(name=league_data.name, owner_id=current_user.id, max_teams=league_data.max_teams)
    db.add(league)
    db.commit()
    db.refresh(league)

    roster = Roster(user_id=current_user.id, league_id=league.id)
    db.add(roster)
    db.commit()
    return {"message": "League created!", "league_id": league.id}


@router.post("/{league_id}/join")
def join_league(
        league_id: int,
        db: Session = Depends(get_db),
        current_username: str = Depends(get_current_user)
):
    # Get user from database
    current_user = db.query(User).filter(User.username == current_username).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(Roster).filter(
        Roster.league_id == league_id,
        Roster.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You are already in this league")

    db.add(Roster(user_id=current_user.id, league_id=league_id))
    db.commit()
    return {"message": "Successfully joined league!"}


@router.get("/{league_id}/draft_state")
def get_draft_state(
        league_id: int,
        db: Session = Depends(get_db),
        current_username: str = Depends(get_current_user)
):
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    draft_seq = league.draft_order.split(",") if league.draft_order else []
    current_picker_id = int(
        draft_seq[league.current_pick_index]
    ) if league.draft_status == "ACTIVE" and league.current_pick_index < len(draft_seq) else None

    current_picker_name = "None"
    if current_picker_id:
        u = db.query(User).filter(User.id == current_picker_id).first()
        if u:
            current_picker_name = u.username

    return {
        "status": league.draft_status,
        "current_pick_index": league.current_pick_index,
        "total_picks": len(draft_seq),
        "current_picker_name": current_picker_name
    }


@router.post("/draft")
def draft_team(
        pick: DraftPick,
        db: Session = Depends(get_db),
        current_username: str = Depends(get_current_user)
):
    # Get user from database
    current_user = db.query(User).filter(User.username == current_username).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    league = db.query(League).filter(League.id == pick.league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    if league.draft_status != "ACTIVE":
        raise HTTPException(status_code=400, detail="Draft is not active")

    draft_sequence = league.draft_order.split(",")
    if not draft_sequence or current_user.id != int(draft_sequence[league.current_pick_index]):
        raise HTTPException(status_code=400, detail="It is not your turn!")

    roster = db.query(Roster).filter(
        Roster.league_id == pick.league_id,
        Roster.user_id == current_user.id
    ).first()

    if not roster:
        raise HTTPException(status_code=404, detail="You are not in this league")

    team_key = f"frc{pick.team_number}"

    # Check if team already drafted
    if db.query(RosterTeam).join(Roster).filter(
            Roster.league_id == pick.league_id,
            RosterTeam.team_key == team_key
    ).first():
        raise HTTPException(status_code=400, detail=f"Team {pick.team_number} already drafted!")

    db.add(RosterTeam(roster_id=roster.id, team_key=team_key, position="STARTER"))
    league.current_pick_index += 1
    if league.current_pick_index >= len(draft_sequence):
        league.draft_status = "COMPLETED"

    db.commit()
    return {"message": f"Drafted Team {pick.team_number}!"}