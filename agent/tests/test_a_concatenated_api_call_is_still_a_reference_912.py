r"""#912: the audit rejected the safest way to write the call.

`audit_ui_page` checks each declared `apis_used` path against the frontend source, replacing every
`{param}`/`:param` with a wildcard. The wildcard was ``[^/'"`\s)]*`` — it excluded quotes,
whitespace and `)`. That matches `${postId}` and `'+id+'`, and rejects this:

    '/api/titles/' + encodeURIComponent(id) + '/episodes'
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^ quotes, spaces AND parens

r153 declares `/api/titles/{id}/episodes`, `services/api.js:200` calls it exactly that way, and
today's audit reports *"declared API `/api/titles/{id}/episodes` never referenced in frontend src"*.

Measured over the corpus: **136 of 2476 declared API references (5.5%) are false** —
`/api/genres/{id}/titles` and `/api/titles/{id}/rating` the recurring pair, both written as
`'/api/genres/' + genreId + '/titles'`. After the fix **98 remain**, so the check keeps its power;
a widening that returned 0 would have replaced a false alarm with a blind spot.

A soft miss does not block, but it feeds `pages_pending` and the remediation prompt — the lane is
told to wire a call it already wrote, which is the churn class #910b measures.
"""
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _audit(call_src: str, declared: str):
    src = Path(tempfile.mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "App.jsx").write_text(
        '<Routes><Route path="/x" element={<XPage />} /></Routes>', encoding="utf-8")
    (src / "pages" / "XPage.jsx").write_text(
        "export default function XPage(){ return <div onClick={()=>{}}>x</div> }", encoding="utf-8")
    (src / "services" / "api.js").write_text(call_src, encoding="utf-8")
    page = {"name": "x_page", "route": "/x", "component": "XPage", "apis_used": [declared],
            "path": "app/frontend/src/pages/XPage.jsx"}
    _ok, missing = fa.audit_ui_page(src, page)
    return [m for m in missing if "never referenced" in m]


def test_encode_uri_component_concatenation_counts_as_a_reference():
    """★ r153's actual line, verbatim."""
    assert not _audit(
        "export const eps = (id) => request('/api/titles/' + encodeURIComponent(id) + '/episodes');",
        "/api/titles/{id}/episodes")


def test_plain_concatenation_still_counts():
    """The corpus's most common false negative: `'/api/genres/' + genreId + '/titles'`."""
    assert not _audit(
        "export const g = (genreId) => request('/api/genres/' + genreId + '/titles');",
        "/api/genres/{id}/titles")


def test_a_template_literal_still_counts():
    """Non-regression: the shape the old wildcard was written for."""
    assert not _audit(
        "export const like = (postId) => fetch(`/api/posts/${postId}/like`);",
        "/api/posts/{id}/like")


def test_a_colon_param_declaration_still_counts():
    assert not _audit(
        "export const g = (id) => fetch('/api/things/' + id + '/detail');",
        "/api/things/:thingId/detail")


def test_a_genuinely_absent_api_is_still_reported():
    """★ The half that keeps the check honest. Widening a probe until nothing fails is not a fix —
    98 soft misses survive on the corpus, which is why this one has to fail."""
    assert _audit("export const other = () => fetch('/api/unrelated');",
                  "/api/titles/{id}/episodes")


def test_the_wildcard_does_not_cross_a_slash():
    """A param stands for ONE segment. `/api/a/{id}/b` must not match `/api/a/x/y/b`, or the probe
    would accept a different endpoint as evidence."""
    assert _audit("export const g = () => fetch('/api/a/x/y/b');", "/api/a/{id}/b")


def test_the_wildcard_is_bounded():
    """Unbounded `[^/\\n]*` between two literals invites backtracking on a minified bundle; the
    bound is what makes this safe to run over every source file each tick."""
    import inspect
    src = inspect.getsource(fa.audit_ui_page)
    assert "[^/\\n]{0,80}" in src, "the wildcard must stay bounded"


def test_the_declared_path_is_still_anchored_on_its_literals():
    """Only the param becomes a wildcard — the surrounding literal segments must still have to
    appear, or every declared API would match any source."""
    assert _audit("export const g = (id) => fetch('/api/OTHER/' + id + '/episodes');",
                  "/api/titles/{id}/episodes")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
