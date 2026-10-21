import json
import secrets
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session
from src.database import get_db
from src.models import User, League, Roster, RosterTeam, Matchup, Period, Observation, Activity, Trade, Claim
from src.schemas import (LeagueCreate, DraftPick, JoinLeague, TeamName, TeamAction, Lineup,
                         TradeOffer, Decision, Message, ScoringRules, ScoreImport)
from src.auth import get_current_user
from src.scoring import default_rules, score_metrics, METRICS

router = APIRouter(prefix='/api/leagues', tags=['Fantasy leagues'])

def fail(message, status=400):
    raise HTTPException(status_code=status, detail=message)

def get_authenticated_user(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=username).first()
    if user is None:
        fail('User no longer exists', 401)
    return user

def get_league(db, league_id, write=False):
    # Serialize every league mutation before reading ownership, turn or availability.
    # SQLite takes a write lock; other SQL databases take a row lock via UPDATE.
    if write:
        db.execute(update(League).where(League.id == league_id).values(revision=League.revision + 1))
        db.expire_all()
    league = db.get(League, league_id)
    if league is None:
        fail('League not found', 404)
    return league

def member(db, league, user):
    roster = db.query(Roster).filter_by(league_id=league.id, user_id=user.id).first()
    if not roster:
        fail('Join this league to view or manage it', 403)
    return roster

def commissioner(league, user):
    if league.owner_id != user.id:
        fail('Only the commissioner can do that', 403)

def log(db, league, text, kind='TRANSACTION'):
    db.add(Activity(league_id=league.id, text=text, kind=kind))

def label(roster):
    return roster.team_name or f'{roster.user.username}’s alliance'

def rules(league):
    return json.loads(league.scoring_json or '{}') or default_rules()

def unlocked(db, league):
    if db.query(Period).filter_by(league_id=league.id, status='OPEN').first():
        fail('Lineups and transactions are locked while a scoring period is open')
    periods = db.query(Period).filter_by(league_id=league.id).all()
    if periods and all(p.status == 'FINAL' for p in periods):
        fail('This season is complete')

def held(db, league, key):
    return db.query(RosterTeam).join(Roster).filter(Roster.league_id == league.id, RosterTeam.team_key == key).first()

def replace_team(db, league, roster, add_key, drop_key=None):
    if held(db, league, add_key):
        fail('That FRC team is already rostered in this league')
    drop = next((t for t in roster.teams if t.team_key == drop_key), None)
    if drop_key and drop is None:
        fail('The drop team is no longer on your roster')
    if len(roster.teams) - bool(drop) >= league.roster_size:
        fail('Your roster is full. Choose a team to drop')
    position = drop.position if drop else ('STARTER' if sum(t.position == 'STARTER' for t in roster.teams) < league.starter_count else 'BENCH')
    if drop:
        db.delete(drop)
    db.add(RosterTeam(roster_id=roster.id, team_key=add_key, position=position))
    log(db, league, f'{label(roster)} added {add_key}' + (f' and dropped {drop_key}' if drop_key else ''))

def summary(db, league, user):
    roster = member(db, league, user)
    return {'id': league.id, 'name': league.name, 'owner_id': league.owner_id,
            'invite_code': league.invite_code, 'max_teams': league.max_teams,
            'member_count': len(league.rosters), 'draft_status': league.draft_status,
            'roster_size': league.roster_size, 'starter_count': league.starter_count,
            'regular_weeks': league.regular_weeks, 'playoff_teams': league.playoff_teams,
            'my_roster_id': roster.id, 'my_team_name': label(roster),
            'scoring': rules(league), 'scoring_active': league.scoring_active}

@router.get('')
def my_leagues(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    return [summary(db, league, user) for league in db.query(League).join(Roster).filter(Roster.user_id == user.id).order_by(League.id.desc()).all()]

@router.post('/create')
def create_league(league_data: LeagueCreate, db: Session = Depends(get_db), current_user: User = Depends(get_authenticated_user)):
    if league_data.starter_count > league_data.roster_size:
        fail('Starters cannot exceed roster size')
    if league_data.playoff_teams > league_data.max_teams:
        fail('Four-team playoffs require at least four manager slots')
    code = secrets.token_hex(6).upper()
    while db.query(League).filter_by(invite_code=code).first():
        code = secrets.token_hex(6).upper()
    league = League(name=league_data.name, owner_id=current_user.id, max_teams=league_data.max_teams,
                    invite_code=code, roster_size=league_data.roster_size, starter_count=league_data.starter_count,
                    regular_weeks=league_data.regular_weeks, playoff_teams=league_data.playoff_teams,
                    scoring_json=json.dumps(default_rules(league_data.preset)))
    db.add(league)
    db.flush()
    db.add(Roster(user_id=current_user.id, league_id=league.id, team_name=f'{current_user.username}’s alliance'))
    log(db, league, f'{current_user.username} created the league', 'LEAGUE')
    db.commit()
    return {'league_id': league.id, 'invite_code': code}

# Retained as an internal helper for older Python callers. Numeric IDs are no longer a join API.
def join_league(league_id: int, db: Session, current_user: User):
    league = get_league(db, league_id, write=True)
    if db.query(Roster).filter_by(league_id=league_id, user_id=current_user.id).first():
        fail('You are already in this league')
    if league.draft_status != 'PRE_DRAFT':
        fail('This league’s draft has already started')
    if len(league.rosters) >= league.max_teams:
        fail('This league is full')
    db.add(Roster(user_id=current_user.id, league_id=league_id, team_name=f'{current_user.username}’s alliance', waiver_priority=len(league.rosters)+1))
    log(db, league, f'{current_user.username} joined the league', 'LEAGUE')
    db.commit()
    return {'league_id': league.id}

@router.post('/join')
def join_by_code(data: JoinLeague, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = db.query(League).filter_by(invite_code=data.code.upper()).first()
    if not league:
        fail('No league matches that invite code', 404)
    return join_league(league.id, db, user)

def standings(db, league):
    rows = {r.id: {'roster_id': r.id, 'name': label(r), 'wins': 0, 'losses': 0, 'ties': 0, 'points_for': 0, 'points_against': 0} for r in league.rosters}
    for m in league.matchups:
        if not m.is_completed or m.week > league.regular_weeks:
            continue
        a, b = rows[m.roster1_id], rows[m.roster2_id]
        a['points_for'] += m.roster1_score; a['points_against'] += m.roster2_score
        b['points_for'] += m.roster2_score; b['points_against'] += m.roster1_score
        if m.roster1_score == m.roster2_score:
            a['ties'] += 1; b['ties'] += 1
        else:
            winner, loser = (a, b) if m.roster1_score > m.roster2_score else (b, a)
            winner['wins'] += 1; loser['losses'] += 1
    ordered = sorted(rows.values(), key=lambda r: (-r['wins'] - r['ties'] / 2, -r['points_for'], r['roster_id']))
    for i, row in enumerate(ordered):
        row.update(rank=i+1, points_for=round(row['points_for'], 2), points_against=round(row['points_against'], 2))
    return ordered

@router.get('/{league_id}')
def league_home(league_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id)
    result = summary(db, league, user)
    result['rosters'] = [{'id': r.id, 'user_id': r.user_id, 'manager': r.user.username, 'name': label(r), 'waiver_priority': r.waiver_priority,
                          'teams': [{'number': int(t.team_key[3:]), 'position': t.position} for t in r.teams],
                          'watchlist': json.loads(r.watchlist or '[]') if r.user_id == user.id else []} for r in league.rosters]
    result['standings'] = standings(db, league)
    periods = db.query(Period).filter_by(league_id=league_id).order_by(Period.week).all()
    result['periods'] = [{'week': p.week, 'status': p.status, 'kind': p.kind} for p in periods]
    result['matchups'] = [{'id': m.id, 'week': m.week, 'a': m.roster1_id, 'b': m.roster2_id, 'a_score': m.roster1_score, 'b_score': m.roster2_score, 'final': m.is_completed} for m in league.matchups]
    result['activity'] = [{'id': a.id, 'kind': a.kind, 'text': a.text, 'at': a.created_at.isoformat()+'Z'} for a in db.query(Activity).filter_by(league_id=league_id).order_by(Activity.id.desc()).limit(100)]
    result['trades'] = [{'id': t.id, 'sender_id': t.sender_id, 'receiver_id': t.receiver_id, 'give_key': t.give_key, 'receive_key': t.receive_key, 'status': t.status} for t in db.query(Trade).filter_by(league_id=league_id).order_by(Trade.id.desc()).limit(100)]
    result['claims'] = [{'id': c.id, 'add_key': c.add_key, 'drop_key': c.drop_key, 'status': c.status} for c in db.query(Claim).filter_by(league_id=league_id, roster_id=result['my_roster_id']).order_by(Claim.id.desc()).limit(100)]
    result['draft'] = get_draft_state(league_id, db, user)
    return result

@router.post('/{league_id}/invite/rotate')
def rotate_invite(league_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    league.invite_code = secrets.token_hex(6).upper()
    log(db, league, 'Commissioner rotated the invite code', 'LEAGUE'); db.commit()
    return {'invite_code': league.invite_code}

@router.post('/{league_id}/team-name')
def rename_team(league_id: int, data: TeamName, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user)
    roster.team_name = data.name; db.commit()
    return {'message': 'Team name saved'}

@router.post('/{league_id}/lineup')
def save_lineup(league_id: int, data: Lineup, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user); unlocked(db, league)
    keys = {f'frc{n}' for n in data.starters}
    if len(keys) != len(data.starters) or len(keys) > league.starter_count:
        fail('Choose unique starters within the starter limit')
    if not keys.issubset({t.team_key for t in roster.teams}):
        fail('Starters must be on your roster')
    for team in roster.teams:
        team.position = 'STARTER' if team.team_key in keys else 'BENCH'
    log(db, league, f'{label(roster)} updated their lineup'); db.commit()
    return {'message': 'Lineup saved'}

@router.post('/{league_id}/watchlist')
def toggle_watch(league_id: int, data: TeamAction, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user)
    numbers = json.loads(roster.watchlist or '[]')
    if data.team_number in numbers:
        numbers.remove(data.team_number)
    elif len(numbers) < 100:
        numbers.append(data.team_number)
    else:
        fail('Watchlist limit is 100 teams')
    roster.watchlist = json.dumps(numbers); db.commit()
    return {'message': 'Watchlist updated'}

@router.post('/{league_id}/draft/start')
def start_draft(league_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    if league.draft_status != 'PRE_DRAFT': fail('The draft has already started')
    rosters = sorted(league.rosters, key=lambda r: r.id)
    if len(rosters) < max(2, league.playoff_teams): fail('Invite more managers before starting')
    order = [r.user_id for r in rosters]; secrets.SystemRandom().shuffle(order)
    sequence = [uid for rnd in range(league.roster_size) for uid in (order if rnd % 2 == 0 else order[::-1])]
    league.draft_order = ','.join(map(str, sequence)); league.current_pick_index = 0; league.draft_status = 'ACTIVE'
    for i, uid in enumerate(reversed(order)):
        next(r for r in rosters if r.user_id == uid).waiver_priority = i+1
    log(db, league, 'The snake draft started. Waivers use reverse first-round order.', 'DRAFT'); db.commit()
    return {'message': 'Draft started'}

@router.get('/{league_id}/draft_state')
def get_draft_state(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id); member(db, league, current_user)
    sequence = [int(uid) for uid in league.draft_order.split(',') if uid]
    picker = sequence[league.current_pick_index] if league.draft_status == 'ACTIVE' and league.current_pick_index < len(sequence) else None
    return {'status': league.draft_status, 'current_pick_index': league.current_pick_index, 'total_picks': len(sequence),
            'current_picker_id': picker, 'current_picker_name': db.get(User, picker).username if picker else 'None',
            'sequence': sequence}

@router.post('/draft')
def draft_team(pick: DraftPick, db: Session = Depends(get_db), current_user: User = Depends(get_authenticated_user)):
    league = get_league(db, pick.league_id, True); roster = member(db, league, current_user)
    if league.draft_status != 'ACTIVE': fail('Draft is not active')
    sequence = league.draft_order.split(',') if league.draft_order else []
    if not 0 <= league.current_pick_index < len(sequence): fail('Draft has no remaining picks')
    if str(current_user.id) != sequence[league.current_pick_index]: fail('It is not your turn')
    replace_team(db, league, roster, f'frc{pick.team_number}')
    league.current_pick_index += 1
    log(db, league, f'Pick {league.current_pick_index}: {label(roster)} drafted frc{pick.team_number}', 'DRAFT')
    if league.current_pick_index >= len(sequence):
        league.draft_status = 'COMPLETED'; schedule(db, league)
    db.commit()
    return {'message': f'Drafted team {pick.team_number}'}

def schedule(db, league):
    ids = sorted(r.id for r in league.rosters)
    if len(ids) % 2: ids.append(None)
    rounds = []
    for _ in range(len(ids)-1):
        rounds.append([(ids[i], ids[-i-1]) for i in range(len(ids)//2) if ids[i] and ids[-i-1]])
        ids = [ids[0], ids[-1]] + ids[1:-1]
    for week in range(1, league.regular_weeks+1):
        db.add(Period(league_id=league.id, week=week))
        for a, b in rounds[(week-1) % len(rounds)]:
            db.add(Matchup(league_id=league.id, week=week, roster1_id=a, roster2_id=b))
    log(db, league, 'Draft completed. The regular-season schedule is ready.', 'LEAGUE')

@router.post('/{league_id}/draft/commissioner-pick')
def commissioner_pick(league_id: int, data: TeamAction, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    sequence = league.draft_order.split(',') if league.draft_order else []
    if league.draft_status != 'ACTIVE' or not 0 <= league.current_pick_index < len(sequence):
        fail('No active draft turn')
    picker = db.get(User, int(sequence[league.current_pick_index]))
    log(db, league, f'Commissioner {user.username} submitted a proxy pick for {picker.username}: frc{data.team_number}', 'DRAFT')
    return draft_team(DraftPick(league_id=league_id, team_number=data.team_number), db, picker)

@router.post('/{league_id}/claims')
def create_claim(league_id: int, data: TeamAction, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user); unlocked(db, league)
    if league.draft_status != 'COMPLETED': fail('Waivers open after the draft')
    key = f'frc{data.team_number}'; drop = f'frc{data.drop_team_number}' if data.drop_team_number else None
    if held(db, league, key): fail('That team is already rostered')
    if drop and not any(t.team_key == drop for t in roster.teams): fail('Choose a drop from your roster')
    if len(roster.teams) >= league.roster_size and not drop: fail('Your roster is full; choose a drop')
    if db.query(Claim).filter_by(league_id=league_id, roster_id=roster.id, add_key=key, status='PENDING').first(): fail('You already have a pending claim for this team')
    db.add(Claim(league_id=league_id, roster_id=roster.id, add_key=key, drop_key=drop)); db.commit()
    return {'message': 'Claim submitted; the commissioner processes waivers between periods'}

@router.post('/{league_id}/claims/{claim_id}/cancel')
def cancel_claim(league_id: int, claim_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user)
    claim = db.get(Claim, claim_id)
    if not claim or claim.league_id != league_id or claim.roster_id != roster.id: fail('Claim not found', 404)
    if claim.status != 'PENDING': fail('Claim already processed')
    claim.status = 'CANCELLED'; db.commit(); return {'message': 'Claim cancelled'}

@router.post('/{league_id}/waivers/process')
def process_waivers(league_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user); unlocked(db, league)
    pending = db.query(Claim).filter_by(league_id=league_id, status='PENDING').all()
    count = 0
    while pending:
        claim = min(pending, key=lambda c: (db.get(Roster, c.roster_id).waiver_priority, c.id)); pending.remove(claim)
        roster = db.get(Roster, claim.roster_id)
        try:
            replace_team(db, league, roster, claim.add_key, claim.drop_key)
        except HTTPException as error:
            claim.status = 'FAILED'; log(db, league, f'Waiver for {label(roster)}: {error.detail}')
        else:
            claim.status = 'SUCCESS'; count += 1
            roster.waiver_priority = max(r.waiver_priority for r in league.rosters)+1
        db.flush(); db.expire_all()
    # Normalize the rolling order without changing its relative priority.
    for i, roster in enumerate(sorted(league.rosters, key=lambda r: (r.waiver_priority, r.id))): roster.waiver_priority = i+1
    db.commit(); return {'message': f'Processed waivers: {count} successful'}

@router.post('/{league_id}/drop')
def drop_team(league_id: int, data: TeamAction, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user); unlocked(db, league)
    if league.draft_status != 'COMPLETED': fail('Wait until the draft is complete')
    team = next((t for t in roster.teams if t.team_key == f'frc{data.team_number}'), None)
    if not team: fail('Team is not on your roster')
    db.delete(team); log(db, league, f'{label(roster)} dropped frc{data.team_number}'); db.commit()
    return {'message': 'Team dropped. Fill the open spot through waivers.'}

@router.post('/{league_id}/trades')
def propose_trade(league_id: int, data: TradeOffer, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); sender = member(db, league, user); unlocked(db, league)
    if league.draft_status != 'COMPLETED': fail('Trades open after the draft')
    receiver = db.get(Roster, data.receiver_id)
    if not receiver or receiver.league_id != league_id or receiver.id == sender.id: fail('Choose another manager in this league')
    give = f'frc{data.give_number}'; receive = f'frc{data.receive_number}'
    if not any(t.team_key == give for t in sender.teams) or not any(t.team_key == receive for t in receiver.teams): fail('Both teams must be on the specified rosters')
    db.add(Trade(league_id=league_id, sender_id=sender.id, receiver_id=receiver.id, give_key=give, receive_key=receive))
    log(db, league, f'{label(sender)} offered {give} for {receive} to {label(receiver)}', 'TRADE'); db.commit()
    return {'message': 'Trade offered'}

@router.post('/{league_id}/trades/{trade_id}')
def decide_trade(league_id: int, trade_id: int, data: Decision, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); roster = member(db, league, user)
    trade = db.get(Trade, trade_id)
    if not trade or trade.league_id != league_id: fail('Trade not found', 404)
    if trade.status != 'PENDING': fail('Trade is no longer pending')
    if data.action == 'cancel':
        if roster.id != trade.sender_id: fail('Only the sender can cancel', 403)
        trade.status = 'CANCELLED'
    else:
        if roster.id != trade.receiver_id: fail('Only the receiving manager can respond', 403)
        if data.action == 'decline': trade.status = 'DECLINED'
        else:
            unlocked(db, league)
            give = held(db, league, trade.give_key); receive = held(db, league, trade.receive_key)
            if not give or not receive or give.roster_id != trade.sender_id or receive.roster_id != trade.receiver_id:
                fail('Rosters changed. Decline this offer and create a new trade')
            give.roster_id, receive.roster_id = receive.roster_id, give.roster_id
            give.position, receive.position = receive.position, give.position
            trade.status = 'ACCEPTED'
    log(db, league, f'Trade #{trade.id} {trade.status.lower()}', 'TRADE'); db.commit()
    return {'message': 'Trade updated'}

@router.post('/{league_id}/messages')
def post_message(league_id: int, data: Message, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); member(db, league, user)
    log(db, league, f'{user.username}: {data.text}', 'MESSAGE'); db.commit()
    return {'message': 'Message posted'}

@router.post('/{league_id}/scoring')
def set_scoring(league_id: int, data: ScoringRules, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    if db.query(Period).filter(Period.league_id == league_id, Period.status != 'SCHEDULED').first(): fail('Scoring rules freeze when the first period opens')
    if set(data.weights) != set(METRICS): fail('Provide all six metric weights: ' + ', '.join(METRICS))
    league.scoring_json = json.dumps({'version': data.version, 'preset': 'custom', 'aggregation': data.aggregation, 'weights': data.weights})
    league.scoring_active = data.active
    log(db, league, f'Scoring rules updated to {data.version}; ' + ('activated' if data.active else 'provisional'), 'SCORING'); db.commit()
    return {'message': 'Scoring configuration saved'}

@router.post('/{league_id}/periods/{week}/open')
def open_period(league_id: int, week: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    if league.draft_status != 'COMPLETED': fail('Complete the draft first')
    if not league.scoring_active: fail('Configure and activate the season scoring rules first')
    period = db.query(Period).filter_by(league_id=league_id, week=week).first()
    if not period or period.status != 'SCHEDULED': fail('That period is not scheduled')
    if db.query(Period).filter(Period.league_id == league_id, Period.week < week, Period.status != 'FINAL').first(): fail('Finalize earlier periods first')
    if db.query(Period).filter_by(league_id=league_id, status='OPEN').first(): fail('Another period is open')
    period.lineups_json = json.dumps({str(r.id): [t.team_key for t in r.teams if t.position == 'STARTER'] for r in league.rosters})
    period.status = 'OPEN'; log(db, league, f'Period {week} opened. Starter lineups are frozen.', 'SCORING'); db.commit()
    return {'message': 'Period opened; all lineups and transactions are locked'}

def recalculate(db, league, period):
    totals = defaultdict(list)
    for record in db.query(Observation).filter_by(league_id=league.id, week=period.week): totals[record.team_key].append(record.points)
    robot_points = {k: (sum(v)/len(v) if rules(league)['aggregation'] == 'average' else sum(v)) for k, v in totals.items()}
    lineup = json.loads(period.lineups_json)
    scores = {int(rid): round(sum(robot_points.get(k, 0) for k in keys), 2) for rid, keys in lineup.items()}
    for matchup in db.query(Matchup).filter_by(league_id=league.id, week=period.week):
        matchup.roster1_score = scores.get(matchup.roster1_id, 0); matchup.roster2_score = scores.get(matchup.roster2_id, 0)

@router.post('/{league_id}/periods/{week}/import')
def import_scores(league_id: int, week: int, data: ScoreImport, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    period = db.query(Period).filter_by(league_id=league_id, week=week).first()
    if not period or period.status != 'OPEN': fail('Import scores into an open period')
    config = rules(league)
    if data.rules_version != config['version']: fail('Import rules_version does not match this league')
    prepared = []; seen = set()
    for record in data.records:
        key = f'frc{record.team_number}'; identity = (record.match_key, key)
        if identity in seen: fail('Duplicate match/team within this import')
        if db.query(Observation).filter(Observation.league_id == league_id, Observation.week != week,
                                       Observation.match_key == record.match_key, Observation.team_key == key).first():
            fail('This robot match already belongs to another period')
        seen.add(identity)
        try: points = score_metrics(record.metrics, config)
        except ValueError as error: fail(str(error))
        prepared.append((record, key, points))
    for record, key, points in prepared:
        item = db.query(Observation).filter_by(league_id=league_id, week=week, match_key=record.match_key, team_key=key).first()
        if item is None:
            item = Observation(league_id=league_id, week=week, match_key=record.match_key, team_key=key); db.add(item)
        item.metrics_json = json.dumps(record.metrics); item.points = points
        db.flush()
    recalculate(db, league, period)
    log(db, league, f'Period {week}: imported {len(prepared)} robot match records using {config["version"]}', 'SCORING'); db.commit()
    return {'message': f'Imported {len(prepared)} records; scores updated'}

@router.get('/{league_id}/periods/{week}/scores')
def score_details(league_id: int, week: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id); member(db, league, user)
    return [{'id': o.id, 'match_key': o.match_key, 'team_number': int(o.team_key[3:]), 'metrics': json.loads(o.metrics_json), 'points': o.points} for o in db.query(Observation).filter_by(league_id=league_id, week=week).order_by(Observation.match_key, Observation.team_key)]

@router.delete('/{league_id}/periods/{week}/scores/{record_id}')
def remove_score(league_id: int, week: int, record_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    period = db.query(Period).filter_by(league_id=league_id, week=week).first()
    record = db.get(Observation, record_id)
    if not record or record.league_id != league_id or record.week != week: fail('Record not found', 404)
    if not period or period.status != 'OPEN': fail('Only records in an open period can be removed')
    log(db, league, f'Period {week}: removed incorrect match record {record.match_key} / {record.team_key}', 'SCORING')
    db.delete(record); db.flush(); recalculate(db, league, period); db.commit()
    return {'message': 'Incorrect record removed; scores recalculated'}

@router.post('/{league_id}/periods/{week}/finalize')
def finalize_period(league_id: int, week: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    league = get_league(db, league_id, True); commissioner(league, user)
    period = db.query(Period).filter_by(league_id=league_id, week=week).first()
    if not period or period.status != 'OPEN': fail('Only an open period can be finalized')
    if not db.query(Observation).filter_by(league_id=league_id, week=week).first(): fail('Import played-match records before finalizing')
    recalculate(db, league, period)
    matches = db.query(Matchup).filter_by(league_id=league_id, week=week).all()
    for m in matches: m.is_completed = True
    period.status = 'FINAL'; db.flush()
    if league.playoff_teams == 4:
        if week == league.regular_weeks:
            seeds = [r['roster_id'] for r in standings(db, league)[:4]]
            db.add(Period(league_id=league_id, week=week+1, kind='SEMIFINAL'))
            for a, b in [(seeds[0], seeds[3]), (seeds[1], seeds[2])]: db.add(Matchup(league_id=league_id, week=week+1, roster1_id=a, roster2_id=b))
        elif period.kind == 'SEMIFINAL':
            ranks = {r['roster_id']: r['rank'] for r in standings(db, league)}
            winners = [m.roster1_id if m.roster1_score > m.roster2_score or (m.roster1_score == m.roster2_score and ranks[m.roster1_id] < ranks[m.roster2_id]) else m.roster2_id for m in matches]
            db.add(Period(league_id=league_id, week=week+1, kind='FINAL'))
            db.add(Matchup(league_id=league_id, week=week+1, roster1_id=winners[0], roster2_id=winners[1]))
    log(db, league, f'Period {week} finalized. Scores are now immutable.', 'SCORING'); db.commit()
    return {'message': 'Period finalized'}
