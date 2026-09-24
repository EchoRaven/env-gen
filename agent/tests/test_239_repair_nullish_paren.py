"""#239 (tiktok r29 NO-CONVERGENCE abort, build-break): the framework's OWN #175
fabricated-fallback repair rewrote the LAST `|| 'lit'` of a `||`-chain to
`?? '—'`, producing `cur.title || cur.description ?? '—'` — JS forbids mixing
?? with || without parens, so vite/esbuild rejected it → build failed →
verification_checklist_not_ready → abort. The repair must ALWAYS parenthesize
the ?? replacement so it is valid inside any || / && chain."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (  # noqa: E402
    repair_fabricated_fallbacks,
)

_INVALID_MIX = re.compile(r"\|\|[^()]*\?\?|&&[^()]*\?\?")


def _repair(tmp_path, body):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "P.jsx").write_text(body)
    res = repair_fabricated_fallbacks(src)
    return (src / "P.jsx").read_text(), res


def test_chained_or_gets_parenthesized_no_syntax_error(tmp_path):
    # r29's exact shape: cur.title || cur.description || 'fabricated'
    out, res = _repair(tmp_path, "<div>{cur.title || cur.description || 'Amazing Title'}</div>")
    assert res["repaired"] == ["P.jsx"]
    assert "(cur.description ?? '—')" in out
    assert not _INVALID_MIX.search(out), f"invalid ??/|| mix survived: {out}"


def test_standalone_still_repaired_and_valid(tmp_path):
    out, res = _repair(tmp_path, "<span>{place.rating || '4.5'}</span>")
    assert "(place.rating ?? '—')" in out
    assert not _INVALID_MIX.search(out)


def test_and_chain_also_safe(tmp_path):
    out, _ = _repair(tmp_path, "<div>{ok && user.name || 'Anonymous'}</div>")
    assert not _INVALID_MIX.search(out)


def test_non_fabricated_literal_untouched(tmp_path):
    # a real domain default is NOT rewritten (only fabricated placeholders)
    body = "<div>{status || 'active'}</div>"
    out, res = _repair(tmp_path, body)
    # 'active' is a short enum-ish token; if untouched, no ?? appears
    if not res["repaired"]:
        assert out == body


def test_multiple_sites_one_line(tmp_path):
    out, _ = _repair(
        tmp_path,
        "<div>{a.x || 'Fabricated One'}{b.y || 'Fabricated Two'}</div>")
    assert not _INVALID_MIX.search(out)
