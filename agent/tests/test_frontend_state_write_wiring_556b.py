"""#556-pt2 — FRONTEND companion to the #556 state-write heal (play -> persist ->
resume, end-to-end).

#556 auto-projects a backend UPSERT WRITE endpoint (POST on a state collection,
``projected_by == 'completeness_state_write_heal_556'``) for any state-bearing
entity that had a GET but no write (e.g. POST /api/continue-watching persisting
progress_seconds). BUT the frontend never fired it, so "resume watching" recorded
NOTHING. This half makes the projected PLAYER screen fire that write from the
viewing action, so the Continue-Watching rail reflects REAL viewing on reload.

These tests pin:
  * a player screen + a projected state-write endpoint -> the emitted frontend
    POSTs to that endpoint carrying the SUBJECT key + the STATE value;
  * NO such endpoint -> the emitted frontend is BYTE-IDENTICAL (no write wiring);
  * the path + body keys are DERIVED from the descriptor + the entity's columns
    (a DIFFERENT entity emits ITS own keys — no continue_watching/progress_seconds
    literals);
  * a non-player screen emits no write wiring;
  * the loader reads the registry JSON and derives subject_fks when only
    natural_keys are present (owner peeled off — owner is server-derived);
  * ``_load_design_for_projection`` attaches ``_state_write_endpoints``;
  * the emitted player page transpiles (esbuild --loader jsx).
"""
import json
import shutil
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _design(state_write_endpoints=None, dataset=None):
    d = {
        "design_system": {
            "palette": {"bg": "#141414", "text": "#ffffff", "accent_red": "#e50914"},
            "theme": {"default": "dark"},
        },
    }
    if state_write_endpoints is not None:
        d["_state_write_endpoints"] = state_write_endpoints
    if dataset is not None:
        d["dataset"] = dataset
    return d


def _cw_endpoint():
    # netflix-shaped: subject FK title_id, state column progress_seconds, owner profile_id.
    return {
        "path": "/api/continue-watching",
        "state_columns": ["progress_seconds"],
        "natural_keys": ["profile_id", "title_id"],
        "subject_fks": ["title_id"],
        "owner_fk": "profile_id",
    }


def _player_screen():
    return {
        "name": "player",
        "route": "/watch/:titleId",
        "components": [
            {"id": "video", "role": "media playback area scrub playhead",
             "region": [0.0, 0.0, 1.0, 1.0]},
        ],
    }


def _player_page():
    return {"route": "/watch/:titleId", "name": "PlayerPage",
            "component": "PlayerPage", "apis_used": ["GET /api/titles/{id}"]}


def _render(design, screen=None, page=None, get_ep="/api/titles/{id}"):
    return fs._render_reference_page(
        "PlayerPage", page or _player_page(), screen or _player_screen(),
        design, [], get_ep)


# ---------------------------------------------------------------------------
# player screen + projected state-write endpoint -> POST carries subject + state
# ---------------------------------------------------------------------------

def test_player_with_state_write_endpoint_posts_subject_and_state():
    src = _render(_design([_cw_endpoint()]))
    # a POST to the projected write endpoint
    assert "fetch('/api/continue-watching', {" in src
    assert "method: 'POST'," in src
    # body carries the SUBJECT key (title_id) + the STATE value (progress_seconds)
    assert "'title_id': _swSid" in src
    assert "'progress_seconds': _swPlayed.current" in src
    # the subject id comes from the loaded record, else the ROUTE's own param
    assert "const _swSid = (cur && cur.id) || params.titleId;" in src
    # play-start + periodic + on-unmount write; useRef progress accumulator
    assert "const _swPlayed = useRef(0);" in src
    assert "import { useState, useEffect, useRef } from 'react';" in src
    assert "setInterval(() => { _swPlayed.current += 15; _swPost(); }, 15000);" in src
    assert "return () => { clearInterval(_swTimer); _swPost(); };" in src
    # rok-guard on the write (the file's existing fetch style)
    assert "if (!r.ok) throw new Error('HTTP ' + r.status);" in src


def test_owner_fk_not_sent_owner_is_server_derived():
    # the owner (profile_id) is injected by the #556 handler from the authed caller;
    # the body must NOT carry it (never trust a client owner id).
    src = _render(_design([_cw_endpoint()]))
    assert "profile_id" not in src


# ---------------------------------------------------------------------------
# NO state-write endpoint -> byte-identical (no write wiring)
# ---------------------------------------------------------------------------

def test_no_state_write_endpoint_is_byte_identical():
    base = _render(_design())                       # no _state_write_endpoints key
    empty = _render(_design(state_write_endpoints=[]))  # present but empty
    assert base == empty                            # empty list == absent
    assert "_swPost" not in base
    assert "useRef" not in base
    assert "import { useState, useEffect } from 'react';" in base

    # and the WITH-endpoint render differs ONLY by the additive wiring:
    wired = _render(_design([_cw_endpoint()]))
    assert wired != base
    # stripping the (contiguous) wiring block + the useRef import token recovers base.
    recovered = wired.replace(
        "import { useState, useEffect, useRef } from 'react';",
        "import { useState, useEffect } from 'react';")
    effect = fs._state_write_effect_556b(_player_screen(), _player_page(),
                                         _design([_cw_endpoint()]))
    assert effect and effect in recovered
    recovered = recovered.replace(effect, "", 1)
    assert recovered == base


# ---------------------------------------------------------------------------
# GENERALIZABLE: a DIFFERENT entity emits ITS OWN derived keys (no literals)
# ---------------------------------------------------------------------------

def test_derives_keys_for_a_different_entity_no_product_literals():
    # a course app: lesson_progress state entity, subject FK lesson_id, state col
    # position_seconds, owner user_id — the SAME wiring, different derived keys.
    ep = {
        "path": "/api/lesson-progress",
        "state_columns": ["position_seconds"],
        "natural_keys": ["user_id", "lesson_id"],
        "subject_fks": ["lesson_id"],
        "owner_fk": "user_id",
    }
    screen = {"name": "lesson_player", "route": "/learn/:lessonId",
              "components": [{"id": "v", "role": "playback area scrub playhead",
                              "region": [0.0, 0.0, 1.0, 1.0]}]}
    page = {"route": "/learn/:lessonId", "name": "PlayerPage",
            "component": "PlayerPage", "apis_used": ["GET /api/lessons/{id}"]}
    src = fs._render_reference_page("PlayerPage", page, screen, _design([ep]),
                                    [], "/api/lessons/{id}")
    assert "fetch('/api/lesson-progress', {" in src
    assert "'lesson_id': _swSid" in src
    assert "'position_seconds': _swPlayed.current" in src
    assert "params.lessonId" in src
    # NOT the netflix literals — everything is derived from the descriptor
    assert "continue-watching" not in src
    assert "progress_seconds" not in src
    assert "title_id" not in src


# ---------------------------------------------------------------------------
# a NON-player screen emits no write wiring (the write fires from the viewing action)
# ---------------------------------------------------------------------------

def test_non_player_screen_emits_no_write_wiring():
    grid = {"name": "browse", "route": "/browse",
            "components": [{"id": "rail", "role": "poster rail row of titles",
                            "region": [0.0, 0.1, 1.0, 0.5]}]}
    page = {"route": "/browse", "name": "BrowsePage", "component": "BrowsePage",
            "apis_used": ["GET /api/titles"]}
    with_ep = fs._render_reference_page("BrowsePage", page, grid,
                                        _design([_cw_endpoint()]), [], "/api/titles")
    without = fs._render_reference_page("BrowsePage", page, grid, _design(), [],
                                        "/api/titles")
    assert with_ep == without          # byte-identical — no wiring on a non-player screen
    assert "_swPost" not in with_ep


# ---------------------------------------------------------------------------
# subject-FK MATCH: multiple write endpoints -> pick the one for THIS subject
# ---------------------------------------------------------------------------

def test_matches_write_endpoint_by_subject_entity():
    # two state-write endpoints; the content entity (titles) selects continue-watching.
    other = {"path": "/api/reading-progress", "state_columns": ["page_no"],
             "natural_keys": ["user_id", "book_id"], "subject_fks": ["book_id"],
             "owner_fk": "user_id"}
    design = _design([other, _cw_endpoint()],
                     dataset=[{"id": "titles", "columns": ["id", "title", "poster_url"],
                               "records": 30}])
    src = _render(design)
    assert "fetch('/api/continue-watching', {" in src
    assert "'title_id': _swSid" in src
    assert "reading-progress" not in src


# ---------------------------------------------------------------------------
# the LOADER: reads the registry JSON, derives subject_fks when absent
# ---------------------------------------------------------------------------

def _write_registry(tmp_path, records):
    hub = tmp_path / "shared" / "hubs"
    hub.mkdir(parents=True)
    (hub / "registryhub_endpoints.json").write_text(
        json.dumps(records), encoding="utf-8")
    fe = tmp_path / "app" / "frontend" / "src"
    fe.mkdir(parents=True)
    return fe


def test_loader_reads_projected_state_write_endpoints(tmp_path):
    fe = _write_registry(tmp_path, {
        "POST /api/continue-watching": {
            "method": "POST", "path": "/api/continue-watching",
            "metadata": {"projected_by": "completeness_state_write_heal_556",
                         "state_columns": ["progress_seconds"],
                         "natural_keys": ["profile_id", "title_id"],
                         "subject_fks": ["title_id"], "owner_fk": "profile_id"}},
        "GET /api/continue-watching": {
            "method": "GET", "path": "/api/continue-watching", "metadata": {}},
        "POST /api/reviews": {          # a NON-projected POST is ignored
            "method": "POST", "path": "/api/reviews", "metadata": {}},
    })
    eps = fs._load_state_write_endpoints_556b(fe)
    assert len(eps) == 1
    d = eps[0]
    assert d["path"] == "/api/continue-watching"
    assert d["subject_fks"] == ["title_id"]
    assert d["state_columns"] == ["progress_seconds"]
    assert d["owner_fk"] == "profile_id"


def test_loader_derives_subject_fks_from_natural_keys(tmp_path):
    # older/partial metadata: only natural_keys present -> peel the owner FK off.
    fe = _write_registry(tmp_path, {
        "POST /api/continue-watching": {
            "method": "POST", "path": "/api/continue-watching",
            "metadata": {"projected_by": "completeness_state_write_heal_556",
                         "state_columns": ["progress_seconds"],
                         "natural_keys": ["profile_id", "title_id"]}},
    })
    eps = fs._load_state_write_endpoints_556b(fe)
    assert len(eps) == 1
    assert eps[0]["owner_fk"] == "profile_id"      # owner-like FK detected
    assert eps[0]["subject_fks"] == ["title_id"]   # the remainder is the subject


def test_loader_empty_when_no_registry(tmp_path):
    (tmp_path / "app" / "frontend" / "src").mkdir(parents=True)
    assert fs._load_state_write_endpoints_556b(
        tmp_path / "app" / "frontend" / "src") == []


def test_load_design_attaches_state_write_endpoints(tmp_path):
    fe = _write_registry(tmp_path, {
        "POST /api/continue-watching": {
            "method": "POST", "path": "/api/continue-watching",
            "metadata": {"projected_by": "completeness_state_write_heal_556",
                         "state_columns": ["progress_seconds"],
                         "natural_keys": ["profile_id", "title_id"],
                         "subject_fks": ["title_id"], "owner_fk": "profile_id"}},
    })
    # design_system.json lives at <run>/design/design_system.json (parent.parent/design)
    ds = tmp_path / "app" / "design"
    ds.mkdir(parents=True)
    (ds / "design_system.json").write_text(json.dumps({"design_system": {}}),
                                           encoding="utf-8")
    d = fs._load_design_for_projection(fe)
    assert d.get("_state_write_endpoints")
    assert d["_state_write_endpoints"][0]["path"] == "/api/continue-watching"


# ---------------------------------------------------------------------------
# the emitted player page transpiles (esbuild --loader jsx)
# ---------------------------------------------------------------------------

def test_emitted_player_page_transpiles_with_esbuild(tmp_path):
    esbuild = shutil.which("esbuild") or "/var/www/scripts/bin/esbuild"
    if not shutil.which(esbuild) and not __import__("os").path.exists(esbuild):
        pytest.skip("esbuild not available")
    src = _render(_design([_cw_endpoint()]))
    f = tmp_path / "PlayerPage.jsx"
    f.write_text(src, encoding="utf-8")
    proc = subprocess.run([esbuild, str(f), "--format=esm"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "_swPost" in proc.stdout   # the wiring survived transpile


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
