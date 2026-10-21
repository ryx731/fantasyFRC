from typing import Optional, Literal
from pydantic import BaseModel, Field, constr, conlist, confloat

Name = constr(strip_whitespace=True, min_length=1, max_length=100)
class UserAuth(BaseModel):
    username: constr(strip_whitespace=True, min_length=1, max_length=50)
    password: constr(min_length=1, max_length=256)
class LeagueCreate(BaseModel):
    name: Name
    owner_id: Optional[int] = None
    max_teams: int = Field(8, ge=2, le=32)
    roster_size: int = Field(5, ge=1, le=12)
    starter_count: int = Field(3, ge=1, le=12)
    regular_weeks: int = Field(6, ge=1, le=12)
    playoff_teams: Literal[0, 4] = 0
    preset: Literal['standard', 'half_ppr', 'ppr'] = 'standard'
class JoinLeague(BaseModel):
    code: constr(strip_whitespace=True, min_length=12, max_length=12, regex=r'^[a-fA-F0-9]{12}$')
class DraftPick(BaseModel):
    league_id: int = Field(gt=0)
    user_id: Optional[int] = None
    team_number: int = Field(gt=0, le=999999)
class TeamName(BaseModel):
    name: Name
class TeamAction(BaseModel):
    team_number: int = Field(gt=0, le=999999)
    drop_team_number: Optional[int] = Field(None, gt=0, le=999999)
class Lineup(BaseModel):
    starters: conlist(int, max_items=12)
class TradeOffer(BaseModel):
    receiver_id: int = Field(gt=0)
    give_number: int = Field(gt=0, le=999999)
    receive_number: int = Field(gt=0, le=999999)
class Decision(BaseModel):
    action: Literal['accept', 'decline', 'cancel']
class Message(BaseModel):
    text: constr(strip_whitespace=True, min_length=1, max_length=1000)
class ScoringRules(BaseModel):
    version: constr(strip_whitespace=True, min_length=1, max_length=80)
    aggregation: Literal['average', 'sum'] = 'average'
    weights: dict[str, confloat(ge=-100, le=100, allow_inf_nan=False)]
    active: bool = False
class MatchRecord(BaseModel):
    match_key: constr(strip_whitespace=True, min_length=1, max_length=100)
    team_number: int = Field(gt=0, le=999999)
    metrics: dict[str, confloat(ge=0, allow_inf_nan=False)]
class ScoreImport(BaseModel):
    rules_version: constr(min_length=1, max_length=80)
    records: conlist(MatchRecord, min_items=1, max_items=5000)
class WaiverClaim(BaseModel):
    league_id: int = Field(gt=0)
    user_id: Optional[int] = None
    add_team_number: int = Field(gt=0)
    drop_team_number: Optional[int] = Field(None, gt=0)
