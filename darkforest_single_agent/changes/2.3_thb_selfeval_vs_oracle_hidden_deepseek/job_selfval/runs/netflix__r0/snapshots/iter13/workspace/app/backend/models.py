from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profiles: Mapped[list["Profile"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str] = mapped_column(String, nullable=False)
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="profiles")


class Title(Base):
    __tablename__ = "titles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[str | None] = mapped_column(String)
    genre: Mapped[str | None] = mapped_column(String)
    maturity_rating: Mapped[str | None] = mapped_column(String)
    rating: Mapped[float] = mapped_column(Float, default=0)
    synopsis: Mapped[str | None] = mapped_column(Text)
    poster: Mapped[str | None] = mapped_column(String)
    backdrop: Mapped[str | None] = mapped_column(String)
    video_url: Mapped[str | None] = mapped_column(String)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    top10_rank: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String)
    language_name: Mapped[str | None] = mapped_column(String)


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title_id: Mapped[int] = mapped_column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    synopsis: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail: Mapped[str | None] = mapped_column(String)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class TitleGenre(Base):
    __tablename__ = "title_genres"
    __table_args__ = (UniqueConstraint("title_id", "genre_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title_id: Mapped[int] = mapped_column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    genre_id: Mapped[int] = mapped_column(Integer, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False)


class MyList(Base):
    __tablename__ = "my_list"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id: Mapped[int] = mapped_column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id: Mapped[int] = mapped_column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id: Mapped[int] = mapped_column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    progress_seconds: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
