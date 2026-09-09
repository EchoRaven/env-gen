"""#1202jb: a projected read that anyone can call must not carry contact or credential columns.

`_serialize_expr` emits the MODEL's columns and has never consulted the contract's declared
response shape, so a lane that removes `email` from the schema still gets it in the payload --
and #528 gives the projected read precedence over any GET the lane writes itself. It cannot
fix this from its side. `password_hash` was the only column the projector had been taught to
withhold; this is that same rule, at the same emitter, widened to the rest of the class.

Measured over the last 30 corpus runs: 18 UNAUTHENTICATED projected reads return `email` --
`/api/users/{username}` 14 times, `/api/search` once, and `/api/suggested-creators` THREE
times, which is a LIST: one anonymous request for every suggested creator's address. The
contract itself declares it (`auth_required: false` with `email` in the response), so nothing
downstream reads it as wrong.
"""
import sys
import pathlib
import re

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import route_projector as RP  # noqa: E402


_MODELS_PY = '''
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    display_name = Column(String)
    email = Column(String)
    phone = Column(String)
    password_hash = Column(String)
    avatar = Column(String)
    bio = Column(String)
    followers = Column(Integer)
    verified = Column(Boolean)
    email_verified = Column(Boolean)     # public-safe, and CONTAINS "email"
    tokens_used = Column(Integer)        # public-safe, and CONTAINS "token"


class SuggestedCreator(Base):
    __tablename__ = "suggested_creators"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    email = Column(String)
    followers = Column(Integer)


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    caption = Column(String)
    views = Column(Integer)
'''


def _models(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS_PY)
    return RP._orm_models(tmp_path)


def _keys(tmp_path, path, auth=False, scoped=False):
    h = RP._generate_handler("GET", path, auth, _models(tmp_path), 0, None, scoped, set())
    src = h if isinstance(h, str) else h[0]
    return set(re.findall(r'"(\w+)": ', src))


def test_an_anonymous_read_does_not_carry_the_address(tmp_path):
    k = _keys(tmp_path, "/api/users/{username}")
    assert "email" not in k, k
    assert "phone" not in k, k
    assert "password_hash" not in k, k


def test_the_page_still_gets_what_it_renders(tmp_path):
    """r110's profile page renders `user.followers`. An allowlist narrow enough to be safe
    would take it away, which is why this is a denylist and not #1202ir's display set."""
    k = _keys(tmp_path, "/api/users/{username}")
    for kept in ("username", "display_name", "avatar", "bio", "followers", "verified"):
        assert kept in k, (kept, k)


def test_it_is_keyed_on_REACH_not_on_the_table_name(tmp_path):
    """The worst instance in the corpus is `/api/suggested-creators`, which resolves to its
    OWN table because the lane copied the user fields into it. An actor-table test misses it,
    and it is the LIST case."""
    assert RP._resource_model("/api/suggested-creators", _models(tmp_path))[0] \
        == "suggested_creators"
    k = _keys(tmp_path, "/api/suggested-creators")
    assert "email" not in k, k
    assert "followers" in k, k


def test_your_own_record_keeps_your_own_address(tmp_path):
    k = _keys(tmp_path, "/api/users/me", auth=True)
    assert "email" in k, k


def test_a_table_with_nothing_private_is_untouched(tmp_path):
    k = _keys(tmp_path, "/api/videos")
    # "items"/"total" are the collection envelope, not columns
    assert k - {"items", "total"} == {"id", "caption", "views"}, k


def test_the_match_is_exact_not_substring(tmp_path):
    """`_IMAGEISH_1202FH` matching "art" inside `partner_email` is the substring trap this
    file already carries once, so this one has to be asserted through the EMITTED handler
    rather than by inspecting the frozenset.

    The first version of this test only checked membership of the set, and switching the
    production match to `any(k in col)` left it green — a vacuous assertion of exactly the
    kind #1202ip's actor ban was, caught the same way.
    """
    k = _keys(tmp_path, "/api/users/{username}")
    assert "email" not in k, k                # the private one goes
    assert "email_verified" in k, k           # the one that merely CONTAINS it stays
    assert "tokens_used" in k, k


def test_a_write_is_not_touched(tmp_path):
    """POST /auth/register must still answer with the address it just created."""
    h = RP._generate_handler("POST", "/api/users", False, _models(tmp_path), 0, None,
                             False, set())
    src = h if isinstance(h, str) else h[0]
    assert "email" in src, src
