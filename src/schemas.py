from pydantic import BaseModel
from typing import List, Optional

class UserAuth(BaseModel):
    username: str
    password: str

class LeagueCreate(BaseModel):
    name: str
    owner_id: int
    max_teams: Optional[int] = 8

class DraftPick(BaseModel):
    league_id: int
    user_id: int
    team_number: int

class WaiverClaim(BaseModel):
    league_id: int
    user_id: int
    add_team_number: int
    drop_team_number: int