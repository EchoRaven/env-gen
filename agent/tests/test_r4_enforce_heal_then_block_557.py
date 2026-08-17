"""#557 R4-core (user-approved) — HEAL-THEN-ENFORCE contract-completeness.

The #557 oracle DETECTS a readable-but-not-writable STATE entity (the
Continue-Watching class: a table with a mutable data column that has a GET but no
POST/PUT/PATCH). #556 auto-projects the missing write. Turning the oracle into a
HARD delivery block (``ENVGEN_COMPLETENESS_ENFORCE`` — now ON by default) is only
SAFE if the heal runs FIRST: the #556 heal otherwise runs LATER (orchestrator
final-flush / release-snapshot, AFTER the delivery gate), so naive enforcement
would FALSE-BLOCK a gap the heal WOULD have closed. ``delivery_gate.enforce_completeness``
closes that timing bug — it runs the SAME heal entry point
(``heal_pipeline.heal_state_write_endpoints`` → ``route_projector.
project_state_write_endpoints``) BEFORE consulting the oracle.

These tests pin the exact gate code path (``enforce_completeness``):
  (a) ENFORCE on + a HEALABLE state-entity gap → heal projects+registers the write →
      the oracle goes clean → NOT blocked;
  (b) ENFORCE on + a GENUINELY UNHEALABLE gap (state column + GET but no ORM model
      the projector can back) → still BLOCKS (failed_checks carries
      completeness_state_entity_no_write) — real incompleteness must not ship;
  (b2) ENFORCE on + a write that exists in CODE but is missing from the REGISTRY →
       NOT blocked (register-only heal; never false-block a working feature);
  (c) ENFORCE on + no gap → OK;
  (d) ENFORCE off → reported-only, never blocks, and BYTE-IDENTICAL (no heal side
      effects: main.py untouched, nothing registered);
  (e) warn-severity flow findings (flow_no_write) NEVER block regardless.

Plus a full ``validate_delivery_gate`` smoke test to confirm the wiring does not
crash a real gate eval. Generalizable: derived from the schema (mutable column(s)
+ owner/subject FKs) — no product literals.
"""
import ast
import os

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import completeness_audit as ca


# ---------------------------------------------------------------------------
# Fakes (duck-typed like the real hubs)
# ---------------------------------------------------------------------------

class _FakeRH:
    """RegistryHub stand-in: get_endpoints/list_tables + a register_endpoint that
    actually mutates the endpoints map (so the oracle sees a newly-registered write)."""

    def __init__(self, endpoints, tables):
        self._eps = dict(endpoints)
        self._tbls = dict(tables)
        self.registered = []

    def get_endpoints(self):
        return dict(self._eps)

    def list_tables(self, provider=None):
        return dict(self._tbls)

    def list_ui_pages(self):
        return {}

    def get_verification_chains(self):
        return {}

    def register_endpoint(self, method, path, schema=None, provider="",
                          agent="", status="defined", **metadata):
        key = f"{method} {path}"
        self._eps[key] = {"id": key, "method": method, "path": path,
                          "status": status, "schema": schema or {},
                          "metadata": metadata}
        self.registered.append(key)
        return self._eps[key]


class _FakeWorkhub:
    def __init__(self, feature_inventory=None, section="frontend"):
        self._fi = feature_inventory
        self._section = section

    def list_documents(self, kind=None, status=None):
        if kind not in (None, "kickoff") or self._fi is None:
            return []
        return [{
            "kind": "kickoff",
            "metadata": {"decisions": [
                {"section": self._section, "milestone_index": 1,
                 "content": {"done_def": ["x"], "feature_inventory": self._fi}},
            ]},
        }]

    def list_tasks(self):
        return []


class _FakeHubs:
    def __init__(self, rh, wh=None):
        self.registryhub = rh
        self.schema_hub = rh
        self.workhub = wh or _FakeWorkhub()


def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def _table(name, columns, status="implemented", metadata=None):
    return {"id": name, "name": name, "status": status,
            "schema": {"columns": columns}, "metadata": metadata or {}}


def _ep(method, path, status="implemented", **kw):
    return {"method": method, "path": path, "status": status, **kw}


# A netflix-shaped state entity: PK + owner FK (profile_id) + subject FK (title_id)
# + a mutable scalar (progress_seconds).
_CW_TABLE = _table("continue_watching", [
    _col("id", "integer", primary_key=True),
    _col("profile_id", "integer", references="profiles.id"),
    _col("title_id", "integer", references="titles.id"),
    _col("progress_seconds", "integer", default=0),
])

_CW_MODELS_PY = """
from sqlalchemy import Column, Integer, ForeignKey
from database import Base


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    title_id = Column(Integer, ForeignKey("titles.id"))
    progress_seconds = Column(Integer, default=0)
"""

_MAIN_GET_ONLY = '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/continue-watching")
def get_cw():
    return {"items": [], "total": 0}
'''

_MAIN_WITH_POST = '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/continue-watching")
def get_cw():
    return {"items": [], "total": 0}


@app.post("/api/continue-watching")
def post_cw(body: dict = None):
    return {"item": {}}
'''


def _backend(tmp_path, models_py=_CW_MODELS_PY, main_py=_MAIN_GET_ONLY):
    bd = tmp_path / "app" / "backend"
    bd.mkdir(parents=True)
    if models_py is not None:
        (bd / "models.py").write_text(models_py, encoding="utf-8")
    (bd / "main.py").write_text(main_py, encoding="utf-8")
    return bd


@pytest.fixture(autouse=True)
def _clear_enforce_env(monkeypatch):
    # each test sets it explicitly; ensure no ambient value leaks in
    monkeypatch.delenv("ENVGEN_COMPLETENESS_ENFORCE", raising=False)
    yield


# ---------------------------------------------------------------------------
# (a) ENFORCE on + HEALABLE gap → heal projects the write → NOT blocked
# ---------------------------------------------------------------------------

def test_enforce_on_healable_gap_heals_and_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    _backend(tmp_path)  # models.py has ContinueWatching → projector CAN back it
    tables = {"continue_watching": _CW_TABLE}
    rh = _FakeRH({"g1": _ep("GET", "/api/continue-watching")}, tables)
    hubs = _FakeHubs(rh)

    # sanity: WITHOUT the heal the oracle would flag it (the false-block ENFORCE avoids)
    assert "completeness_state_entity_no_write" in \
        ca.compute_completeness(hubs).blocking_check_ids("error")

    failed = []
    results = dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    # HEALED → nothing blocking
    assert failed == []
    assert "completeness_state_entity_no_write" not in failed
    # the heal projected the write into main.py AND registered it (oracle now sees it)
    assert "POST /api/continue-watching" in rh.registered
    assert "POST /api/continue-watching" in rh.get_endpoints()
    new_main = (tmp_path / "app" / "backend" / "main.py").read_text()
    ast.parse(new_main)  # projected handler is valid python
    assert '@app.post("/api/continue-watching")' in new_main
    # the reported results no longer carry a state_entity_no_write error
    assert not any(r.get("check_id") == "completeness_state_entity_no_write"
                   and r.get("severity") == "error" for r in results)


# ---------------------------------------------------------------------------
# (b) ENFORCE on + GENUINELY UNHEALABLE gap → BLOCKS
# ---------------------------------------------------------------------------

def test_enforce_on_unhealable_gap_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    # No models.py at all → the projector cannot back a correct write → unhealable.
    # main.py has ONLY the GET (no write in code either) — genuine incompleteness.
    _backend(tmp_path, models_py=None, main_py=_MAIN_GET_ONLY)
    tables = {"continue_watching": _CW_TABLE}
    rh = _FakeRH({"g1": _ep("GET", "/api/continue-watching")}, tables)
    hubs = _FakeHubs(rh)

    failed = []
    dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    # UNHEALABLE → hard block (real functional incompleteness must not ship)
    assert "completeness_state_entity_no_write" in failed
    # nothing was projected or registered (no ORM model to back it)
    assert rh.registered == []
    before = _MAIN_GET_ONLY
    assert (tmp_path / "app" / "backend" / "main.py").read_text() == before


# ---------------------------------------------------------------------------
# (b2) ENFORCE on + write EXISTS IN CODE but MISSING FROM REGISTRY → NOT blocked
#      (register-only heal — never false-block a feature that works in code)
# ---------------------------------------------------------------------------

def test_enforce_on_write_coded_but_unregistered_registers_and_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    bd = _backend(tmp_path, main_py=_MAIN_WITH_POST)  # code HAS the POST
    before = (bd / "main.py").read_text()
    tables = {"continue_watching": _CW_TABLE}
    # registry knows only the GET (the write was coded but never registered)
    rh = _FakeRH({"g1": _ep("GET", "/api/continue-watching")}, tables)
    hubs = _FakeHubs(rh)

    failed = []
    dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    assert failed == []                                    # not false-blocked
    assert "POST /api/continue-watching" in rh.registered  # coded write got registered
    assert (bd / "main.py").read_text() == before          # no duplicate handler written


# ---------------------------------------------------------------------------
# (c) ENFORCE on + NO gap → OK
# ---------------------------------------------------------------------------

def test_enforce_on_no_gap_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    bd = _backend(tmp_path, main_py=_MAIN_WITH_POST)
    before = (bd / "main.py").read_text()
    tables = {"continue_watching": _CW_TABLE}
    # registry ALSO already has the POST → nothing missing at all
    rh = _FakeRH({"g1": _ep("GET", "/api/continue-watching"),
                  "p1": _ep("POST", "/api/continue-watching")}, tables)
    hubs = _FakeHubs(rh)

    failed = []
    dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    assert failed == []
    assert rh.registered == []                     # nothing to heal
    assert (bd / "main.py").read_text() == before  # byte-identical


# ---------------------------------------------------------------------------
# (d) ENFORCE off → reported-only, never blocks, BYTE-IDENTICAL (no side effects)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("off_value", ["0", "false", "no", "off"])
def test_enforce_off_is_reported_only_and_byte_identical(tmp_path, monkeypatch, off_value):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", off_value)
    bd = _backend(tmp_path)  # a HEALABLE gap is present
    before_main = (bd / "main.py").read_text()
    tables = {"continue_watching": _CW_TABLE}
    rh = _FakeRH({"g1": _ep("GET", "/api/continue-watching")}, tables)
    before_eps = set(rh.get_endpoints())
    hubs = _FakeHubs(rh)

    failed = []
    results = dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    # never blocks
    assert failed == []
    # NO heal ran → byte-identical: main.py untouched, nothing registered
    assert (bd / "main.py").read_text() == before_main
    assert rh.registered == []
    assert set(rh.get_endpoints()) == before_eps
    # still REPORTED (the oracle is computed for the gate dict)
    assert any(r.get("check_id") == "completeness_state_entity_no_write"
               for r in results)


# ---------------------------------------------------------------------------
# (e) warn-severity flow findings NEVER block (regardless of ENFORCE)
# ---------------------------------------------------------------------------

def test_enforce_on_warn_flow_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    _backend(tmp_path, models_py=None, main_py=_MAIN_GET_ONLY)
    # NO state entities → no error-severity finding. A declared mutation FLOW
    # (create_order) with no backing write → warn-severity flow_no_write only.
    tables = {}
    fi = {"entities": [], "flows": ["create_order"]}
    rh = _FakeRH({"g1": _ep("GET", "/api/orders")}, tables)
    hubs = _FakeHubs(rh, _FakeWorkhub(fi, section="backend"))

    failed = []
    results = dg.enforce_completeness(tmp_path, hubs, tables, failed, logger=None)

    # a warn flow finding is present ...
    assert any(r.get("check_id") == "completeness_flow_no_write"
               and r.get("severity") == "warn" for r in results)
    # ... but it NEVER blocks (only error-severity state_entity_no_write blocks)
    assert failed == []


# ---------------------------------------------------------------------------
# full validate_delivery_gate smoke: HEAL-THEN-ENFORCE wiring must not crash a
# real gate eval, and a healable gap must not appear in failed_checks.
# ---------------------------------------------------------------------------

class _FullRH(_FakeRH):
    def endpoint_id(self, m, p):
        import re
        p = re.sub(r"\$\{[^}]+\}", "{x}", p)
        p = re.sub(r"\{[^}]+\}", "{x}", p)
        return f"{(m or 'GET').upper()} {p.rstrip('/') or '/'}"

    def get_contract_test_results(self, *a, **k):
        return []


class _FullCodehub:
    def list_checks(self):
        return []


class _FullHubs:
    def __init__(self, rh, wh):
        self.registryhub = rh
        self.schema_hub = rh
        self.workhub = wh
        self.codehub = _FullCodehub()
        self.runhub = None  # → functionally_validated False (getattr-safe)


def test_full_delivery_gate_eval_does_not_crash_and_heals(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPLETENESS_ENFORCE", "1")
    # minimal on-disk env so the gate's file checks run without exploding
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "README.md").write_text("# design\n", encoding="utf-8")
    bd = _backend(tmp_path)  # app/backend with GET-only main.py + real model
    (tmp_path / "app" / "frontend").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    dbdir = tmp_path / "app" / "database"
    dbdir.mkdir(parents=True)
    (dbdir / "01_init.sql").write_text("CREATE TABLE continue_watching (id serial);\n", encoding="utf-8")

    tables = {"continue_watching": _CW_TABLE}
    rh = _FullRH({"g1": _ep("GET", "/api/continue-watching")}, tables)
    hubs = _FullHubs(rh, _FakeWorkhub())

    gate = dg.validate_delivery_gate(
        tmp_path, hubs, 0.0, None,
        scaffold_design_readme=lambda: None,
        get_validation_results=lambda limit=200: [],
        get_validation_summary=lambda: {})

    # did not crash; returns the expected shape
    assert isinstance(gate, dict)
    assert "completeness" in gate
    assert isinstance(gate.get("failed_checks"), list)
    # HEAL-THEN-ENFORCE ran inside the gate: the healable gap was healed, so the
    # completeness error is NOT among the failed checks (other unrelated checks may be).
    assert "completeness_state_entity_no_write" not in gate["failed_checks"]
    assert "POST /api/continue-watching" in rh.registered


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
