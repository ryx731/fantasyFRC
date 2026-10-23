"""Administrator-only site overview. Authorization always comes from the database."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import User, League
from src.routers.leagues import get_authenticated_user

router = APIRouter(prefix='/api/admin', tags=['Administration'])


def require_admin(user: User = Depends(get_authenticated_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail='Administrator access required')
    return user


@router.get('/overview')
def overview(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return {
        'users': [{'id': u.id, 'username': u.username, 'is_admin': bool(u.is_admin)}
                  for u in db.query(User).order_by(User.id)],
        'leagues': [{'id': l.id, 'name': l.name, 'commissioner': l.owner.username if l.owner else 'Unknown',
                     'member_count': len(l.rosters), 'draft_status': l.draft_status}
                    for l in db.query(League).order_by(League.id)],
    }
