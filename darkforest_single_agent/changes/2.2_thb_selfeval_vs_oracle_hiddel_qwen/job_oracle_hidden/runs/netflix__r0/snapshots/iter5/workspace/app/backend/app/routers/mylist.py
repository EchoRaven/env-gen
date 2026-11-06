from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_profile, get_current_user
from ..models import MyList, Title
from ..serializers import title_to_dict

router = APIRouter(prefix="/api/my-list", tags=["my-list"])


@router.get("")
def list_my_list(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    profile = get_current_profile(db, user, request)
    rows = (
        db.query(MyList)
        .filter(MyList.profile_id == profile.id)
        .order_by(MyList.id.desc())
        .all()
    )
    out = []
    for row in rows:
        t = db.query(Title).filter(Title.id == row.title_id).first()
        if t:
            d = title_to_dict(t, db)
            d["my_list_id"] = row.id
            out.append(d)
    return {"items": out}


@router.post("")
def add_to_my_list(
    request: Request,
    body: dict = {},
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    title_id = body.get("title_id") or body.get("id")
    if title_id is None:
        raise HTTPException(status_code=422, detail="title_id is required")
    t = db.query(Title).filter(Title.id == int(title_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Title not found")
    profile = get_current_profile(db, user, request, body_profile_id=body.get("profile_id"))
    existing = (
        db.query(MyList)
        .filter(MyList.profile_id == profile.id, MyList.title_id == t.id)
        .first()
    )
    if existing:
        return {"id": t.id, "profile_id": profile.id, "title_id": t.id, "already_listed": True}
    row = MyList(profile_id=profile.id, title_id=t.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": t.id, "profile_id": profile.id, "title_id": t.id, "my_list_id": row.id}


@router.put("/{item_id}")
def update_my_list(
    item_id: int,
    request: Request,
    body: dict = {},
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    profile = get_current_profile(db, user, request)
    row = (
        db.query(MyList)
        .filter(MyList.profile_id == profile.id)
        .filter(MyList.id == item_id)
        .first()
    )
    if not row:
        row = (
            db.query(MyList)
            .filter(MyList.profile_id == profile.id)
            .filter(MyList.title_id == item_id)
            .first()
        )
    if not row:
        raise HTTPException(status_code=404, detail="Not in your list")
    title_id = body.get("title_id") or body.get("id")
    if title_id is not None:
        t = db.query(Title).filter(Title.id == int(title_id)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Title not found")
        row.title_id = t.id
        db.commit()
        db.refresh(row)
    return {"id": row.id, "profile_id": profile.id, "title_id": row.title_id}


@router.delete("/{item_id}")
def remove_from_my_list(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    profile = get_current_profile(db, user, request)
    row = (
        db.query(MyList)
        .filter(MyList.profile_id == profile.id)
        .filter(MyList.id == item_id)
        .first()
    )
    if not row:
        row = (
            db.query(MyList)
            .filter(MyList.profile_id == profile.id)
            .filter(MyList.title_id == item_id)
            .first()
        )
    if not row:
        raise HTTPException(status_code=404, detail="Not in your list")
    db.delete(row)
    db.commit()
    return {"deleted": True, "title_id": row.title_id}
