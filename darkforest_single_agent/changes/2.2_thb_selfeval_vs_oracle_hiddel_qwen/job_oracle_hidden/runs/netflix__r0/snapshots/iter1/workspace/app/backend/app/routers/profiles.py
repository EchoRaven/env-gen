from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Profile
from ..schemas import ProfileIn, ProfileUpdate
from ..serializers import profile_to_dict

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
def list_profiles(db: Session = Depends(get_db), user=Depends(get_current_user)):
    profiles = (
        db.query(Profile).filter(Profile.user_id == user.id).order_by(Profile.id).all()
    )
    return [profile_to_dict(p) for p in profiles]


@router.post("")
def create_profile(body: ProfileIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    profile = Profile(user_id=user.id, name=body.name.strip(), avatar=body.avatar or "avatar_0", is_kids=body.is_kids)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile_to_dict(profile)


@router.patch("/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if body.name is not None:
        profile.name = body.name.strip() or profile.name
    if body.avatar is not None:
        profile.avatar = body.avatar
    if body.is_kids is not None:
        profile.is_kids = body.is_kids
    db.commit()
    db.refresh(profile)
    return profile_to_dict(profile)


@router.delete("/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    remaining = db.query(Profile).filter(Profile.user_id == user.id).count()
    if remaining <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last profile")
    db.delete(profile)
    db.commit()
    return {"deleted": True}
