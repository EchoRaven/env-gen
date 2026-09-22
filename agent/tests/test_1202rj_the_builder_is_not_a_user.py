r"""#1202rj: the account that BUILT the env is not one of its users.

An environment is a place an AI agent is put to work; the moment it can tell the place was
generated, the evaluation is over. The operator's own identity is the sharpest of those tells,
and this corpus ships it by TWO unrelated paths:

  transcription   design-prep transcribes a reference screenshot, the screenshot was taken from
                  the operator's own signed-in account, and #778 tells the lane to render
                  transcribed `copy` character for character. `haibotong7` -- the operator's
                  real handle -- reached the served app in r127, r128, r129 and r131, rendered
                  as the signed-in user of a generated TikTok clone.

  build identity  nothing to do with screenshots: netflix-local-r30's LoginPage.jsx and
                  googlemaps-r16's App.jsx hardcode `haibot2@illinois.edu` -- the git commit
                  author on this machine -- as the default signed-in email, across 10 files in
                  two unrelated environments.

#1202ri splits chrome copy from data slots so the first path stops producing it. This gate is
the backstop, and it is at the EXIT rather than on either path, because a harm with two
producing branches needs the guard at their common descendant (#934) -- and because a prompt
rule is not enforcement: this same lane already carried "never ship fake data" while shipping
50 picsum URLs in r130.

Found by the detector, not by me: I validated it against a baseline that said netflix and
googlemaps were clean, because I had only ever grepped for `haibotong`. They were not clean.
The baseline was wrong, not the detector.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import deliverability as D  # noqa: E402


def _app(tmp_path, files):
    app = tmp_path / "app"
    for rel, body in files.items():
        f = app / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return app


def test_the_r127_shape_is_caught(tmp_path, monkeypatch):
    """A handle transcribed from the operator's own profile screenshot."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"frontend/src/pages/ProfileOwnPage.jsx":
                          "export default () => <span>haibotong7</span>;"})
    out = D._operator_identity_blockers_1202rj(app)
    assert out and "ProfileOwnPage.jsx" in out[0]


def test_the_netflix_shape_is_caught(tmp_path, monkeypatch):
    """A build-identity email hardcoded as the default signed-in user."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibot2"])
    app = _app(tmp_path, {"frontend/src/components/LoginPage.jsx":
                          "const email = q.get('email') || 'haibot2@illinois.edu';"})
    assert D._operator_identity_blockers_1202rj(app)


def test_the_seed_is_scanned_too(tmp_path, monkeypatch):
    """The leak reaches a browser through the database as readily as through JSX."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibot2"])
    app = _app(tmp_path, {"backend/seed_data.json":
                          json.dumps({"users": [{"email": "haibot2@illinois.edu"}]})})
    assert D._operator_identity_blockers_1202rj(app)


def test_a_clean_app_is_clean(tmp_path, monkeypatch):
    """r130's shape. A gate that fires on everything protects nothing."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong", "haibot2"])
    app = _app(tmp_path, {
        "frontend/src/pages/ProfileOwnPage.jsx": "export default () => <span>{user.handle}</span>;",
        "backend/seed_data.json": json.dumps({"users": [{"username": "khaby.lame"}]})})
    assert D._operator_identity_blockers_1202rj(app) == []


def test_build_metadata_is_not_scanned(tmp_path, monkeypatch):
    """design/ carries the build PATH and never reaches a browser; r30 and r16 both have it
    there. Flagging it would send a lane after something no visitor can see."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = tmp_path / "app"
    app.mkdir()
    d = tmp_path / "design"
    d.mkdir()
    (d / "verdict.json").write_text('{"screenshot": "/data/common/haibotong/x.png"}',
                                    encoding="utf-8")
    assert D._operator_identity_blockers_1202rj(app) == []


def test_node_modules_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"frontend/src/node_modules/pkg/index.js": "// haibotong"})
    assert D._operator_identity_blockers_1202rj(app) == []


def test_no_identity_means_no_verdict(tmp_path, monkeypatch):
    """On a machine whose identity cannot be read, blocking every build would be worse."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: [])
    app = _app(tmp_path, {"frontend/src/App.jsx": "const e = 'haibot2@illinois.edu';"})
    assert D._operator_identity_blockers_1202rj(app) == []


def test_short_tokens_are_never_used(monkeypatch):
    """A 3-letter $USER would match inside ordinary words and block every app."""
    monkeypatch.setenv("USER", "bob")
    monkeypatch.setenv("LOGNAME", "bob")
    assert "bob" not in D._operator_identity_1202rj()


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    monkeypatch.setenv("ENVGEN_OPERATOR_IDENTITY_GATE", "0")
    app = _app(tmp_path, {"frontend/src/App.jsx": "// haibotong7"})
    assert D._operator_identity_blockers_1202rj(app) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    """#1202 ratchet: a gate nothing calls gates nothing."""
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert "_operator_identity_blockers_1202rj(app_root)" in src
    assert src.count("blockers.extend(_operator_identity_blockers_1202rj") == 1


# --- #1202rk: a comment is not a render --------------------------------------------------

def test_a_comment_mention_is_reported_as_a_comment(tmp_path, monkeypatch):
    """Still reported -- a build identity in a comment is a dev trace, and usually the fossil
    of a literal that WAS rendered until someone bound it. But calling it a render sends the
    lane looking for something no visitor can see."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"frontend/src/A.jsx":
                          "// never hardcode haibotong7 -- bind it\n"
                          "export default () => <b>{u.handle}</b>;"})
    out = D._operator_identity_blockers_1202rj(app)
    assert out and "comments only" in out[0] and "RENDER it to visitors" not in out[0]


def test_a_real_render_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"frontend/src/B.jsx": "export default () => <b>haibotong7</b>;"})
    out = D._operator_identity_blockers_1202rj(app)
    assert "RENDER it to visitors" in out[0]


def test_a_url_containing_slashes_is_not_mistaken_for_a_comment(tmp_path, monkeypatch):
    """The stripper only removes `//` at line start; a URL inside a string stays live, which
    is the safe direction -- it may call a comment live, never the reverse."""
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"frontend/src/C.jsx":
                          "const u = 'https://cdn.example/haibotong7.jpg';"})
    assert "RENDER it to visitors" in D._operator_identity_blockers_1202rj(app)[0]


def test_a_python_comment_counts_too(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: ["haibotong"])
    app = _app(tmp_path, {"backend/seed.py": "# seeded by haibotong7 originally\nROWS = []"})
    out = D._operator_identity_blockers_1202rj(app)
    assert out and "comments only" in out[0]
