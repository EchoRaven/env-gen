"""FIX #72 — canonical per-user named-row consistency (outlook run-61, live 2026-07-03).

The lane's reply/forward/delete handlers look up a REQUIRED per-user singleton by a literal
label (``Folder.name == "Sent"``, ``Folder.kind == "trash"``) and 500 when it is absent. The
framework seeds GENERIC names, so no user has that row → every such write 500s on a CORRECT
handler and the business_chain gate wedges forever (live: reply→422 auto-filled→500 'User or
Sent folder not found'; PROVEN fixed e2e: after bootstrapping the user's Sent folder the reply
returns 201). This detects the canonical rows from the raise-on-absent idiom and projects the
bootstrap spec the seed loader + create_user enforce. LOCAL-ONLY (agent/tests/ gitignored).
"""

import os
import sys
import tempfile
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import canonical_rows as cr  # noqa: E402
from multi_agent.runtime import backend_skeleton as bs  # noqa: E402

_MODELS = '''
class User(Base):
    __tablename__ = "users"
class Folder(Base):
    __tablename__ = "folders"
class Message(Base):
    __tablename__ = "messages"
'''

# the real outlook idiom: a required-singleton lookup guarded by a raise-on-absent
_ROUTES_REQUIRED = '''
def reply_message(messageId: int, msg_in, db, user):
    user_id = user["id"]
    orig = db.query(Message).filter(Message.id == messageId, Message.user_id == user_id).first()
    if not orig:
        raise HTTPException(status_code=404, detail="Original message not found")
    sent_folder = db.query(Folder).filter(Folder.user_id == user_id, Folder.name == "Sent").first()
    if not user or not sent_folder:
        raise HTTPException(status_code=500, detail="User or Sent folder not found")

def delete_message(messageId: int, db, user):
    user_id = user["id"]
    trash_folder = db.query(Folder).filter(Folder.user_id == user_id, Folder.kind == "trash").first()
    if not trash_folder:
        raise HTTPException(status_code=500, detail="Trash folder not found")
'''

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "email", "type": "String"}, {"name": "name", "type": "String"},
        {"name": "password_hash", "type": "String"}, {"name": "tenant_id", "type": "String"}]},
    "folders": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "user_id", "type": "Integer", "references": "users.id"},
        {"name": "name", "type": "Text"}, {"name": "kind", "type": "Text"},
        {"name": "unread_count", "type": "Integer"}, {"name": "created_at", "type": "DateTime"}]},
    "messages": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "user_id", "type": "Integer", "references": "users.id"},
        {"name": "subject", "type": "Text"}]},
}


# ── detector ─────────────────────────────────────────────────────────────────
def test_detects_required_singletons():
    det = cr.detect_canonical_rows(_ROUTES_REQUIRED, _MODELS)
    got = {(d["table"], d["match_col"], d["literal"]) for d in det}
    assert ("folders", "name", "Sent") in got
    assert ("folders", "kind", "trash") in got


def test_ignores_non_label_columns():
    """``.id ==`` / ``.user_id ==`` / ``.status ==`` are NOT canonical rows to create —
    materialising a row per-user for a status filter would fabricate spurious objects."""
    det = cr.detect_canonical_rows(_ROUTES_REQUIRED, _MODELS)
    cols = {d["match_col"] for d in det}
    assert "id" not in cols and "user_id" not in cols
    src = ('x = db.query(Order).filter(Order.user_id == uid, Order.status == "pending").first()\n'
           '    if not x:\n        raise HTTPException(status_code=404, detail="none")\n')
    assert cr.detect_canonical_rows(src, 'class Order(Base):\n    __tablename__ = "orders"\n') == []


def test_authz_gate_403_is_not_bootstrapped():
    """SECURITY: a per-user ``Role.name == "admin"`` guarded by a 403 is an authorization
    gate — its absence is INTENTIONAL for unprivileged users. Bootstrapping an 'admin' row
    per user would be privilege escalation, so a 4xx-guarded lookup is NEVER canonical."""
    src = ('role = db.query(Role).filter(Role.user_id == uid, Role.name == "admin").first()\n'
           '    if not role:\n'
           '        raise HTTPException(status_code=403, detail="admin role required")\n')
    models = 'class Role(Base):\n    __tablename__ = "roles"\n'
    assert cr.detect_canonical_rows(src, models) == []
    # a 401 gate is likewise excluded
    src401 = src.replace("403", "401")
    assert cr.detect_canonical_rows(src401, models) == []
    # …but the SAME lookup guarded by a 5xx (a broken invariant) IS canonical
    src500 = src.replace("403", "500")
    got = {(d["table"], d["match_col"], d["literal"]) for d in cr.detect_canonical_rows(src500, models)}
    assert ("roles", "name", "admin") in got


def test_write_target_structural_container_detected():
    """run-62 GRACEFUL reply variant: no 5xx guard, but the looked-up folder's ``.id`` is
    assigned as an FK (``folder_id=sent_folder.id``) → the folder is a structural container
    the reply files into. Without it every reply orphans (folder_id NULL) and the Sent
    folder is forever empty. Detected via the write-target signal."""
    src = ("sent_folder = db.query(Folder).filter(Folder.user_id == user_id, "
           "Folder.kind == 'sent').first()\n"
           "    new_message = Message(user_id=user_id, "
           "folder_id=sent_folder.id if sent_folder else None, subject=s)\n")
    got = {(d["table"], d["match_col"], d["literal"]) for d in cr.detect_canonical_rows(src, _MODELS)}
    assert ("folders", "kind", "sent") in got


def test_write_target_excludes_authz_even_without_raise():
    """SECURITY: a labeled lookup whose ``.id`` is NOT used as an FK and has no 5xx guard
    is never canonical — an authz check that merely reads a role is not bootstrapped."""
    src = ('admin = db.query(Role).filter(Role.user_id == uid, Role.name == "admin").first()\n'
           '    allowed = admin is not None\n'
           '    return {"allowed": allowed}\n')
    assert cr.detect_canonical_rows(src, 'class Role(Base):\n    __tablename__ = "roles"\n') == []


def test_status_dot_http_5xx_form_detected():
    """The ``status.HTTP_500_INTERNAL_SERVER_ERROR`` spelling (the outlook lane's form) is
    recognised as a 5xx guard."""
    src = ('sent = db.query(Folder).filter(Folder.user_id == uid, Folder.name == "Sent").first()\n'
           '    if not sent:\n'
           '        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="x")\n')
    got = {(d["match_col"], d["literal"]) for d in cr.detect_canonical_rows(src, _MODELS)}
    assert ("name", "Sent") in got


def test_labeled_lookup_without_raise_is_not_canonical():
    """A labeled lookup that does NOT raise on absence is optional content, not a required
    canonical row — do not bootstrap it (avoids over-creating rows)."""
    src = ('archive = db.query(Folder).filter(Folder.name == "Archive").first()\n'
           '    return archive or {}\n')
    assert cr.detect_canonical_rows(src, _MODELS) == []


def test_detector_never_raises_on_garbage():
    assert cr.detect_canonical_rows("", "") == []
    assert cr.detect_canonical_rows("def (((", "class ??") == []


# ── spec builder ─────────────────────────────────────────────────────────────
def test_build_spec_valid_rows():
    canonical = cr.detect_canonical_rows(_ROUTES_REQUIRED, _MODELS)
    spec = cr.build_bootstrap_spec(canonical, _TABLES)
    by = {(s["match_col"], s["literal"]): s for s in spec}
    sent = by[("name", "Sent")]
    assert sent["table"] == "folders" and sent["owner_col"] == "user_id"
    assert sent["row"].get("name") == "Sent"                 # match literal present
    assert "kind" in sent["row"] and "unread_count" in sent["row"]  # NOT NULL siblings filled
    assert "id" not in sent["row"] and "user_id" not in sent["row"]  # PK/owner excluded
    trash = by[("kind", "trash")]
    assert trash["row"].get("kind") == "trash"
    assert trash["row"].get("name") == "Trash"               # cosmetic label, not a seed title


def test_spec_skips_non_per_user_table():
    """A table with no owner FK is not per-user → a per-user default is meaningless."""
    tables = {"settings": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "key", "type": "String"}, {"name": "value", "type": "String"}]}}
    canonical = [{"model": "Setting", "table": "settings", "match_col": "key", "literal": "theme"}]
    assert cr.build_bootstrap_spec(canonical, tables) == []


def test_spec_skips_unknown_table():
    canonical = [{"model": "Ghost", "table": "ghosts", "match_col": "name", "literal": "X"}]
    assert cr.build_bootstrap_spec(canonical, _TABLES) == []


def test_empty_canonical_yields_empty_spec():
    assert cr.build_bootstrap_spec([], _TABLES) == []


# ── generated-code integration ───────────────────────────────────────────────
def test_generated_seed_loader_bakes_spec_and_compiles():
    canonical = cr.detect_canonical_rows(_ROUTES_REQUIRED, _MODELS)
    spec = cr.build_bootstrap_spec(canonical, _TABLES)
    src = bs.render_seed_data(_TABLES, spec)
    assert "_USER_BOOTSTRAP = [" in src
    assert "def _ensure_canonical_rows" in src
    assert "_ensure_canonical_rows()" in src           # invoked in seed_if_empty finally
    d = tempfile.mkdtemp()
    p = os.path.join(d, "seed_data.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(src)
    py_compile.compile(p, doraise=True)


def test_seed_loader_without_spec_is_backward_compatible():
    """No canonical rows detected → empty spec → the loader behaves exactly as pre-#72."""
    src = bs.render_seed_data(_TABLES)          # no bootstrap_spec arg
    assert "_USER_BOOTSTRAP = []" in src
    d = tempfile.mkdtemp()
    p = os.path.join(d, "seed_data.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(src)
    py_compile.compile(p, doraise=True)


def test_oauth_store_template_has_bootstrap_and_compiles():
    tmpl = (LLM / "multi_agent" / "runtime" / "oauth_as_templates"
            / "oauth_store.py.tmpl").read_text(encoding="utf-8")
    assert "def _bootstrap_user_rows" in tmpl
    assert "self._bootstrap_user_rows(conn, row" in tmpl   # called in create_user
    assert "user_bootstrap.json" in tmpl                   # reads the projected spec
    d = tempfile.mkdtemp()
    p = os.path.join(d, "oauth_store.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(tmpl)
    py_compile.compile(p, doraise=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
