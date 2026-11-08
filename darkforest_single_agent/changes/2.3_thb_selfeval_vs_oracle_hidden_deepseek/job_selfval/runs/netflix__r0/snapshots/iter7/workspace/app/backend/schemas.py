from typing import Optional

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class ProfileCreate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    is_kids: bool = False


class MyListCreate(BaseModel):
    title_id: Optional[int] = None


class RatingCreate(BaseModel):
    value: Optional[int] = None
    rating: Optional[int] = None


class ProgressCreate(BaseModel):
    title_id: Optional[int] = None
    progress_seconds: int = 0
