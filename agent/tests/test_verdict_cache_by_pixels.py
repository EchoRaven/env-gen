"""FIX #142 — per-screen verdict cache keyed by capture content hash.

run-65 M4 live evidence (#141b history made it provable): the last 3 explore
captures were BYTE-IDENTICAL (same md5) yet the judge scored them 0.00 then
0.30 — ±0.3 noise on identical pixels. That noise (1) phantom-resets #138
plateau tracking ("improvement" that is pure luck), (2) makes #129
sticky-pass luck-dependent near the threshold, (3) burns vision calls
re-judging unchanged screens.

Fix: run_visual_fidelity accepts verdict_cache (dict). A screen whose
capture bytes are unchanged reuses its cached verdict — identical pixels,
identical score, deterministically. The gate owns the cache per milestone
(reset_for_milestone clears it). Pixels change → md5 changes → re-judged.
"""
import asyncio
import sys
import threading
import http.server
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_PAGE = (b"<!doctype html><html><body><div id='root'>stable page content "
         b"stable page content stable page content stable page content"
         b"</div></body></html>")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_PAGE)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _project(tmp_path):
    # minimal project skeleton: an App.jsx exposing the route + a reference
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text('<Route path="/home" element={<Home/>} />')
    refs = tmp_path / "design" / "references"
    refs.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (64, 64), "white").save(refs / "home.png")
    return tmp_path, [refs / "home.png"]


def _judge_counting(calls, score=0.3):
    async def judge(llm, screen, shot):
        calls.append(screen["name"])
        return {"similarity": score, "deviations": [], "dimensions": {},
                "fixes": [], "summary": "counted"}
    return judge


def _run(project_dir, refs, server, cache):
    async def capture(scr):
        return await vf.capture_route_screenshots(
            server, scr, None, project_dir / "design" / "visual_gate")
    calls = []
    res = asyncio.run(vf.run_visual_fidelity(
        project_dir, refs, llm=None, capture_fn=capture,
        judge_fn=_judge_counting(calls), verdict_cache=cache))
    return res, calls


def test_identical_pixels_judged_once_across_runs(server, tmp_path):
    project_dir, refs = _project(tmp_path)
    cache = {}
    r1, c1 = _run(project_dir, refs, server, cache)
    r2, c2 = _run(project_dir, refs, server, cache)
    assert c1 == ["home"], "first run judges"
    assert c2 == [], "unchanged pixels must reuse the cached verdict"
    # Name the cause. `c2 == []` above is satisfied by BOTH "the cached verdict was
    # reused" and "the capture failed, so nothing was judged", so a chromium launch
    # that flakes on the repeated start/stop this file does used to surface here as
    # a bare `IndexError: list index out of range` — unreadable, and indistinguishable
    # from a cache regression.
    def _home(report, which):
        got = [s for s in report["screens"] if s["name"] == "home"]
        assert got, (
            f"{which} reported no 'home' screen at all (screens="
            f"{[s['name'] for s in report['screens']]}). With c2 == [] this is a "
            "CAPTURE failure, not a cache hit — the two are indistinguishable from "
            "the judge-call list alone.")
        return got[0]

    s1 = _home(r1, "first run")
    s2 = _home(r2, "second run")
    assert s1["similarity"] == s2["similarity"] == 0.3


def test_no_cache_passed_judges_every_time(server, tmp_path):
    project_dir, refs = _project(tmp_path)
    _, c1 = _run(project_dir, refs, server, cache=None)
    _, c2 = _run(project_dir, refs, server, cache=None)
    assert c1 == ["home"] and c2 == ["home"]


def test_cleared_cache_rejudges(server, tmp_path):
    # reset_for_milestone semantics: a fresh cache re-judges
    project_dir, refs = _project(tmp_path)
    cache = {}
    _, c1 = _run(project_dir, refs, server, cache)
    cache.clear()
    _, c2 = _run(project_dir, refs, server, cache)
    assert c1 == ["home"] and c2 == ["home"]


def test_gate_owns_cache_and_resets_per_milestone():
    from types import SimpleNamespace
    g = vf.VisualFidelityGate(SimpleNamespace())
    assert isinstance(getattr(g, "_verdict_cache", None), dict)
    g._verdict_cache["k"] = {"similarity": 1.0}
    g.reset_for_milestone()
    assert g._verdict_cache == {}, "reset_for_milestone must clear the verdict cache"
