from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=1)
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: str
    avatar: str | None = "avatar_0"
    is_kids: bool = False


class ProfileUpdate(BaseModel):
    name: str | None = None
    avatar: str | None = None
    is_kids: bool | None = None


class MyListIn(BaseModel):
    title_id: int | None = None
    id: int | None = None


class RatingIn(BaseModel):
    value: int = Field(ge=1, le=3)


class ContinueWatchingIn(BaseModel):
    title_id: int
    progress_seconds: int = 0
