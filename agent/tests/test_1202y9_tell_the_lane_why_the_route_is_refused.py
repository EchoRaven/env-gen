r"""#1202y9: tell the lane WHY the route it is trying to open is refused.

r140, traced end to end on the live run:
  1. the lane registered `GET /api/feed` `auth_required=False` at 03:17:07 -- the logged-out
     landing page reads it
  2. the materials said NOTHING about `feed`, so `_structurally_private_resource_633`
     demoted it on shape alone (`author_id -> users` beside `sound_id -> sounds`, #598)
  3. `announce_shape_override_1202vt` said so 39 times -- into route_projector's logger
  4. ★ MEASURED: `SHAPE OVERRODE`, `1202vt` and `materials declare NOTHING` appear in ZERO
     files under `shared/hubs/` -- the tasks, messages and documents that are the whole of
     what a lane can read. The notice fired and reached nobody.
  5. the projected handler took an actor, the anonymous request came back 401, and the lane
     appended to `_FW_PUBLIC_API_1202KH` from custom_routes.py
  6. `deliverability_guard_tampering` blocked delivery 8 times across 90 minutes

#1202kx's own comment is the test this failed: "a lane that knew WHY it was being refused had
no reason to build that."

The remediation text is not a substitute. It gives the RULE -- "change its CONTRACT
(`auth_required: false` on a table the materials call public)" -- and the lane did the first
half. The half it could not see is that the materials say nothing about this table.

Corpus: guard_tampering blocked 10 of the 86 runs holding a gate ledger (12%, 63
occurrences), present in every one of the last eight -- r133 (26x), r134, r136, r137, r138,
r139 (10x), r140 (8x). #1202vt has been live for three of those, firing 109/75/39 times, and
the tampering happened in all three.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _guard_tampering_blockers_1202oj as guard,
    _shape_demoted_publics_1202y9 as why)

_MODELS = '''from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)


class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)
    title = Column(String)


class Feed(Base):
    __tablename__ = "feed"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    caption = Column(String)
'''

_TAMPER = '''from fastapi import APIRouter
import main as main_mod
router = APIRouter()

existing = list(getattr(main_mod, "_FW_PUBLIC_API_1202KH", []) or [])
existing.append(("GET", "/api/feed"))
setattr(main_mod, "_FW_PUBLIC_API_1202KH", existing)
'''

_CLEAN = '''from fastapi import APIRouter
router = APIRouter()


@router.get("/api/feed")
def feed():
    return {"items": []}
'''


class _RH:
    def __init__(self, eps, tables=None):
        self._e = eps
        self._t = tables or {}

    def get_endpoints(self):
        return self._e

    def list_tables(self):
        return self._t


class _Hubs:
    def __init__(self, eps, tables=None):
        self.registryhub = _RH(eps, tables)


def _public(method, path):
    return {"id": "%s %s" % (method, path), "method": method, "path": path,
            "schema": {"auth_required": False}}


def _app(tmp_path, custom=_TAMPER, models=_MODELS):
    app = tmp_path / "app"
    bd = app / "backend"
    bd.mkdir(parents=True)
    (bd / "main.py").write_text(models, encoding="utf-8")
    (bd / "custom_routes.py").write_text(custom, encoding="utf-8")
    return str(app)


_FEED = {"GET /api/feed": _public("GET", "/api/feed")}


def test_the_reason_is_attached_to_the_finding(tmp_path):
    """The r140 shape, end to end."""
    out = guard(_app(tmp_path), _Hubs(_FEED))
    assert out, "the tampering itself must still be reported"
    joined = " ".join(out)
    assert "GET /api/feed" in joined and "`feed`" in joined, joined
    assert "author_id->users" in joined, "the FK pair that decided it must be named"
    assert "visibility" in joined, "the one way out must be named"


def test_the_evidence_leads_and_the_explanation_follows(tmp_path):
    """★ #1202vx: prepending the sentence would let the prose take the head of the message
    from the file:line that tells the lane WHERE to look."""
    out = guard(_app(tmp_path), _Hubs(_FEED))
    assert out[0].startswith("framework auth guard tampered with:"), out[0]


def test_no_tampering_means_no_message_at_all(tmp_path):
    """The reason rides an existing blocker; it never becomes one."""
    assert guard(_app(tmp_path, custom=_CLEAN), _Hubs(_FEED)) == []


def test_tampering_without_a_shape_demoted_public_is_unchanged(tmp_path):
    """No contract-public endpoint -> nothing to explain, and the finding keeps its old
    wording exactly."""
    out = guard(_app(tmp_path), _Hubs({}))
    assert out and all("WHY THE 401" not in x for x in out), out


def test_a_missing_registry_is_the_old_behaviour(tmp_path):
    """The parameter defaults to None so every existing caller is untouched."""
    out = guard(_app(tmp_path))
    assert out and all("WHY THE 401" not in x for x in out), out


def test_the_control_plane_is_not_the_lanes_question(tmp_path):
    """`/api/v1/*` is the framework's own tenancy surface and is public by construction."""
    eps = {"POST /api/v1/reset": _public("POST", "/api/v1/reset"),
           "GET /api/v1/tenants": _public("GET", "/api/v1/tenants")}
    assert why(_app(tmp_path), _Hubs(eps)) == ""


def test_an_endpoint_the_contract_keeps_private_is_not_named(tmp_path):
    """Only a REVERSAL is news: an endpoint that never claimed to be public explains
    nothing about a 401 the lane did not expect."""
    rec = _public("GET", "/api/feed")
    rec["schema"]["auth_required"] = True
    assert why(_app(tmp_path), _Hubs({"GET /api/feed": rec})) == ""


def test_a_shape_that_is_not_private_is_not_named(tmp_path):
    """A table with no users FK beside another entity's FK was never demoted, so its
    `auth_required: false` stands and there is nothing to explain."""
    models = _MODELS.replace('    author_id = Column(Integer, ForeignKey("users.id"))\n', "")
    assert why(_app(tmp_path, models=models), _Hubs(_FEED)) == ""


def test_both_registry_accessors_are_tried():
    """★ #1202rm paid for this once already: "the method is get_endpoints, not
    list_endpoints. The first draft guessed." Both spellings must work."""
    import ast
    import inspect
    import multi_agent.runtime.deliverability as D

    tree = ast.parse(inspect.getsource(D._shape_demoted_publics_1202y9).lstrip())
    names = {n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "get_endpoints" in names and "list_endpoints" in names, sorted(names)


def test_a_registry_that_answers_neither_is_silent(tmp_path):
    class _Dumb:
        pass

    class _H:
        registryhub = _Dumb()
    assert why(_app(tmp_path), _H()) == ""


def test_it_reuses_the_projectors_own_predicate():
    """★ #1032 and the rule the unscoped-owner gate states in its own comment: the gate and
    the generator must not disagree about what is private, so the gate calls the projector's
    decision rather than restating it."""
    import ast
    import inspect
    import multi_agent.runtime.deliverability as D

    src = inspect.getsource(D._shape_demoted_publics_1202y9)
    assert "_structurally_private_resource_633" in src
    tree = ast.parse(src.lstrip())
    assert not any(isinstance(n, ast.FunctionDef) and "private" in n.name
                   for n in ast.walk(tree)), "no local re-implementation"


def test_the_prose_still_routes_to_the_same_owner(tmp_path):
    """★ #1202tu: the appended sentence must not change which check id the blocker maps to,
    or the finding stops dispatching anyone."""
    from multi_agent.runtime.delivery_gate import _deliverability_check_token as tok
    out = guard(_app(tmp_path), _Hubs(_FEED))
    for line in out:
        assert tok(line) == "deliverability_guard_tampering", (line[:90], tok(line))


def test_the_chain_that_owner_scoped_the_table_is_named(tmp_path):
    """★ r140's `feed` carries `owner_scoped_reads_set_by_chain_1202kv:
    authored_video_ownership_flow` — a VERIFICATION CHAIN flipped the flag that filters the
    rows. No amount of reading its own code shows a lane that cause, and r118 lost an hour
    going six rounds against a flag it never touched."""
    tables = {"feed": {"metadata": {
        "owner_scoped_reads": True,
        "owner_scoped_reads_set_by_chain_1202kv": "authored_video_ownership_flow"}}}
    out = guard(_app(tmp_path), _Hubs(_FEED, tables))
    assert "authored_video_ownership_flow" in " ".join(out), out


def test_a_table_that_is_not_owner_scoped_gets_no_attribution(tmp_path):
    tables = {"feed": {"metadata": {"owner_scoped_reads": False}}}
    out = guard(_app(tmp_path), _Hubs(_FEED, tables))
    assert "owner-scoped" not in " ".join(out), out


def test_the_way_out_names_the_write_that_actually_clears_the_flag(tmp_path):
    """★ "give it a visibility" is not enough to act on. The clear happens at
    `register_table`'s write boundary (#1202io) and only when `metadata.visibility` is
    exactly `public`; r140's `feed` has no `visibility` key at all, which is why nothing
    cleared it."""
    out = " ".join(guard(_app(tmp_path), _Hubs(_FEED)))
    assert "metadata.visibility" in out and "re-register" in out, out
    assert "owner_scoped_reads" in out, "the flag that actually filters must be named"


def test_a_registry_without_tables_still_reports(tmp_path):
    """Attribution is enrichment: its absence must not cost the diagnosis."""
    class _NoTables:
        def get_endpoints(self):
            return _FEED

    class _H:
        registryhub = _NoTables()
    out = guard(_app(tmp_path), _H())
    assert "WHY THE 401" in " ".join(out), out
