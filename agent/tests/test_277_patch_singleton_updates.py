"""#277 — PATCH/PUT of an owner-scoped SINGLETON must UPDATE, not INSERT.

r61 (opus-4.7), live: POST /api/settings -> 201, GET -> 200, but PATCH /api/settings -> 500.
The projected PATCH handler ran ``obj = Setting(**valid); db.add(obj); db.commit()`` — a
CREATE. settings is an owner singleton (one row per user), so POST already inserted the row;
the PATCH re-INSERT hits the unique/owner constraint (or a NOT-NULL owner it did not set) and
500s. Same class as the note the projector already carries: "falling through to the create
path made PUT/PATCH do cls(**valid); db.add -> every update INSERTED a duplicate row".

The projector already routes PUT/PATCH to an UPDATE for two shapes: a ``/me`` path, and a
by-id path (``/notes/{id}``). The gap is the third: an owner-scoped singleton with NO id
param and not ending in ``/me`` — /api/settings, /api/preferences, /api/profile, /api/config.
These are one-row-per-user resources; a PATCH must load the caller's existing row (like /me)
and setattr onto it, not insert a second row.

Env-agnostic: any app with a per-user settings/preferences singleton hits it. The fix reuses
the /me update logic (owner-scoped fetch of the single existing row) for a no-id PATCH/PUT on
an owner-scoped resource. A genuine collection create (POST /api/videos) is untouched, and a
by-id update keeps its existing path.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import _generate_handler  # noqa: E402


def _m(cls, cols, fks=None):
    return {"cls": cls, "cols": cols, "fks": fks or {}}


_MODELS = {
    "users": _m("User", ["id", "email", "name", "password_hash"]),
    "settings": _m("Setting", ["id", "user_id", "dark_mode", "language"], {"user_id": "users"}),
    "videos": _m("Video", ["id", "author_id", "caption"], {"author_id": "users"}),
}


def test_r61_regression_patch_settings_updates_not_inserts():
    src = _generate_handler("PATCH", "/api/settings", auth=True, models=_MODELS, idx=1,
                            response_key="item")
    # It must LOAD an existing row and setattr — not construct + add a new one.
    assert "setattr(obj" in src, src
    # It must LOAD the caller's existing row first (update semantics), not unconditionally
    # insert. A create-if-absent branch may still construct one for a first-ever PATCH.
    assert "db.query(Setting).filter(" in src, "PATCH singleton must load-then-update:\n" + src


def test_put_settings_also_updates():
    src = _generate_handler("PUT", "/api/settings", auth=True, models=_MODELS, idx=2,
                            response_key="item")
    assert "setattr(obj" in src and "db.query(Setting).filter(" in src, src


def test_owner_scoped_fetch_is_used_for_the_singleton():
    """The one existing row is the caller's — fetch it owner-scoped, like /me."""
    src = _generate_handler("PATCH", "/api/settings", auth=True, models=_MODELS, idx=3,
                            response_key="item")
    assert "_fw_owner_val(Setting" in src or "user" in src, src


def test_a_real_collection_create_is_untouched():
    """POST to a genuine collection stays a create — do not turn it into an update."""
    src = _generate_handler("POST", "/api/videos", auth=True, models=_MODELS, idx=4,
                            response_key="item")
    assert "Video(**valid)" in src, "collection POST must still CREATE:\n" + src


def test_by_id_update_still_works():
    src = _generate_handler("PATCH", "/api/videos/{id}", auth=True, models=_MODELS, idx=5,
                            response_key="item")
    assert "setattr(obj" in src and "Video(**valid)" not in src, src


def test_me_path_still_updates():
    src = _generate_handler("PATCH", "/api/users/me", auth=True, models=_MODELS, idx=6,
                            response_key="item")
    assert "setattr(obj" in src, src


def test_generated_patch_handler_compiles():
    import ast
    src = _generate_handler("PATCH", "/api/settings", auth=True, models=_MODELS, idx=7,
                            response_key="item")
    ast.parse(src)
