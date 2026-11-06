from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Genre, Title, TitleGenre
from ..serializers import title_to_dict

router = APIRouter(prefix="/api/genres", tags=["genres"])


@router.get("")
def list_genres(db: Session = Depends(get_db), user=Depends(get_current_user)):
    genres = db.query(Genre).order_by(Genre.id.asc()).all()
    return [{"id": g.id, "name": g.name} for g in genres]


@router.get("/{genre_id}/titles")
def titles_by_genre(genre_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    genre = db.query(Genre).filter(Genre.id == genre_id).first()
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    titles = (
        db.query(Title)
        .join(TitleGenre, TitleGenre.title_id == Title.id)
        .filter(TitleGenre.genre_id == genre_id)
        .order_by(Title.id.asc())
        .all()
    )
    return [title_to_dict(t, db) for t in titles]
