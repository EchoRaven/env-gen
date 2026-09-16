"""#1202ph: the fabricated-fallback heal never turns valid lane code into a crash.

`_HEAL_EXPR` did not know optional chaining and the heal could anchor right after a `.`, so
`user?.username || user?.name || 'Haibo Tong'` became `user?.username || user?.(name ?? '—')` — an
optional CALL of `user`, a TypeError whenever `user` exists — and `a().foo.bar || 'x'` became
`a().(foo.bar ?? '—')`, a syntax error. 175 crash-shaped rewrites across 18 recent runs; it is the
true cause of r111's blank /comments route (`aria-label={video?.(caption ?? '—')}`), which was
blamed on the lane. Drives the real heal over a real file.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import repair_fabricated_fallbacks  # noqa: E402


def _heal(tmp_path, src):
    d = tmp_path / "src"
    d.mkdir()
    (d / "P.jsx").write_text(src)
    repair_fabricated_fallbacks(d)
    return (d / "P.jsx").read_text()


def test_an_optional_chain_is_wrapped_whole(tmp_path):
    out = _heal(tmp_path, "const n = user?.username || user?.name || 'Haibo Tong';\n")
    assert "user?.(" not in out, out
    assert "(user?.name ?? '—')" in out, out


def test_r111_the_aria_label_is_not_turned_into_a_call(tmp_path):
    out = _heal(tmp_path, "<div aria-label={video?.caption || 'TikTok video'} />\n")
    assert "video?.(" not in out, out


def test_a_chain_it_cannot_anchor_is_left_alone_rather_than_broken(tmp_path):
    out = _heal(tmp_path, "const x = a().foo.bar || 'Some Label';\n")
    assert "a().(" not in out, out


def test_a_plain_member_chain_is_still_healed(tmp_path):
    out = _heal(tmp_path, "const n = place.name || 'HI Point Montara Lighthouse';\n")
    assert "(place.name ?? '—')" in out, out
