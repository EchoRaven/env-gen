"""#524 (netflix r94, 2026-08-06) — the deliver-tail fabricated-field gate must HEAL-then-CHECK.

GROUND TRUTH: r94 looped forever in the deliver-tail — the SOUND deliverability_fabricated_
field_fallback checker rejected the SAME 5 lane `x || 'Literal'` lines 48x ("FRONTEND LANE
IS EFFECTIVELY DARK … rejected deliver_project 7+ times on the SAME 5 fabricated-fallback
lines"), and it never delivered. The deterministic repair_fabricated_fallbacks HEAL existed
but ran ONLY in the build-time heal pipeline (heal_pipeline.py:945) — not at the deliver-tail
gate (deliverability.py). So fabricated `||` authored LATE by a lane that then goes dark
never got healed → permanent rejection. FIX #524: `_invented_field_blockers` (the deliver-
tail gate check) now runs `repair_fabricated_fallbacks(frontend/src)` FIRST, then the
checker → `heal → check = 0 flagged BY CONSTRUCTION`, independent of the lane. The heal
rewrites `x || 'Literal'` → `(x ?? '—')` (honest) — the SOUND checker is untouched.

These tests lock: the deliver-tail check heals-then-clears a fabricated `||`; the file is
actually rewritten to honest '—'; and an honest fallback is left alone."""
from pathlib import Path
from env_generator.llm_generator.multi_agent.runtime.deliverability import _invented_field_blockers


def _mk_app(tmp, page_body):
    src = Path(tmp) / "frontend" / "src" / "pages"
    src.mkdir(parents=True, exist_ok=True)
    (src / "BrowseHomePage.jsx").write_text(page_body, encoding="utf-8")
    return Path(tmp)


def test_deliver_tail_heals_then_clears_fabricated(tmp_path):
    app = _mk_app(tmp_path, "export default function P(){ const x = gg.name || 'Genre'; "
                            "const y = title.maturity_rating || 'TV-14'; return null; }\n")
    blockers = _invented_field_blockers(app)   # heal-then-check
    assert blockers == [], f"deliver-tail gate should be clear after heal (#524), got: {blockers}"
    # the file was actually rewritten to honest '—' (fabricated literals gone)
    txt = (app / "frontend" / "src" / "pages" / "BrowseHomePage.jsx").read_text()
    assert "'Genre'" not in txt and "'TV-14'" not in txt, "fabricated literals not stripped:\n" + txt
    assert "?? '—'" in txt or "?? '—'" in txt, "expected honest '—' rewrite:\n" + txt


def test_honest_fallback_left_alone(tmp_path):
    # honest defaults ('0', '', '—') must NOT be rewritten (classifier is shared + sound)
    app = _mk_app(tmp_path, "export default function P(){ const c = r.count || '0'; "
                            "const e = r.label || ''; return null; }\n")
    blockers = _invented_field_blockers(app)
    assert blockers == []
    txt = (app / "frontend" / "src" / "pages" / "BrowseHomePage.jsx").read_text()
    assert "r.count || '0'" in txt, "honest '0' fallback must be preserved:\n" + txt


def test_no_frontend_dir_returns_empty(tmp_path):
    assert _invented_field_blockers(tmp_path) == []   # best-effort, never raises


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
