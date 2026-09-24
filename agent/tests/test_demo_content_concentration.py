"""FIX #74 — demo-content concentration (outlook run-62: the demo user's inbox showed ~1 email
because 30 messages were spread 3/user across 10 users). After seeding, the FIRST user (the
demo identity every gate + first-load uses) is CLONE-concentrated to _DEMO_FLOOR rows per
owner-scoped content table, FK-safe. Adversarial-review-hardened: (a) SINGLETON per-user tables
(settings/profile) are skipped — cloning them makes look-alikes or, under UNIQUE(user_id),
per-boot fail-churn; (b) a clone's owner-scoped child FK is remapped onto the demo's SAME-KIND
child (a donor's Inbox message → the demo's Inbox), so the INBOX screen actually fills instead of
mail scattering round-robin into Sent/Trash. Runs against a real SQLite DB. LOCAL-ONLY.
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_seed_data, render_models  # noqa: E402

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "email", "type": "String"}, {"name": "name", "type": "String"},
        {"name": "password_hash", "type": "String"}, {"name": "tenant_id", "type": "String"}]},
    "folders": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "user_id", "type": "Integer", "references": "users.id"},
        {"name": "name", "type": "Text"}, {"name": "kind", "type": "Text"}]},
    "messages": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "user_id", "type": "Integer", "references": "users.id"},
        {"name": "folder_id", "type": "Integer", "references": "folders.id"},
        {"name": "subject", "type": "Text"}, {"name": "body", "type": "Text"}]},
    "settings": {"columns": [
        {"name": "id", "type": "Integer", "primary_key": True},
        {"name": "user_id", "type": "Integer", "references": "users.id"},
        {"name": "theme", "type": "String"}]},
}
# folders is a canonical/structural table (a handler references Folder.kind=='sent') → the
# concentrator SKIPS it (containers are navigation, not feed content). Model that here.
_BOOTSTRAP = [{"table": "folders", "owner_col": "user_id", "match_col": "kind",
               "literal": "sent", "row": {"name": "Sent", "kind": "sent"}}]

# Spread: demo (user 1) owns 2 inbox messages; users 2 & 3 own 4 inbox messages each. Each
# user has an Inbox (kind=inbox) + a Sent (kind=sent) folder. A settings singleton (1/user).
_SEED = {
    "users": [{"id": i, "email": f"u{i}@example.com", "name": f"U{i}"} for i in (1, 2, 3)],
    "folders": [
        {"id": 1, "user_id": 1, "name": "Inbox", "kind": "inbox"},
        {"id": 2, "user_id": 1, "name": "Sent", "kind": "sent"},
        {"id": 3, "user_id": 2, "name": "Inbox", "kind": "inbox"},
        {"id": 4, "user_id": 2, "name": "Sent", "kind": "sent"},
        {"id": 5, "user_id": 3, "name": "Inbox", "kind": "inbox"},
        {"id": 6, "user_id": 3, "name": "Sent", "kind": "sent"}],
    "messages": (
        [{"id": i, "user_id": 1, "folder_id": 1, "subject": f"demo {i}", "body": "x"} for i in (1, 2)]
        + [{"id": 2 + i, "user_id": 2, "folder_id": 3, "subject": f"u2 {i}", "body": "x"} for i in range(1, 5)]
        + [{"id": 6 + i, "user_id": 3, "folder_id": 5, "subject": f"u3 {i}", "body": "x"} for i in range(1, 5)]),
    "settings": [{"id": i, "user_id": i, "theme": "light"} for i in (1, 2, 3)],
}


def _boot(tmp_path, seed_json):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod

    src = render_seed_data(_TABLES, _BOOTSTRAP)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    (seed_dir / "seed_data.py").write_text(src, encoding="utf-8")
    (seed_dir / "seed_data.json").write_text(json.dumps(seed_json), encoding="utf-8")

    models_mod = types.ModuleType("models")
    exec(compile(render_models(_TABLES), "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    Base.metadata.create_all(eng)

    ns = {"__file__": str(seed_dir / "seed_data.py")}
    exec(compile(src, str(seed_dir / "seed_data.py"), "exec"), ns)
    ns["seed_if_empty"]()
    return db_mod.SessionLocal(), models_mod


def _teardown():
    for m in ("database", "models"):
        sys.modules.pop(m, None)


def test_concentrates_demo_to_floor_fk_safe_and_kind_aware(tmp_path):
    s, m = _boot(tmp_path, _SEED)
    try:
        demo_msgs = s.query(m.Message).filter(m.Message.user_id == 1).all()
        # concentrated to the floor (was 2)
        assert len(demo_msgs) >= 8, f"demo should reach the floor, got {len(demo_msgs)}"
        # FK-SAFE: every demo message references a folder the DEMO owns (never a donor's)
        demo_folder_ids = {f.id for f in s.query(m.Folder).filter(m.Folder.user_id == 1).all()}
        assert all(msg.folder_id in demo_folder_ids for msg in demo_msgs), \
            "a cloned message references a non-demo folder (cross-user FK leak)"
        # KIND-AWARE: donors' messages were all in an INBOX-kind folder → clones land in the
        # demo's INBOX (id=1), so the inbox screen fills (not scattered into Sent).
        inbox = next(f.id for f in s.query(m.Folder).filter(m.Folder.user_id == 1).all()
                     if f.kind == "inbox")
        assert all(msg.folder_id == inbox for msg in demo_msgs), \
            "cloned inbox mail must file into the demo's INBOX, not round-robin"
        # DONORS PRESERVED: never re-owned/removed — cross-user tests keep their data.
        assert s.query(m.Message).filter(m.Message.user_id == 2).count() == 4
        assert s.query(m.Message).filter(m.Message.user_id == 3).count() == 4
    finally:
        s.close(); _teardown()


def test_singleton_table_is_not_concentrated(tmp_path):
    """settings is 1-row-per-user → NOT feed content. Cloning it would make 8 look-alikes or
    (under a UNIQUE) churn every boot. The demo must still own exactly its 1 settings row."""
    s, m = _boot(tmp_path, _SEED)
    try:
        assert s.query(m.Setting).filter(m.Setting.user_id == 1).count() == 1, \
            "singleton settings must not be cloned"
        assert s.query(m.Setting).count() == 3, "no phantom settings rows created"
    finally:
        s.close(); _teardown()


def test_structural_folder_table_untouched(tmp_path):
    """folders is a canonical/structural container (in _USER_BOOTSTRAP) → skipped: the demo
    keeps exactly its seeded folders, never cloned copies."""
    s, m = _boot(tmp_path, _SEED)
    try:
        assert s.query(m.Folder).filter(m.Folder.user_id == 1).count() == 2
    finally:
        s.close(); _teardown()


def test_idempotent_second_boot(tmp_path):
    s, m = _boot(tmp_path, _SEED)
    n1 = s.query(m.Message).filter(m.Message.user_id == 1).count()
    s.close(); _teardown()
    # second boot on the SAME db file: floor already met → no further clones
    s2, m2 = _boot(tmp_path, _SEED)
    try:
        n2 = s2.query(m2.Message).filter(m2.Message.user_id == 1).count()
        assert n2 == n1, f"floor-gated concentration must be idempotent ({n1} -> {n2})"
    finally:
        s2.close(); _teardown()


def test_single_user_seed_no_self_duplication(tmp_path):
    """One user, no donors → the demo already owns all there is; must NOT self-duplicate its
    own rows into look-alikes."""
    one = {"users": [{"id": 1, "email": "solo@example.com", "name": "Solo"}],
           "folders": [{"id": 1, "user_id": 1, "name": "Inbox", "kind": "inbox"}],
           "messages": [{"id": 1, "user_id": 1, "folder_id": 1, "subject": "only", "body": "x"}],
           "settings": [{"id": 1, "user_id": 1, "theme": "light"}]}
    s, m = _boot(tmp_path, one)
    try:
        assert s.query(m.Message).filter(m.Message.user_id == 1).count() == 1
    finally:
        s.close(); _teardown()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
