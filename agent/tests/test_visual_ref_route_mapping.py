"""Reference images named <appname>_<screen> must map to the app's <screen> route.

outlook run #8: the visual gate was blind because map_reference_screens matched the
FULL stem ('outlook_inbox') against routes — so only 2/9 outlook references mapped
('outlook_inbox'->/messages wrongly, login), and inbox/calendar/landing mapped to
nothing -> the gate judged ~0 screens and never caught the bad UI. The mapper now also
tries the TRAILING segments (drops the app-name prefix). LOCAL-ONLY."""
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; LLM = ROOT/"env_generator"/"llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path: sys.path.insert(0, str(_p))
from multi_agent.runtime.visual_fidelity import map_reference_screens  # noqa

def _refs(names):
    d = Path(tempfile.mkdtemp())
    out = []
    for n in names:
        f = d / (n + ".png"); f.write_bytes(b"\x89PNG\r\n"); out.append(str(f))
    return out

ROUTES = {"/", "/login", "/signup", "/inbox", "/calendar", "/contacts", "/events"}

def test_appname_prefixed_refs_map_to_screen_routes():
    refs = _refs(["outlook_inbox", "outlook_calendar", "outlook_landing", "outlook_login"])
    m = {s["name"]: s.get("route") for s in map_reference_screens(refs, ROUTES)}
    assert m["outlook_inbox"] == "/inbox"        # NOT /messages
    assert m["outlook_calendar"] == "/calendar"
    assert m["outlook_landing"] == "/"
    assert m["outlook_login"] == "/login"

def test_plain_names_still_map():  # no app prefix → still works
    m = {s["name"]: s.get("route") for s in map_reference_screens(_refs(["inbox", "calendar", "contacts"]), ROUTES)}
    assert m["inbox"] == "/inbox" and m["calendar"] == "/calendar" and m["contacts"] == "/contacts"

def test_unmappable_ref_is_skipped_not_failed():
    m = {s["name"]: s.get("route") for s in map_reference_screens(_refs(["outlook_compose_reply"]), ROUTES)}
    assert m["outlook_compose_reply"] is None   # modal state, no route → skipped (route=None)

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
