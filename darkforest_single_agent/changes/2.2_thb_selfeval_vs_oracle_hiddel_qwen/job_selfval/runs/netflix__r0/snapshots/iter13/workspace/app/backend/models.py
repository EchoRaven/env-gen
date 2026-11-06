"""SQLAlchemy ORM models — mirror app/database/init/01_init.sql exactly."""
from sqlalchemy import (Boolean, Column, Double, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False, default="")
    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    avatar = Column(String, nullable=False, default="0")
    is_kids = Column(Boolean, nullable=False, default=False)
    user = relationship("User", back_populates="profiles")


class Genre(Base):
    __tablename__ = "genres"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)              # series | movie
    year = Column(String)
    genre = Column(String)                              # primary genre
    maturity_rating = Column(String)
    rating = Column(Float)
    synopsis = Column(Text)
    poster = Column(String)
    backdrop = Column(String)
    video_url = Column(String)
    duration = Column(Integer, nullable=False, default=0)
    top10_rank = Column(Integer)
    language = Column(String)


class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    season = Column(Integer, nullable=False)
    number = Column(Integer, nullable=False)
    name = Column(String)
    synopsis = Column(Text)
    duration = Column(Integer, nullable=False, default=0)
    thumbnail = Column(String)


class TitleGenre(Base):
    __tablename__ = "title_genres"
    __table_args__ = (UniqueConstraint("title_id", "genre_id"),)
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    genre_id = Column(Integer, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False)


class MyList(Base):
    __tablename__ = "my_list"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    value = Column(Integer, nullable=False)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    progress_seconds = Column(Integer, nullable=False, default=0)
