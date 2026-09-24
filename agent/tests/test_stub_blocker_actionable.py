"""Guard: FIX #201 — the #173 stub-handler blocker message must be LANE-ACTIONABLE
for a FRAMEWORK-projected stub.

r10 walled here: the 3 flagged stubs were `_projected_*` handlers in main.py
(framework-owned, regenerated every cycle), but the remediation told the lane
to "replace the handler with a real query" — which the lane CAN'T do (it
doesn't edit projected handlers). #200 fixes the resolvable cases; the residual
is an endpoint with NO backing table (/api/activity). For a projected stub the
message must name the endpoint and tell the lane the thing it CAN do: declare
the backing table (so the projector reads it) or drop the endpoint. A LANE
custom stub keeps the original "replace with a real query" (it owns that file).
This is a message/routing fix — NOT a HARD-vs-SOFT change (still HARD).
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import stub_handler_blockers  # noqa: E402


def _backend(files: dict):
    d = Path(tempfile.mkdtemp())
    for name, src in files.items():
        (d / name).write_text(src)
    return d


_PROJECTED_STUB = '''\
from fastapi import FastAPI, Depends
app = FastAPI()

@app.get("/api/activity")
def _projected_get_api_activity_11(db=Depends(get_db), user=Depends(get_current_user)):
    return {"items": [], "total": 0}
'''

_LANE_STUB = '''\
from fastapi import APIRouter, Depends
router = APIRouter()

@router.get("/api/widgets")
def list_widgets(db=Depends(get_db)):
    return {"items": []}
'''


class StubBlockerMessageTests(unittest.TestCase):
    def test_projected_stub_message_is_lane_actionable(self):
        be = _backend({"main.py": _PROJECTED_STUB})
        blockers = stub_handler_blockers(be)
        self.assertEqual(len(blockers), 1)
        msg = blockers[0].lower()
        # names the endpoint and the lane-actionable remedy (declare table / drop)
        self.assertIn("/api/activity", blockers[0])
        self.assertTrue("declare" in msg or "backing table" in msg or "remove the endpoint" in msg)
        # must NOT tell the lane to edit the projected handler (it can't)
        self.assertNotIn("replace the placeholder-stub get handler with a real query", msg)

    def test_lane_custom_stub_keeps_replace_message(self):
        be = _backend({"custom_routes.py": _LANE_STUB})
        blockers = stub_handler_blockers(be)
        self.assertEqual(len(blockers), 1)
        msg = blockers[0].lower()
        # the lane owns custom_routes.py → "query the real table" is actionable
        self.assertIn("query", msg)
        self.assertIn("widgets", blockers[0])

    def test_no_stub_no_blocker(self):
        good = '''\
@app.get("/api/videos")
def _projected_get_api_videos_0(db=Depends(get_db)):
    rows = db.query(Video).limit(100).all()
    return {"items": [r for r in rows]}
'''
        be = _backend({"main.py": good})
        self.assertEqual(stub_handler_blockers(be), [])


if __name__ == "__main__":
    unittest.main()
