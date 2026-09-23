r"""#1202rs: seeded people whose addresses are on RFC 2606's reserved documentation domain.

`example.com` exists so that nothing real uses it. A seeded `alice@example.com` therefore tells
any agent reading the database that its people are invented — and this is the single most
recurrent deterministic realism tell in the corpus, with nothing ever checking it.

Measured across four domains, six runs, every one of them positive: instagram run73 carries 20
such addresses, tiktok-r129 35, netflix-local-r30 11, googlemaps gmrun4 8, r130 and r131 6
each. Eight of eight SUCCESSFUL instagram deliveries carry it, and no other deterministic tell
(picsum, John Doe, lorem, +1-555) appears in any of them.

It also reproduces on demand: in a controlled A/B this session, the arm WITHOUT the realism
contract seeded 8 `@example.com` addresses and the arm with it seeded none. The contract works
on this one — and a prompt rule is not enforcement, which is what the gate is for.

Narrow by design: the RFC-reserved names plus the two hosts that mean "nowhere". A product's
own invented domain is exactly what a clone's users SHOULD have and is never flagged.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.deliverability import (  # noqa: E402
    _reserved_email_domain_blockers_1202rs as gate)


def _app(tmp_path, files):
    app = tmp_path / "app"
    for rel, body in files.items():
        f = app / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return app


def test_a_seeded_reserved_address_is_caught(tmp_path):
    app = _app(tmp_path, {"backend/seed_data.json":
                          json.dumps({"users": [{"email": "alice@example.com"}]})})
    out = gate(app)
    assert out and "seed_data.json" in out[0]


def test_the_products_own_invented_domain_passes(tmp_path):
    """This is what a clone's users should have; flagging it would fight the fix."""
    app = _app(tmp_path, {"backend/seed_data.json": json.dumps({"users": [
        {"email": "maya@lumenfeed.com"}, {"email": "admin@acme-video.io"}]})})
    assert gate(app) == []


def test_the_sibling_reserved_names_count(tmp_path):
    for dom in ("@example.org", "@example.net", "@test.com", "@localhost"):
        app = _app(tmp_path / dom.strip("@."),
                   {"backend/seed_data.json": json.dumps({"u": [{"email": "a" + dom}]})})
        assert gate(app), dom


def test_the_frontend_is_scanned_too(tmp_path):
    """A prefilled login form ships the address as surely as the database does."""
    app = _app(tmp_path, {"frontend/src/pages/LoginPage.jsx":
                          "const [email, setEmail] = useState('demo@example.com');"})
    assert gate(app)


def test_node_modules_is_skipped(tmp_path):
    app = _app(tmp_path, {"frontend/src/node_modules/pkg/index.js":
                          "// contact a@example.com"})
    assert gate(app) == []


def test_a_clean_app_passes(tmp_path):
    app = _app(tmp_path, {"backend/seed_data.json":
                          json.dumps({"users": [{"email": "zach@lumenfeed.com"}]})})
    assert gate(app) == []


def test_the_message_says_why_the_domain_is_reserved(tmp_path):
    """A reader who thinks example.com is merely unfashionable will substitute example.org."""
    app = _app(tmp_path, {"backend/seed_data.json":
                          json.dumps({"u": [{"email": "a@example.com"}]})})
    assert "RFC 2606" in gate(app)[0]


def test_it_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_RESERVED_EMAIL_GATE", "0")
    app = _app(tmp_path, {"backend/seed_data.json":
                          json.dumps({"u": [{"email": "a@example.com"}]})})
    assert gate(app) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert src.count("blockers.extend(_reserved_email_domain_blockers_1202rs") == 1
