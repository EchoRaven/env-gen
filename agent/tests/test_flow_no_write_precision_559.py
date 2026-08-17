"""#559 — precision fix for #557's ``completeness_flow_no_write``.

r107 flagged two FALSE POSITIVES on ``completeness_flow_no_write``:

  * ``player`` — a play/watch flow whose mutation (record playback progress) IS
    backed by a state-write endpoint (``POST /api/continue-watching``, projected by
    #556). The old check name-matched ``player`` -> ``play`` and, finding no route
    literally called ``player``, flagged it.
  * ``landing_marketing`` — a STATIC pre-auth marketing splash (no mutation at all).
    The old fuzzy prefix match let ``marketing`` hit the verb ``mark``.

These tests pin the two GENERALIZABLE suppression rules, and prove neither weakens
true-gap detection:

  1. state-write-backed flows — a mutation flow whose subject entity has a write,
     or a play/watch/resume flow with a progress state-write endpoint, is clean;
  2. non-mutation flows — view-only / static flow names (marketing/landing/splash/
     browse/…) carry no mutation verb and are never flagged;
  3. a real mutation flow with NO backing write ANYWHERE is STILL flagged;
  4. the exact r107 ``player`` + ``landing_marketing`` cases are clean.
"""

import json
import os

from env_generator.llm_generator.multi_agent.runtime.completeness_audit import (
    compute_completeness,
    check_flow_no_write,
    check_state_entity_no_write,
    state_entities_with_write,
    _flow_mutation_verb,
)


# ---------------------------------------------------------------------------
# Fakes (duck-typed like the real hubs — mirrors test_completeness_audit_557)
# ---------------------------------------------------------------------------

class _FakeRH:
    def __init__(self, endpoints, tables):
        self._eps = endpoints
        self._tbls = tables

    def get_endpoints(self):
        return dict(self._eps)

    def list_tables(self, provider=None):
        return dict(self._tbls)


class _FakeWorkhub:
    def __init__(self, feature_inventory=None, section="frontend"):
        self._fi = feature_inventory
        self._section = section

    def list_documents(self, kind=None, status=None):
        if kind not in (None, "kickoff"):
            return []
        if self._fi is None:
            return []
        return [{
            "kind": "kickoff",
            "metadata": {"decisions": [
                {"section": self._section, "milestone_index": 1,
                 "content": {"feature_inventory": self._fi}},
            ]},
        }]


class _FakeHubs:
    def __init__(self, rh, wh=None):
        self.registryhub = rh
        self.schema_hub = rh
        self.workhub = wh or _FakeWorkhub()


def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def _table(name, columns, status="implemented"):
    return {"id": name, "name": name, "status": status,
            "schema": {"columns": columns}}


def _ep(method, path, status="implemented", **kw):
    return {"method": method, "path": path, "status": status, **kw}


# continue_watching: a progress state entity (state token ``progress``)
_CONTINUE_WATCHING = _table("continue_watching", [
    _col("id", "integer", primary_key=True),
    _col("profile_id", "integer", references="profiles.id"),
    _col("title_id", "integer", references="titles.id"),
    _col("progress_seconds", "integer", default=0),
])


# ---------------------------------------------------------------------------
# Verb / word-part matching precision (the root of both FPs)
# ---------------------------------------------------------------------------

def test_marketing_does_not_match_mark_verb():
    # 'marketing' = 'mark' + 'eting' -> 'eting' is NOT a verb suffix.
    assert _flow_mutation_verb("landing_marketing") is None
    assert _flow_mutation_verb("marketing") is None


def test_playlist_does_not_match_play_verb():
    # 'playlist' = 'play' + 'list' -> 'list' is NOT a verb suffix (noun, not action).
    assert _flow_mutation_verb("playlist") is None


def test_player_matches_play_verb():
    # 'player' = 'play' + 'er' -> agent-noun suffix keeps the play action.
    assert _flow_mutation_verb("player") == "play"


def test_poster_descriptive_token_is_not_post_verb():
    # 'poster' inflection-matches 'post' but is a descriptive/image token.
    assert _flow_mutation_verb("poster_wall") is None


def test_static_view_only_flows_have_no_mutation_verb():
    for name in ("landing_marketing", "browse_home", "splash_screen",
                 "welcome", "hero_billboard", "search", "browse_by_languages",
                 "profile_menu", "hover_preview", "title_detail"):
        assert _flow_mutation_verb(name) is None, name


def test_genuine_mutation_verbs_still_detected():
    assert _flow_mutation_verb("create_order") == "create"
    assert _flow_mutation_verb("continue_watching") == "watch"
    assert _flow_mutation_verb("rate_title") == "rate"
    assert _flow_mutation_verb("add_to_list") == "add"
    assert _flow_mutation_verb("toggle_favorite") == "toggle"


# ---------------------------------------------------------------------------
# Rule 1 — state-write-backed flows are NOT flagged
# ---------------------------------------------------------------------------

def test_playback_flow_backed_by_progress_state_write_is_clean():
    # 'player' (verb 'play') has NO route literally named 'player', but the app
    # HAS a progress state-write endpoint (POST /api/continue-watching) -> the
    # playback mutation is satisfied -> NOT flagged.
    tables = {"continue_watching": _CONTINUE_WATCHING}
    endpoints = {
        "e1": _ep("GET", "/api/continue-watching"),
        "e2": _ep("POST", "/api/continue-watching"),
    }
    assert check_flow_no_write(None, endpoints, ["player"], tables) == []


def test_playback_flow_without_any_progress_write_still_flags():
    # Same 'player' flow but continue_watching is READ-ONLY (no write) -> the
    # playback mutation is a genuine gap and STILL flags (true-gap preserved).
    tables = {"continue_watching": _CONTINUE_WATCHING}
    endpoints = {"e1": _ep("GET", "/api/continue-watching")}
    results = check_flow_no_write(None, endpoints, ["player"], tables)
    assert len(results) == 1
    assert results[0].flow == "player"
    assert results[0].missing_verb == "play"
    assert results[0].severity == "warn"


def test_flow_referencing_state_entity_with_write_is_clean():
    # A flow whose subject tokens reference a state entity that HAS a write.
    watch_progress = _table("watch_progress", [
        _col("id", "integer", primary_key=True),
        _col("user_id", "integer", references="users.id"),
        _col("progress_seconds", "integer"),
    ])
    tables = {"watch_progress": watch_progress}
    endpoints = {
        "e1": _ep("GET", "/api/watch-progress"),
        "e2": _ep("PUT", "/api/watch-progress/{id}"),
    }
    assert check_flow_no_write(None, endpoints, ["track_watch_progress"], tables) == []


def test_state_entities_with_write_is_missing_write_complement():
    tables = {"continue_watching": _CONTINUE_WATCHING}
    with_post = {"e1": _ep("GET", "/api/continue-watching"),
                 "e2": _ep("POST", "/api/continue-watching")}
    get_only = {"e1": _ep("GET", "/api/continue-watching")}
    # WITH a write -> in the with_write set, and NOT flagged as state gap.
    assert "continue_watching" in state_entities_with_write(tables, with_post)
    assert check_state_entity_no_write(tables, with_post) == []
    # GET-only -> NOT in the with_write set, and IS flagged as a state gap.
    assert "continue_watching" not in state_entities_with_write(tables, get_only)
    assert len(check_state_entity_no_write(tables, get_only)) == 1


# ---------------------------------------------------------------------------
# Rule 2 — non-mutation / static flows are NOT flagged
# ---------------------------------------------------------------------------

def test_marketing_landing_flow_not_flagged():
    endpoints = {"e1": _ep("GET", "/api/titles")}
    assert check_flow_no_write(None, endpoints, ["landing_marketing"], {}) == []


def test_browse_and_static_flows_not_flagged():
    endpoints = {"e1": _ep("GET", "/api/titles")}
    flows = ["browse_home", "splash_screen", "hero_billboard",
             "profile_menu", "hover_preview", "search"]
    assert check_flow_no_write(None, endpoints, flows, {}) == []


# ---------------------------------------------------------------------------
# True-gap preservation — a real mutation flow with NO backing write STILL flags
# ---------------------------------------------------------------------------

def test_real_mutation_flow_without_backing_write_still_flags():
    # rate_title: verb 'rate', no rating endpoint anywhere, no state entity backs it.
    endpoints = {"e1": _ep("GET", "/api/titles")}
    results = check_flow_no_write(None, endpoints, ["rate_title"], {})
    assert len(results) == 1
    assert results[0].check_id == "completeness_flow_no_write"
    assert results[0].flow == "rate_title"
    assert results[0].missing_verb == "rate"


def test_rating_route_on_different_resource_does_not_falsely_satisfy():
    # A POST that touches 'titles'/'rating' must NOT satisfy a 'rate_title' flow
    # whose own tokens don't match that route (guards over-suppression).
    endpoints = {
        "e1": _ep("GET", "/api/titles"),
        "e2": _ep("POST", "/api/titles/{id}/rating"),
    }
    # 'rate_title' tokens (rate_title/ratetitle/…) don't touch titles/rating route
    results = check_flow_no_write(None, endpoints, ["rate_title"], {})
    assert [r.flow for r in results] == ["rate_title"]


# ---------------------------------------------------------------------------
# The exact r107 cases — player + landing_marketing clean end-to-end
# ---------------------------------------------------------------------------

def _r107_like_hubs(extra_flows=None):
    """A Netflix-r107-shaped contract: continue_watching progress table WITH its
    #556 write, plus the player + landing_marketing flows that were FPs."""
    tables = {
        "genres": _table("genres", [
            _col("id", "integer", primary_key=True),
            _col("name", "string", unique=True),
        ]),
        "continue_watching": _CONTINUE_WATCHING,
        "ratings": _table("ratings", [
            _col("id", "integer", primary_key=True),
            _col("profile_id", "integer", references="profiles.id"),
            _col("title_id", "integer", references="titles.id"),
            _col("value", "string"),
        ]),
    }
    endpoints = {
        "e1": _ep("GET", "/api/titles"),
        "e2": _ep("GET", "/api/genres"),
        "e3": _ep("GET", "/api/continue-watching"),
        "e4": _ep("POST", "/api/continue-watching"),      # #556
        "e5": _ep("POST", "/api/titles/{id}/rating"),
        "e6": _ep("GET", "/api/my-list"),
        "e7": _ep("POST", "/api/my-list"),
    }
    fi = {
        "browse_home": "hero + rails",
        "player": "full-viewport HTML5 <video> at /watch/:titleId (play/pause, +/-10s)",
        "continue_watching": "Continue Watching rail from GET /api/continue-watching",
        "rating": "thumbs rating persisted via POST /api/titles/{id}/rating",
        "landing_marketing": "pre-auth marketing hero at / with poster collage",
        "search": "inline search over GET /api/search",
        "profile_menu": "avatar dropdown",
        "hover_preview": "hover expands to a preview card",
    }
    if extra_flows:
        fi.update(extra_flows)
    return _FakeHubs(_FakeRH(endpoints, tables), _FakeWorkhub(fi))


def test_r107_player_and_landing_marketing_clean_end_to_end():
    report = compute_completeness(_r107_like_hubs())
    flow_flags = [r.flow for r in report.results
                  if r.check_id == "completeness_flow_no_write"]
    assert flow_flags == []          # player + landing_marketing both clean
    # and no false state gap either (continue_watching + ratings both have writes)
    assert [r for r in report.results
            if r.check_id == "completeness_state_entity_no_write"] == []


def test_r107_shape_still_flags_a_genuine_gap():
    # Inject a genuinely-unbacked mutation flow into the r107-shaped inventory.
    report = compute_completeness(_r107_like_hubs(
        extra_flows={"submit_review": "post a written review (no endpoint)"}))
    flow_flags = [r.flow for r in report.results
                  if r.check_id == "completeness_flow_no_write"]
    assert flow_flags == ["submit_review"]


# ---------------------------------------------------------------------------
# Integration against the REAL r107 hubs (skipped if the artifacts are absent)
# ---------------------------------------------------------------------------

_R107 = os.path.join(os.path.dirname(__file__), "..", "generated",
                     "netflix-web-r107", "shared", "hubs")


def test_real_r107_contract_has_no_flow_no_write_fp():
    if not os.path.isdir(_R107):
        return  # generated artifact not present in this checkout — skip
    with open(os.path.join(_R107, "registryhub_endpoints.json")) as f:
        endpoints = json.load(f)
    with open(os.path.join(_R107, "registryhub_tables.json")) as f:
        tables = json.load(f)
    with open(os.path.join(_R107, "workhub_documents.json")) as f:
        docs = json.load(f)

    class _RealWH:
        def list_documents(self, kind=None, status=None):
            out = []
            for d in (docs.values() if isinstance(docs, dict) else docs):
                if isinstance(d, dict) and kind in (None, d.get("kind")):
                    out.append(d)
            return out

    hubs = _FakeHubs(_FakeRH(endpoints, tables), _RealWH())
    report = compute_completeness(hubs)
    flow_flags = [r.flow for r in report.results
                  if r.check_id == "completeness_flow_no_write"]
    assert "player" not in flow_flags
    assert "landing_marketing" not in flow_flags
    assert flow_flags == []
