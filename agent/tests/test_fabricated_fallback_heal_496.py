"""#496 — HEAL↔CHECKER coverage gap for the fabricated-fallback delivery gate.

The CHECKER (frontend_audit.invented_field_fallback_blockers, #175) flags frontend member-field
fallbacks that render FABRICATED display data — `member || 'Live now'`, `? member : 'Big Name'` —
and trips `deliverability_fabricated_field_fallback`. netflix r66 wedged on exactly this: it shipped
`title.live_label || 'Live now'` (HeroBillboard.jsx, JSX-text) and `t.title || 'Title details'`
(TitleDetailModal.jsx, attribute); the deterministic heal must clear every site the checker flags.

The HEAL (repair_fabricated_fallbacks) now drives off WIDENED patterns that form a provable
SUPERSET of the checker (`_HEAL_EXPR` ⊇ the checker's member-access LHS): every checker OR/ternary
site is repaired → `(<expr> ?? '—')` / honest '—', so the round-trip invariant holds by construction
(run checker → run heal → run checker = 0). The heal ALSO cleans bare-identifier LHS (`x || 'Live
now'`) and the mirror ternary (`cond ? 'lit' : expr`) — forms the checker deliberately does NOT flag
— while the checker's proven-sound flag set stays untouched. The SAME literal classifier gates both,
so legitimate defaults (`count || '0'`, `|| ''`, `|| 'all'`) are never rewritten.
"""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    invented_field_fallback_blockers,
    repair_fabricated_fallbacks,
)


def _mk(tmp, files: dict) -> Path:
    """Write {relpath: content} under an app/frontend/src tree; return src dir."""
    src = Path(tmp) / "app" / "frontend" / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


def _wrap(expr_snippet: str) -> str:
    """A minimal, valid JSX component containing one render expression."""
    return (
        "import React from 'react';\n"
        "export default function C(props){\n"
        "  const { title, t, place, x, a, b, cond } = props;\n"
        f"  return <span>{expr_snippet}</span>;\n"
        "}\n"
    )


# ── (a) each NEWLY-COVERED form is rewritten so the checker no longer flags it ──────────────

def test_bare_identifier_lhs_rewritten():
    # `x || 'Live now'` — NON-member LHS. The checker never flagged a bare identifier; the heal
    # now cleans it proactively → `(x ?? '—')`, and the checker still flags 0.
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/C.jsx": _wrap("{x || 'Live now'}")})
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["C.jsx"], out
        after = (src / "components" / "C.jsx").read_text()
        assert "{(x ?? '—')}" in after, after
        assert "'Live now'" not in after
        assert invented_field_fallback_blockers(src) == []


def test_chain_lhs_rewritten():
    # `a.b || c.d || 'Big Name'` — compound chain. Only the LAST operand's fabricated fallback is
    # rewritten, PARENTHESIZED so the `??`/`||` mix stays valid JS: `a.b || (c.d ?? '—')`.
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/C.jsx": _wrap("{a.b || place.d || 'Big Name'}")})
        before = invented_field_fallback_blockers(src)
        assert len(before) == 1, before  # checker (member LHS) flags the chain's tail
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["C.jsx"], out
        after = (src / "components" / "C.jsx").read_text()
        assert "a.b || (place.d ?? '—')" in after, after
        assert "'Big Name'" not in after
        assert invented_field_fallback_blockers(src) == []


def test_jsx_text_member_rewritten_r66_hero():
    # r66 HeroBillboard.jsx:83 — `{title.live_label || 'Live now'}` (member LHS, JSX-text).
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/HeroBillboard.jsx": _wrap("{title.live_label || 'Live now'}")})
        assert len(invented_field_fallback_blockers(src)) == 1
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["HeroBillboard.jsx"], out
        after = (src / "components" / "HeroBillboard.jsx").read_text()
        assert "{(title.live_label ?? '—')}" in after, after
        assert invented_field_fallback_blockers(src) == []


def test_attribute_member_rewritten_r66_modal():
    # r66 TitleDetailModal.jsx:52 — `aria-label={t.title || 'Title details'}` (member LHS, attr).
    with tempfile.TemporaryDirectory() as tmp:
        body = (
            "export default function M(props){ const {t}=props;\n"
            "  return <div aria-label={t.title || 'Title details'} />; }\n"
        )
        src = _mk(tmp, {"components/TitleDetailModal.jsx": body})
        assert len(invented_field_fallback_blockers(src)) == 1
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["TitleDetailModal.jsx"], out
        after = (src / "components" / "TitleDetailModal.jsx").read_text()
        assert "aria-label={(t.title ?? '—')}" in after, after
        assert invented_field_fallback_blockers(src) == []


def test_ternary_false_branch_fake_rewritten():
    # `cond ? place.name : 'HI Point Lighthouse'` — checker-flagged ternary fake (lit in FALSE).
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/C.jsx": _wrap("{cond ? place.name : 'HI Point Lighthouse'}")})
        assert len(invented_field_fallback_blockers(src)) == 1
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["C.jsx"], out
        after = (src / "components" / "C.jsx").read_text()
        assert "{cond ? place.name : '—'}" in after, after
        assert "'HI Point Lighthouse'" not in after
        assert invented_field_fallback_blockers(src) == []


def test_ternary_true_branch_mirror_rewritten():
    # `cond ? 'Live now' : place.name` — MIRROR ternary the checker does NOT flag; heal cleans it.
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/C.jsx": _wrap("{cond ? 'Live now' : place.name}")})
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == ["C.jsx"], out
        after = (src / "components" / "C.jsx").read_text()
        assert "{cond ? '—' : place.name}" in after, after
        assert "'Live now'" not in after
        assert invented_field_fallback_blockers(src) == []


# ── (b) legitimate defaults the checker deliberately allows are LEFT UNCHANGED ───────────────

def test_legitimate_defaults_untouched():
    # count || '0' (honest zero), || '' (honest empty), || 'all'/'GET'/'default' (state/enum),
    # error message ('Failed to load'), asset path, hex color, honest state ('active') — the
    # checker flags NONE of these, so the heal (same classifier) rewrites NONE.
    legit = (
        "export default function L(props){\n"
        "  const {place, x, mode, method, status, msg, avatar, color, kind} = props;\n"
        "  const a = place.review_count || '0';\n"
        "  const b = x.name || '';\n"
        "  const c = mode || 'all';\n"
        "  const d = method || 'GET';\n"
        "  const e = status || 'active';\n"
        "  const f = msg || 'Failed to load account';\n"
        "  const g = avatar || '/assets/avatars/default.png';\n"
        "  const h = color || '#e50914';\n"
        "  const j = kind || 'N/A';\n"
        "  return <span>{a}{b}{c}{d}{e}{f}{g}{h}{j}</span>;\n"
        "}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/L.jsx": legit})
        assert invented_field_fallback_blockers(src) == []
        out = repair_fabricated_fallbacks(src)
        assert out.get("repaired") == [], out
        assert out.get("sites") == [], out
        assert (src / "components" / "L.jsx").read_text() == legit  # byte-identical


# ── (c) a clean file (no fallbacks at all) is byte-identical ─────────────────────────────────

def test_clean_file_byte_identical():
    clean = (
        "import React from 'react';\n"
        "export default function Clean({items}){\n"
        "  return <ul>{items.map((it) => <li key={it.id}>{it.title}</li>)}</ul>;\n"
        "}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/Clean.jsx": clean})
        out = repair_fabricated_fallbacks(src)
        assert out == {"repaired": [], "sites": []}, out
        assert (src / "components" / "Clean.jsx").read_text() == clean


# ── (d) idempotent: a second run changes nothing ────────────────────────────────────────────

def test_idempotent_second_run_no_change():
    mixed = _wrap(
        "{title.live_label || 'Live now'}"
        "{x || 'Title details'}"
        "{cond ? place.name : 'HI Point Lighthouse'}"
        "{cond ? 'Big Name' : place.name}"
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, {"components/C.jsx": mixed})
        first = repair_fabricated_fallbacks(src)
        assert first.get("repaired") == ["C.jsx"], first
        after_first = (src / "components" / "C.jsx").read_text()
        second = repair_fabricated_fallbacks(src)
        assert second.get("repaired") == [], second
        assert second.get("sites") == [], second
        assert (src / "components" / "C.jsx").read_text() == after_first


# ── (e) the invariant: checker → heal → checker = 0 flagged (round-trip) ─────────────────────

def test_roundtrip_checker_heal_checker_zero():
    files = {
        "components/HeroBillboard.jsx": _wrap("{title.live_label || 'Live now'}"),
        "components/TitleDetailModal.jsx": (
            "export default function M(props){ const {t}=props;\n"
            "  return <div aria-label={t.title || 'Title details'} />; }\n"
        ),
        "pages/Browse.jsx": _wrap(
            "{a.b || place.d || 'Big Name'}"
            "{cond ? place.name : 'HI Point Lighthouse'}"
        ),
        # legit defaults must survive the round-trip unflagged and unchanged
        "pages/Legit.jsx": _wrap("{place.review_count || '0'}{x.name || ''}"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk(tmp, files)
        before = invented_field_fallback_blockers(src)
        assert len(before) >= 3, before  # r66-shape: the two member sites + chain + ternary
        repair_fabricated_fallbacks(src)
        after = invented_field_fallback_blockers(src)
        assert after == [], after  # zero flagged after the heal — the round-trip invariant
        # legit file is byte-identical
        assert (src / "pages" / "Legit.jsx").read_text() == files["pages/Legit.jsx"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
