from .models import Genre, TitleGenre


def title_to_dict(t, db=None, include_genres=True):
    d = {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "year": t.year,
        "genre": t.genre,
        "maturity_rating": t.maturity_rating,
        "rating": t.rating,
        "synopsis": t.synopsis,
        "language": getattr(t, "language", None),
        "poster": t.poster,
        "backdrop": t.backdrop,
        "video_url": t.video_url,
        "duration": t.duration,
        "top10_rank": t.top10_rank,
    }
    if include_genres and db is not None:
        rows = (
            db.query(Genre.name)
            .join(TitleGenre, TitleGenre.genre_id == Genre.id)
            .filter(TitleGenre.title_id == t.id)
            .all()
        )
        d["genres"] = [r[0] for r in rows]
    return d


def episode_to_dict(e):
    return {
        "id": e.id,
        "title_id": e.title_id,
        "season": e.season,
        "number": e.number,
        "name": e.name,
        "synopsis": e.synopsis,
        "duration": e.duration,
        "thumbnail": e.thumbnail,
    }


def profile_to_dict(p):
    return {"id": p.id, "name": p.name, "avatar": p.avatar, "is_kids": p.is_kids}
