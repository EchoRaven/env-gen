from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP,
    UniqueConstraint, func,
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    avatar = Column(String, nullable=False, default="crimson")
    is_kids = Column(Boolean, nullable=False, default=False)
    user = relationship("User", back_populates="profiles")


class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    genre = Column(String, nullable=False)
    maturity_rating = Column(String, nullable=False)
    rating = Column(Numeric(3, 1), nullable=False, default=0)
    synopsis = Column(Text, nullable=False)
    poster = Column(String, nullable=False)
    backdrop = Column(String, nullable=False)
    video_url = Column(String, nullable=False)
    duration = Column(Integer, nullable=False)
    top10_rank = Column(Integer)
    language = Column(String, nullable=False, default="en")
    genres = relationship("Genre", secondary="title_genres", lazy="selectin")
    episodes = relationship("Episode", back_populates="title", cascade="all, delete-orphan")


class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    season = Column(Integer, nullable=False)
    number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    synopsis = Column(Text, nullable=False)
    duration = Column(Integer, nullable=False)
    thumbnail = Column(String, nullable=False)
    title = relationship("Title", back_populates="episodes")


class Genre(Base):
    __tablename__ = "genres"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class TitleGenre(Base):
    __tablename__ = "title_genres"
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    genre_id = Column(Integer, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (UniqueConstraint("title_id", "genre_id"),)


class MyList(Base):
    __tablename__ = "my_list"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)


class Rating(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    value = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    progress_seconds = Column(Integer, nullable=False, default=0)
    updated_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
