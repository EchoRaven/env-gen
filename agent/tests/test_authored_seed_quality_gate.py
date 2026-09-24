"""Fix #54 — authored-seed CONTENT-quality gate (HANDOFF 2026-07-02 §6.1 lever 1).

#41 proves the lane authored SOMETHING in app/backend/seed_data.json; run-33-class
outcomes show a token 2-row seed still ships as SUCCESS while the bar is populated,
realistic list screens (info density = the top visual-similarity lever). This gate
audits the authored CONTENT with near-zero-false-positive signals (word-boundary
placeholder markers ×2, sequential counter names ×3, total-row floor) and blocks
delivery — same non-waivable family as #41, recomputed each tick so a rewritten
seed self-clears. ENVGEN_SEED_QUALITY_GATE=0 disables; ENVGEN_SEED_MIN_TOTAL_ROWS
tunes the floor. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.deliverability import compute_deliverability  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.seed_audit import audit_authored_seed  # noqa: E402


def _realistic_seed(n_msgs=12):
    return {
        "users": [
            {"id": 1, "email": "demo@example.com", "name": "Ava Chen"},
            {"id": 2, "email": "boss@example.com", "name": "Marcus Webb"},
        ],
        "messages": [
            {"id": i, "user_id": 1, "subject": f"Quarterly sync notes {2020 + i}",
             "from_name": "Priya Nair", "is_read": bool(i % 2),
             "body": "Attaching the revised figures ahead of Thursday."}
            for i in range(1, n_msgs + 1)
        ],
    }


# ---------------------------------------------------------------- unit: audit
def test_realistic_seed_is_clean():
    assert audit_authored_seed(_realistic_seed()) == []


def test_thin_seed_flagged():
    issues = audit_authored_seed(_realistic_seed(n_msgs=1))
    assert any("structured row(s)" in i for i in issues)


def test_two_distinct_markers_flag_a_table():
    seed = _realistic_seed()
    seed["messages"][0]["subject"] = "lorem ipsum"
    issues = audit_authored_seed(seed)
    assert any("placeholder content" in i and "messages" in i for i in issues)


def test_single_marker_or_substring_does_not_flag():
    seed = _realistic_seed()
    # "lorem" alone = only ONE distinct hard marker; substrings never count.
    seed["messages"][0]["subject"] = "The lorem overhaul plan"
    assert audit_authored_seed(seed) == []


def test_domain_vocabulary_never_flags():
    """Review w6x6art4t: 'test'/'sample'/'bar'/'tbd' are ordinary domain words
    (LMS quizzes, commerce samples, coffee bars, tracker TBDs) — they must NOT
    be hard-gate markers at all."""
    seed = _realistic_seed()
    seed["messages"][0]["subject"] = "Chapter 3 test"
    seed["messages"][1]["subject"] = "Sample problems for the unit test"
    seed["messages"][2]["subject"] = "Venue: TBD — likely the coffee bar"
    assert audit_authored_seed(seed) == []


def test_realistic_string_ids_and_numbered_names_do_not_flag():
    """Review w6x6art4t: the draft sequential-name rule false-blocked the
    STANDARD LLM seed shape — string FK ids 'msg_1'..'msg_12' / 'user_1' — and
    legit numbered domain values ('Room 101', 'iPhone 15'). The rule is gone;
    these seeds must pass."""
    seed = _realistic_seed()
    for i, m in enumerate(seed["messages"], 1):
        m["id"] = f"msg_{i}"
        m["user_id"] = "user_1"
    seed["users"][0]["id"] = "user_1"
    seed["users"][1]["id"] = "user_2"
    seed["rooms"] = [{"id": i, "name": f"Room {100 + i}"} for i in range(1, 5)]
    assert audit_authored_seed(seed) == []


def test_min_rows_env_override(monkeypatch):
    monkeypatch.setenv("ENVGEN_SEED_MIN_TOTAL_ROWS", "2")
    assert audit_authored_seed(_realistic_seed(n_msgs=1)) == []


def test_garbage_shapes_are_tolerated():
    assert audit_authored_seed(None) == []


def test_string_only_rows_fail_the_floor():
    """Review w6x6art4t: {"messages": ["Welcome","Hello","Hi"]} passes #41's
    non-empty-list check yet seeds nothing — 0 structured rows must trip the
    floor (was skipped by the old `0 < total` condition)."""
    issues = audit_authored_seed({"messages": ["Welcome", "Hello", "Hi"],
                                  "cfg": {"k": "v"}, "users": "junk"})
    assert any("0 structured row(s)" in i for i in issues)


# ------------------------------------------------------- wiring: deliverability
def _quality_blockers(tmp_path, seed_obj):
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True, exist_ok=True)
    (app / "backend" / "seed_data.json").write_text(
        json.dumps(seed_obj), encoding="utf-8")
    hr = HubRegistry(tmp_path / "hubs")
    rep = compute_deliverability(hr, app, session_start_ts=0.0)
    return [b for b in (rep.blockers or []) if "authored seed quality" in b]


def test_thin_seed_blocks_delivery(tmp_path):
    assert _quality_blockers(tmp_path, _realistic_seed(n_msgs=1))


def test_realistic_seed_passes_gate(tmp_path):
    assert _quality_blockers(tmp_path, _realistic_seed()) == []


def test_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SEED_QUALITY_GATE", "0")
    assert _quality_blockers(tmp_path, _realistic_seed(n_msgs=1)) == []


def test_blocker_prose_does_not_collide_with_41_anchor(tmp_path):
    """The #41 canonical branch keys on 'authored seed missing'; #54's prose must
    never contain it (elif order in delivery_gate) — and must carry its own anchor."""
    (b,) = _quality_blockers(tmp_path, _realistic_seed(n_msgs=1))
    assert "authored seed missing" not in b.lower()
    assert "authored seed quality" in b.lower()


# --------------------------------------------------- wiring: token + dispatcher
def test_canonical_token_and_owner_wired():
    rt = ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    gate_src = (rt / "delivery_gate.py").read_text(encoding="utf-8")
    disp_src = (rt / "remediation_dispatcher.py").read_text(encoding="utf-8")
    assert '"authored seed quality" in low' in gate_src
    assert gate_src.index('"authored seed quality" in low') \
        < gate_src.index('"missing seed" in low'), "elif order: #54 before generic seed"
    assert '"deliverability_authored_seed_quality"' in gate_src
    # Review w6x6art4t (critical): these tokens are minted only by the DELIVERY
    # GATE, so their owner mapping must live in dispatch_gate_level_checks'
    # _GATE_OWNER map — an entry in dispatch_failing_checks' _CHECK_OWNER is
    # dead code (run-34's "NO remediation owner" would recur -> STUCK-ABORT).
    gate_owner_idx = disp_src.index("_GATE_OWNER = {")
    assert disp_src.index('"deliverability_authored_seed_quality"') > gate_owner_idx
    assert disp_src.index('"deliverability_missing_authored_seed"',
                          gate_owner_idx) > gate_owner_idx


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
