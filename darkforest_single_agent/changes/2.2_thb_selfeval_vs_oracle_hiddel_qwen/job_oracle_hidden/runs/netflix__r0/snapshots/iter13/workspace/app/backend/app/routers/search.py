from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Title
from ..serializers import title_to_dict

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str | None = Query(None),
    genre: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Title)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Title.name.ilike(like), Title.genre.ilike(like)))
    if genre:
        query = query.filter(Title.genre.ilike(genre))
    titles = query.order_by(Title.rating.desc().nullslast(), Title.id.asc()).limit(50).all()
    return {"items": [title_to_dict(t, db) for t in titles]}
