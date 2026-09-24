"""Framework-owned BACKEND SKELETON — by-construction generation of the whole backend
from the contract (user-chosen "skeleton根治", 2026-06-09). The same contract must yield
a consistent, complete, importable backend: spine + app ORM models, all CRUD handlers
projected from the endpoints, fixed storage/auth/infra. Validated end-to-end by a real
docker build+boot (every endpoint 2xx, auth enforced, POST persists) — these tests lock
the generation invariants.
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    render_models,
    render_skeleton_main,
    write_backend_skeleton,
)

_TABLES = {
    "users": {"schema": {"columns": [
        {"name": "id", "type": "serial", "primary_key": True},
        {"name": "username", "type": "text", "nullable": False, "unique": True},
        {"name": "full_name", "type": "text"},
        {"name": "avatar_url", "type": "text"},
    ]}},
    "posts": {"schema": {"columns": [
        {"name": "id", "type": "serial", "primary_key": True},
        {"name": "author_id", "type": "integer", "nullable": False, "fk": "users.id"},
        {"name": "caption", "type": "text"},
        {"name": "created_at", "type": "timestamp", "default": "now()"},
    ]}},
    "follows": {"schema": {"columns": [
        # an id WITHOUT primary_key + a pseudo table-constraint (the run #17 PK trap)
        {"name": "id", "type": "serial"},
        {"name": "follower_id", "type": "integer", "fk": "users.id"},
        {"name": "following_id", "type": "integer", "references": "users(id)"},
        {"name": "unique(follower_id,following_id)", "type": "constraint"},
    ]}},
    "oauth_clients": {"schema": {"columns": [{"name": "id", "type": "text", "primary_key": True}]}},
}
_ENDPOINTS = [
    {"method": "GET", "path": "/api/users/me"},
    {"method": "GET", "path": "/api/users/suggested"},
    {"method": "GET", "path": "/api/users/{username}"},
    {"method": "POST", "path": "/api/posts"},
    {"method": "GET", "path": "/api/feed"},
    {"method": "GET", "path": "/api/users/{username}/posts"},
    {"method": "POST", "path": "/api/users/{username}/follow"},
]


def test_models_spine_app_and_parse():
    src = render_models(_TABLES)
    ast.parse(src)
    classes = [l.split("(")[0].replace("class ", "") for l in src.splitlines() if l.startswith("class ")]
    assert "Tenant" in classes and "User" in classes        # spine always present
    assert "Post" in classes and "Follow" in classes        # app tables
    assert "OauthClient" not in classes and "OAuthClient" not in classes  # AS tables skipped
    # User merges spine + app columns
    assert "email = Column" in src and "password_hash = Column" in src  # spine
    assert "username = Column" in src and "full_name = Column" in src   # app extras
    # FK resolved (both `fk` and inline `references`)
    assert 'ForeignKey("users.id")' in src


def test_every_model_has_exactly_one_primary_key():
    """run #17 trap: a table with an id column NOT marked primary_key must still get a
    PK on that column (not a shadowed duplicate that yields 'no primary key')."""
    src = render_models(_TABLES)
    cur = None
    pk_count = {}
    for line in src.splitlines():
        if line.startswith("class "):
            cur = line.split("(")[0].replace("class ", "")
            pk_count[cur] = 0
        elif cur and "primary_key=True" in line:
            pk_count[cur] += 1
        elif cur and "= Column(" in line and line.strip().startswith("id ="):
            pass
    for cls in ("Tenant", "User", "Post", "Follow"):
        assert pk_count.get(cls) == 1, f"{cls} must have exactly 1 PK, got {pk_count.get(cls)}"
    # the bare-id follows table: its id line carries the PK
    assert "    id = Column(Integer, primary_key=True)" in src


def test_pseudo_constraint_column_skipped():
    src = render_models(_TABLES)
    assert "unique(follower_id" not in src  # the pseudo table-constraint is not a column


def test_skeleton_main_projects_all_handlers_static_first_with_auth():
    src = render_skeleton_main(_ENDPOINTS, _TABLES)
    ast.parse(src)
    assert src.count("def _projected_") == len(_ENDPOINTS)
    assert "_framework_auth_guard" in src                       # auth enforcement middleware
    assert "from auth_dependency import get_current_user" in src
    assert "Base.metadata.create_all" in src                    # tables created on boot
    # static /suggested registered before the /{username} catch-all
    assert src.index('"/api/users/suggested"') < src.index('"/api/users/{username}"')


def test_feed_explore_resolve_to_posts_model():
    """/api/feed and /api/explore name no table, so they resolved to NO model and
    the projector emitted a hardcoded empty list — every feed/explore screen showed
    'no posts' forever (2026-06-10). Posts-shaped tokens must fall back to posts."""
    src = render_skeleton_main(
        [{"method": "GET", "path": "/api/feed"},
         {"method": "GET", "path": "/api/explore"}], _TABLES)
    ast.parse(src)
    assert '{"items": [], "total": 0}' not in src     # no hardcoded empty handlers
    assert src.count("db.query(Post)") >= 2           # both query the posts model


def test_get_by_param_with_empty_columns_contract_does_not_500():
    """instagram M1 (2026-06-10): the lane registered users with EMPTY columns →
    spine-only model (no username column) → the get-by-field handler fell back to
    ``User.id == username`` with a STRING path param → postgres integer=text type
    error → 500 on every probe → the whole validation budget burned. The fallback
    must coerce: non-numeric → 404, numeric → int(key)."""
    tables = {"users": {"schema": {"columns": []}}}   # the empty-columns contract
    src = render_skeleton_main(
        [{"method": "GET", "path": "/api/users/{username}"}], tables)
    ast.parse(src)
    assert ".isdigit()" in src                      # the guard exists
    assert "== int(_key)" in src                    # id compared as int, not str
    assert '"id") == username' not in src           # the raw string compare is gone


def test_get_me_returns_current_user_single_not_list():
    """GET /<resource>/me must return the CURRENT authed user as a single {item},
    NOT fall through to GET-collection and return {items:[all rows]} (the real bug
    found on instagram M1: /api/users/me returned every user as a list)."""
    src = render_skeleton_main([{"method": "GET", "path": "/api/users/me"}], _TABLES)
    ast.parse(src)
    import re
    handler = re.search(r'@app\.get\("/api/users/me".*?(?=@app\.|if __name__)', src, re.S)
    assert handler, "no /api/users/me handler projected"
    body = handler.group(0)
    assert "db.get(User, _fw_owner_val(User, 'id', user))" in body   # #134: resolves "me" → authed user (type-coerced)
    assert '"item":' in body and '"items":' not in body   # single object, not a list


def test_write_backend_skeleton_emits_buildable_set(tmp_path):
    res = write_backend_skeleton(tmp_path, _ENDPOINTS, _TABLES)
    be = tmp_path / "app" / "backend"
    for f in ("models.py", "database.py", "main.py", "auth_dependency.py",
              "schemas.py", "pyproject.toml", "Dockerfile", "reset.sh"):
        assert (be / f).exists(), f"missing {f}"
    for f in ("models.py", "database.py", "main.py", "auth_dependency.py"):
        ast.parse((be / f).read_text(encoding="utf-8"))      # all valid Python
    # fixed infra: deps-only install (no hatchling wheel build) + runs main.py
    assert "[build-system]" not in (be / "pyproject.toml").read_text(encoding="utf-8")
    assert "-r pyproject.toml" in (be / "Dockerfile").read_text(encoding="utf-8")


def test_deterministic_same_contract_same_output(tmp_path):
    a = render_skeleton_main(_ENDPOINTS, _TABLES)
    b = render_skeleton_main(_ENDPOINTS, _TABLES)
    assert a == b                                            # byte-identical (no variance)
    assert render_models(_TABLES) == render_models(_TABLES)


def test_unresolved_param_get_is_item_shaped_or_404():
    """A parameterized GET with no table must NOT stub as a collection
    (live 2026-06-11: GET /api/business_discovery/{username} stubbed
    {"items":...} → shape gate failed forever). Param name resolving to a
    model column → single-item lookup; otherwise honest 404."""
    from multi_agent.runtime.route_projector import _generate_handler
    # the REAL models dict shape (from _parse_models) is {table: {"cls", "cols": [name,...]}}.
    # The prior fixture used phantom class_name/columns keys, masking that this resolver was
    # dead in production (always 404) until it was fixed to read the real keys.
    models = {"users": {"cls": "User", "cols": ["id", "username"]}}
    src = _generate_handler("GET", "/api/business_discovery/{username}", True, models, 1)
    assert '"items"' not in src
    assert "User.username == username" in src
    assert '"item"' in src and "404" in src
    src2 = _generate_handler("GET", "/api/mystery/{token}", True, models, 2)
    assert '"items"' not in src2
    assert "404" in src2
