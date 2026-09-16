"""#1202or: the framework's public list must not advertise a route its own handler denies.

`_FW_PUBLIC_API_1202KH` is a union that never shrinks — deliberately, since the projector sees
only the endpoints of the current cycle. But `_reproject_stale_auth_1202jt` drops and rebuilds a
handler whose auth moved, so a route can gain `Depends(get_current_user)` while its public entry
is immortal: the guard then reports the route as public and the handler 401s anyway, which is the
logged-out-landing-page signature #1202kh exists to remove. Measured across 12 delivered
backends: 15 of 96 listed entries (16%) name a handler that demands a user.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import refresh_public_api_1202kh  # noqa: E402

_SRC = '''from fastapi import Depends, FastAPI
app = FastAPI()

@app.get("/api/videos")
def _projected_get_api_videos_0(db=Depends(get_db), user=Depends(get_current_user)):
    return {"items": []}

@app.get("/api/sounds")
def _projected_get_api_sounds_1(db=Depends(get_db)):
    return {"items": []}

_FW_PUBLIC_API_1202KH = [
    ('GET', '/api/videos'),
    ('GET', '/api/sounds'),
    ('GET', '/api/lane_route'),
]
'''


def _listed(src):
    import ast
    body = src[src.index("_FW_PUBLIC_API_1202KH = [") + len("_FW_PUBLIC_API_1202KH = "):]
    return [tuple(t) for t in ast.literal_eval(body[:body.index("]") + 1])]


def test_an_entry_the_same_file_contradicts_is_dropped():
    out = refresh_public_api_1202kh(_SRC, [])
    listed = [p for _m, p in _listed(out)]
    assert "/api/videos" not in listed          # its handler takes an actor
    assert "/api/sounds" in listed              # no actor: genuinely public
    assert "/api/lane_route" in listed          # no projected handler here: fail open


def test_a_new_public_route_is_still_added():
    out = refresh_public_api_1202kh(_SRC, [("GET", "/api/feed")])
    listed = [p for _m, p in _listed(out)]
    assert "/api/feed" in listed and "/api/sounds" in listed


def test_a_consistent_file_is_returned_untouched():
    src = _SRC.replace(", user=Depends(get_current_user)", "")
    assert refresh_public_api_1202kh(src, []) is src
