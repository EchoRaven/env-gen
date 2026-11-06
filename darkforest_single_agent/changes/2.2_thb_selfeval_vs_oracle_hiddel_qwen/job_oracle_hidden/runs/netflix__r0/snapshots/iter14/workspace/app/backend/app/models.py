from sqlalchemy import Column, Integer, String, Text, Boolean, Float, ForeignKey, UniqueConstraint
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    avatar = Column(String, nullable=False, default="avatar_0")
    is_kids = Column(Boolean, nullable=False, default=False)


class Genre(Base):
    __tablename__ = "genres"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    year = Column(String, nullable=False)
    genre = Column(String)
    maturity_rating = Column(String)
    rating = Column(Float)
    synopsis = Column(Text)
    language = Column(String)
    poster = Column(String)
    backdrop = Column(String)
    video_url = Column(String)
    duration = Column(Integer)
    top10_rank = Column(Integer)


class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)
    season = Column(Integer, nullable=False)
    number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    synopsis = Column(Text)
    duration = Column(Integer)
    thumbnail = Column(String)


class TitleGenre(Base):
    __tablename__ = "title_genres"
    __table_args__ = (UniqueConstraint("title_id", "genre_id"),)
    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)
    genre_id = Column(Integer, ForeignKey("genres.id"), nullable=False)


class MyList(Base):
    __tablename__ = "my_list"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)
    value = Column(Integer, nullable=False)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    __table_args__ = (UniqueConstraint("profile_id", "title_id"),)
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id"), nullable=False)
    progress_seconds = Column(Integer, nullable=False, default=0)
