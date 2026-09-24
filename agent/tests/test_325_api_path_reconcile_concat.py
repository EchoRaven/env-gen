"""#325 — reconcile_frontend_api_paths shipped a BROKEN app (frontend trajectory review, r92).

The lane hand-authored the correct  request('/api/videos/' + id)  — a registered-path PREFIX
concatenated with an id. _API_CALL_PATH_RE captured the string literal '/api/videos/' (it
stops at the closing quote, ignoring the ` + id` that follows), _sub saw it as "unregistered
vs /api/videos", and STRIPPED the trailing slash → runtime GET /api/videos<ID> → 404. r92's
DELIVERED api.js had video-detail/like/save/share/comment/reply/follow all broken this way;
the reconcile fired 18x and the lane re-authored api.js 50+ times fighting it.

Fix: (a) never treat a pure trailing-slash difference as drift; (b) only rewrite a path that
is a COMPLETE call argument (closing quote followed by ) or ,), so a concatenation prefix is
left alone. The legitimate drift fix (extra segment: /api/posts/feed -> /api/feed) still works.
"""
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import reconcile_frontend_api_paths  # noqa: E402


def _run(src, registered):
    d = Path(tempfile.mkdtemp(prefix="apirecon325_"))
    (d / "api.js").write_text(src, encoding="utf-8")
    res = reconcile_frontend_api_paths(d, registered)
    return (d / "api.js").read_text(encoding="utf-8"), res


def test_concat_prefix_is_not_stripped():
    # the exact r92 shipping bug
    src = "export const getVideo = (id) => request('/api/videos/' + id);\n"
    out, res = _run(src, {"/api/videos", "/api/videos/{id}"})
    assert "request('/api/videos/' + id)" in out, out          # slash preserved
    assert res["rewritten"] == [], res


def test_concat_prefix_deeper_path_not_stripped():
    src = "export const likeVideo = (id) => request('/api/videos/' + id + '/like');\n"
    out, _ = _run(src, {"/api/videos", "/api/videos/{id}/like"})
    assert "request('/api/videos/' + id + '/like')" in out, out


def test_trailing_slash_only_call_left_alone():
    # a complete call that only differs by a trailing slash is NOT drift
    src = "export const feed = () => request('/api/feed/');\n"
    out, res = _run(src, {"/api/feed"})
    assert "request('/api/feed/')" in out, out
    assert res["rewritten"] == [], res


def test_real_extra_segment_drift_still_fixed():
    # the behaviour reconcile exists for: lane inserted an extra 'posts' segment
    src = "export const feed = () => request('/api/posts/feed');\n"
    out, res = _run(src, {"/api/feed"})
    assert "request('/api/feed')" in out, out
    assert any(c[1] == "/api/feed" for c in res["rewritten"]), res


def test_version_variant_drift_still_fixed():
    src = "export const feed = () => request('/api/feed');\n"
    out, res = _run(src, {"/api/v1/feed"})
    assert "request('/api/v1/feed')" in out, out


def test_registered_full_path_unchanged():
    src = "export const list = () => request('/api/videos');\n"
    out, res = _run(src, {"/api/videos"})
    assert "request('/api/videos')" in out and res["rewritten"] == []
