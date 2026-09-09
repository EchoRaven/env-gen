"""#1202ip / #1202iq: a PUBLIC projected list read folds in the entity it names by id.

Why this is a framework bug and not a lane bug: #528 hands the projected read precedence
over the lane's own GET on a registered resource, so when the projected payload carries a
bare `sound_id` the lane physically cannot serve `sound_name` from anywhere. r109's
`custom_routes.py` defines a richer `GET /api/videos` that never receives a request, while
its own card renders `sound?.name || video.sound_name || video.sound_id` -- the raw id.

Measured before the fix: 123 of 232 public projected list reads across 24 corpus runs
(tiktok / netflix / googlemaps) answered with bare foreign keys.

Every assertion here goes through the production entry point `_generate_handler`, and the
models come from `_orm_models` parsing a REAL SQLAlchemy source -- a hand-built dict would
be a stand-in that can agree with a fix the production path does not have.
"""
import sys
import pathlib
import ast

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import route_projector as RP  # noqa: E402


_MODELS_PY = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    name = Column(String)          # netflix's users table really has one; without a column
    email = Column(String)         # in _LABEL_COLS_803 the actor ban below is never reached
    password_hash = Column(String)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    label = Column(String)


class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    cover = Column(String)


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    caption = Column(String)
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))
'''


def _models(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS_PY)
    m = RP._orm_models(tmp_path)
    assert "videos" in m and "sounds" in m, m.keys()
    return m


def _public_videos_handler(tmp_path):
    h = RP._generate_handler("GET", "/api/videos", False, _models(tmp_path),
                             0, None, False, set())
    return h if isinstance(h, str) else h[0]


def test_a_public_list_carries_the_referenced_entity_not_just_its_id(tmp_path):
    src = _public_videos_handler(tmp_path)
    # the bare id stays (nothing is taken away) ...
    assert '"sound_id": getattr(r, "sound_id", None)' in src
    # ... and the entity it names is folded in under the base name.
    assert '"sound": _m_sound.get(getattr(r, "sound_id", None))' in src, src
    assert '_m_sound = {getattr(t, "id", None)' in src, src
    # one BATCHED query, not N+1: the lookup is an `in_` over the collected ids.
    assert '.in_(_ids_sound)' in src, src


def test_the_folded_entity_actually_carries_a_drawable_field(tmp_path):
    """A fold that carries only `{"id": ...}` would satisfy the shape assertions above
    while leaving the page exactly as unrenderable as a bare id."""
    src = _public_videos_handler(tmp_path)
    _map = src.split("_m_sound = {getattr(t,", 1)[1].split("for t in", 1)[0]
    assert '"name": getattr(t, "name", None)' in _map, _map


def test_the_emitted_public_handler_parses(tmp_path):
    """The fold splices generated lines into a generated function body; a comprehension
    that shadows `r` or an unbalanced brace would only show up at import time in the app."""
    ast.parse(_public_videos_handler(tmp_path).split("\n", 1)[1])


def test_an_actor_table_is_still_refused_on_a_public_list(tmp_path):
    """#569/#803's actor ban is what keeps this fix from being a leak. `author_id` points
    at `users`, and #1202iq made that target RESOLVABLE for the first time -- so the ban is
    now load-bearing in a way it was not before, and has to be asserted, not assumed.

    The first version of this test passed with the ban DELETED: its `User` carried no
    column in `_LABEL_COLS_803`, so `_expandable_fks_1202fh` refused on "nothing a card
    could draw" instead and the assertion proved nothing. `name` is here to make the ban
    the guard that actually fires."""
    src = _public_videos_handler(tmp_path)
    assert '"author":' not in src, src
    assert "_m_author" not in src, src
    assert "email" not in src, src
    assert "password_hash" not in src, src


def test_declared_foreign_keys_are_resolved_when_the_name_does_not_match(tmp_path):
    """#1202iq. Name inference tries `<base>s` / `<base>` / `<base>es`, so `category_id`
    tries categorys / category / categoryes and never reaches `categories`. 76 of 396
    declared FKs in the corpus were invisible this way (tiktok r105 has exactly this one).

    Asserted THROUGH `_generate_handler`, not by re-deriving the resolution order in the
    test: the declared map is the only thing that can put `category` in this payload, so
    reverting `_declared.get(c) or ...` back to name-only turns this red.
    """
    models = _models(tmp_path)
    assert RP._fk_target_by_name_908("category_id", models) is None, "premise: name-invisible"
    assert (models["videos"].get("fks") or {}).get("category_id") == "categories"

    src = _public_videos_handler(tmp_path)
    assert '"category": _m_category.get(getattr(r, "category_id", None))' in src, src
    assert '"label": getattr(t, "label", None)' in src, src


def test_a_list_with_nothing_to_fold_is_unchanged(tmp_path):
    """`sounds` has no outgoing FK. Its read must emit the plain serialisation, with no
    empty `{**...}` wrapper and no dangling prep lines."""
    h = RP._generate_handler("GET", "/api/sounds", False, _models(tmp_path),
                             0, None, False, set())
    src = h if isinstance(h, str) else h[0]
    assert "_m_" not in src, src
    assert "{**" not in src, src


def test_the_owner_scoped_branch_still_folds(tmp_path):
    """#1202ip moved #1202fh's emission into a shared helper. The branch it came from must
    keep behaving; if this goes quiet, the refactor ate the original fix."""
    h = RP._generate_handler("GET", "/api/videos", True, _models(tmp_path),
                             0, None, True, {"videos"})
    src = h if isinstance(h, str) else h[0]
    assert '"sound": _m_sound.get(' in src, src


# --------------------------------------------------------------------------------------
# #1202ir: an ACTOR target folds in ONLY where the contract already publishes that actor.
# --------------------------------------------------------------------------------------

_PUBLIC_USER_EP = [{"method": "GET", "path": "/api/users/{username}", "auth_required": False}]
_PRIVATE_USER_EP = [{"method": "GET", "path": "/api/users/{username}", "auth_required": True}]


def _videos_with(tmp_path, endpoints):
    models = _models(tmp_path)
    pub = RP._public_actor_tables_1202ir(endpoints, models)
    h = RP._generate_handler("GET", "/api/videos", False, models, 0, None, False, set(),
                             public_actor_tables=pub)
    return (h if isinstance(h, str) else h[0]), pub


def test_an_actor_folds_in_only_where_the_contract_publishes_it(tmp_path):
    """The zero-new-exposure argument: every column folded here is already retrievable,
    one request per row, from a read the contract itself declares public. Where it does
    not, #569/#803's ban stands."""
    public_src, pub = _videos_with(tmp_path, _PUBLIC_USER_EP)
    assert "users" in pub, pub
    assert '"author": _m_author.get(getattr(r, "author_id", None))' in public_src, public_src

    private_src, pub2 = _videos_with(tmp_path, _PRIVATE_USER_EP)
    assert "users" not in pub2, pub2
    assert "_m_author" not in private_src, private_src


def test_an_unstated_contract_is_not_a_public_one(tmp_path):
    """`_stated_auth_1202hi` answers None when nothing states it. None must not be read as
    False -- the whole class of bugs in this repo where an empty value became a meaningful
    one (#902 blank route as site root, #907 empty cache as an empty tree, #566y empty
    child_meta as True)."""
    _, pub = _videos_with(tmp_path, [{"method": "GET", "path": "/api/users/{username}"}])
    assert "users" not in pub, pub


def test_only_allowlisted_actor_columns_come_along(tmp_path):
    src, _ = _videos_with(tmp_path, _PUBLIC_USER_EP)
    fold = src.split("_m_author = {getattr(t,", 1)[1].split("for t in", 1)[0]
    assert '"username": getattr(t, "username", None)' in fold, fold
    assert "email" not in fold, fold
    assert "password_hash" not in fold, fold


def test_the_substring_image_rule_is_not_used_on_an_actor_table(tmp_path):
    """`_IMAGEISH_1202FH` matches by SUBSTRING, and "art" is one of its keys -- so
    `partner_email` and `cart_token` both match it. That is harmless on a table whose every
    column is already public and a leak on an actor table, which is why #1202ir switched
    actors to exact membership. Without that split this test hands out a token."""
    models_py = _MODELS_PY.replace(
        '    password_hash = Column(String)',
        '    password_hash = Column(String)\n    cart_token = Column(String)\n'
        '    partner_email = Column(String)')
    (tmp_path / "models.py").write_text(models_py)
    models = RP._orm_models(tmp_path)
    assert "cart_token" in models["users"]["cols"], models["users"]["cols"]
    pub = RP._public_actor_tables_1202ir(_PUBLIC_USER_EP, models)
    h = RP._generate_handler("GET", "/api/videos", False, models, 0, None, False, set(),
                             public_actor_tables=pub)
    src = h if isinstance(h, str) else h[0]
    assert "_m_author" in src, "premise: the actor must actually be folded here"
    assert "cart_token" not in src, src
    assert "partner_email" not in src, src


def test_a_public_actor_that_the_app_serves_owner_scoped_is_still_refused(tmp_path):
    """Two guards, opposite directions: the contract may declare the read public while the
    table metadata marks its reads owner-scoped. That is #1202io's contradiction, and the
    fold must take the restrictive side of it rather than pick a winner."""
    models = _models(tmp_path)
    pub = RP._public_actor_tables_1202ir(_PUBLIC_USER_EP, models)
    h = RP._generate_handler("GET", "/api/videos", False, models, 0, None, False,
                             {"users"}, public_actor_tables=pub)
    src = h if isinstance(h, str) else h[0]
    assert "_m_author" not in src, src
