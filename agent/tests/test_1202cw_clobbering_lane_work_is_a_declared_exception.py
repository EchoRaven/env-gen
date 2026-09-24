"""#1202cw — the framework may not overwrite lane files without saying why.

#1011 built `framework_may_write` for exactly this, citing 46 deleted LoginPages in r164,
and `is_lane_owned` measured the cost across all 164 generated projects: ~22,000
alternating overwrites in the top 25 files alone (LoginPage.jsx 1162 framework / 1054
lane writes over 70 runs; App.jsx 947/940 over 93; custom_routes.py 507/987 over 114).
Its docstring concluded the ownership map was complete and this was "purely an
enforcement gap".

Then nothing called it — one grep hit, the warning string inside its own body — while the
projector modules made 62 raw `Path.write_text` calls straight onto lane files. r41 is the
bill: the lane wrote the exact nav the judge asked for and #520's projection replaced it
with one built from the capture route table, taking down all seven screens that share the
header.

Several projectors DO overwrite lane files by design and their tests say so. Those
decisions stand — but they are now DECLARED, so a projector written tomorrow is safe
without its author knowing this file exists.
"""
import ast
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.path_routed_workspace import (
    framework_write_1202cw,
    path_is_lane_owned_1202cw,
    lane_clobbers_1202cw,
)

RUNTIME = Path("env_generator/llm_generator/multi_agent/runtime")

# #1202td: this was a hardcoded three. The choke point's own docstring promises that "a
# projector written tomorrow is safe without its author knowing this file exists" -- and a
# list of three filenames cannot deliver that. Three more modules were writing LANE-OWNED
# paths raw, checked against `path_is_lane_owned_1202cw` rather than guessed:
#
#     heal_pipeline.py            seed_data.json (x2), a page component, App.jsx
#     frontend_page_projector.py  the lane's api module (x2)
#     handler_fk_repair.py        only inside #995's documented import-failure fallback
#
# So the guarded set is DERIVED now: every runtime module that writes at all is either
# guarded (no raw `write_text`) or exempt with a reason. The exemptions are files that write
# only FRAMEWORK-owned paths, where the guard would return True and change nothing.
PROJECTORS = ("frontend_scaffold.py", "backend_scaffold.py", "route_projector.py",
              "heal_pipeline.py", "frontend_page_projector.py", "psycopg_dsn_repair.py")

# Writes only framework-owned paths (schema.sql, main.py, docker-compose.yml, the run ledger,
# reports). Verified per file against `path_is_lane_owned_1202cw`, not assumed from the name.
_FRAMEWORK_ONLY_WRITERS_1202TD = {
    "reference_materials.py": "design/reference material, outside app/",
    "visual_fidelity.py": "screenshots and verdicts under logs/",
    "scaffolder.py": "first-run scaffold: main.py, docker-compose.yml, .gitignore, README",
    "backend_skeleton.py": "emits the framework's own skeleton files",
    "kickoff_driver.py": "kickoff artefacts under shared/",
    "safe_code_write.py": "IS the other write primitive (#995); guards its own target",
    "deliverability.py": "writes reports, never app sources",
    "design_prep.py": "design-prep artefacts, outside app/",
    "frontend_audit.py": "audit output",
    "run_budget.py": "the run ledger",
    "database_scaffold.py": "app/database/schema.sql — framework-owned",
    "handler_fk_repair.py": "#995 fallback only; the live path is write_py_if_still_parses",
    "kickoff/run_kickoff.py": "kickoff artefacts under shared/",
    "hubs/codehub/service.py": "hub store, not an app source",
    "mcp_scaffold.py": "app/mcp_server/* — framework-owned, checked not lane-owned",
    "oauth_scaffold.py": "jwt_manager/oauth_store/oauth_routes — all framework-owned",
    "milestone_resume.py": "a .tmp beside the snapshot, replaced atomically",
    "observability/dashboard.py": "the rendered dashboard, outside app/",
    "path_routed_workspace.py": "IS the choke point; line 930 is the guarded write itself",
    "project.py": "project.json metadata",
    "provenance_scrub.py": "logs/provenance_scrub_1202mi.jsonl",
    "seed_audit.py": "a json audit report",
    "test_user_squad.py": "the squad's own json state file",
    # #1202td: revealed only once the scan became AST-based -- all four write through a
    # parenthesised expression, which the old regex could not see.
    "approval.py": "the approval store's own config/record json",
    "run_snapshot.py": "the snapshot manifest",
    "test_user_validation.py": "a per-version report json under logs/",
    "validation_runner.py": ".last_build_fingerprint beside the compose file",
}



def _raw_write_lines(path: Path):
    """Lines holding a raw `.write_text(` call, found by PARSING (#1202td).

    The regex this replaces required an identifier immediately before `.write_text(`, so
    `Path(path).write_text(...)` and `(d / "f").write_text(...)` were invisible to it. That is
    not hypothetical: it hid a live raw write onto lane files inside `frontend_scaffold.py`
    (#632's default-import repair) for this ratchet's whole life, plus writers in seven other
    modules. A line carrying `# raw:` is a declared shim -- the #995 import-failure path.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.split("\n")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return sorted({
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "write_text"
        and "# raw:" not in lines[n.lineno - 1]
    })


def test_an_undeclared_write_onto_lane_work_is_refused(tmp_path):
    """The r41 case, reduced: the lane's file already has content and the projector did
    not say why it should win."""
    f = tmp_path / "app/frontend/src/components/NetflixHeader.jsx"
    f.parent.mkdir(parents=True)
    assert framework_write_1202cw(f, "lane nav") is True          # first-run scaffolding
    assert framework_write_1202cw(f, "projected nav") is False    # would clobber
    assert f.read_text() == "lane nav"


def test_a_declared_write_still_wins(tmp_path):
    """The deliberate projections must keep working — this closes an enforcement gap, it
    does not reverse the decisions behind #520/#495/#493/#534/#910/#1102."""
    f = tmp_path / "app/frontend/src/pages/LoginPage.jsx"
    f.parent.mkdir(parents=True)
    f.write_text("lane page")
    assert framework_write_1202cw(f, "projected", clobber_ok="#495: replaces a fallback")
    assert f.read_text() == "projected"


def test_the_framework_still_owns_its_own_files(tmp_path):
    """Blocking the framework from writing its own scaffold would be a far worse failure
    than the one being fixed."""
    f = tmp_path / "app/frontend/src/main.jsx"
    f.parent.mkdir(parents=True)
    f.write_text("old")
    assert path_is_lane_owned_1202cw(f) is False
    assert framework_write_1202cw(f, "new") is True


def test_an_emptied_lane_file_is_still_repairable(tmp_path):
    """#1011's narrowness, preserved: the guard blocks content, not existence."""
    f = tmp_path / "app/frontend/src/pages/ShowsPage.jsx"
    f.parent.mkdir(parents=True)
    f.write_text("")
    assert framework_write_1202cw(f, "scaffolded") is True


def test_the_projectors_hold_no_raw_writes():
    """The choke point only works if it cannot be walked around. A raw `write_text` in
    these modules is how all 62 of the original bypasses looked."""
    offenders = []
    for name in PROJECTORS:
        offenders += [f"{name}:{i}" for i in _raw_write_lines(RUNTIME / name)]
    assert offenders == [], (
        "these bypass framework_write_1202cw and can clobber lane work silently: "
        + ", ".join(offenders))


def test_the_guard_has_callers():
    """The meta-lesson. #1011 was correct and unwired; #718 is a comment with no code;
    #641/#698 write a recommendation nothing reads. A mechanism with no callers is
    indistinguishable from one that was never written."""
    callers = 0
    for name in PROJECTORS:
        callers += (RUNTIME / name).read_text().count("_fw_write_1202cw(")
    assert callers >= 50, f"only {callers} call sites — the projectors have drifted off the guard"


def test_every_declared_clobber_names_a_ticket():
    """`clobber_ok` is an argument, not a switch: it must cite the decision it invokes so
    the next reader can weigh it rather than copy it."""
    bad = []
    for name in PROJECTORS:
        src = (RUNTIME / name).read_text()
        for m in re.finditer(r"clobber_ok=\(?\s*\n?\s*\"([^\"]{0,200})", src):
            reason = m.group(1)
            if not re.search(r"#\d+|ADDITIVE", reason):
                bad.append(f"{name}: {reason[:60]}")
    assert bad == [], "declared clobbers that cite no ticket: " + "; ".join(bad)


def test_the_census_reaches_run_budget_json(tmp_path):
    """#947: a measurement that only exists in memory has no ceiling. ~22,000 overwrites
    were invisible for 164 projects precisely because nothing wrote them down."""
    import json
    import logging
    import time
    from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget

    f = tmp_path / "app/frontend/src/pages/MyListPage.jsx"
    f.parent.mkdir(parents=True)
    f.write_text("lane")
    framework_write_1202cw(f, "x")                                  # refused
    framework_write_1202cw(f, "y", clobber_ok="#495: fallback")     # declared

    out = tmp_path / "run"
    out.mkdir()
    RunBudget(out, logging.getLogger("t")).write(
        {"max_wall_sec": 1e5, "max_ticks": 500}, time.time(), 1.0, 1, "running")
    census = json.loads((out / "run_budget.json").read_text())["lane_clobbers_1202cw"]
    assert any("MyListPage.jsx" in k for k in census.get("refused", {}))
    assert any("MyListPage.jsx" in k for k in census.get("declared", {}))


def test_no_runtime_module_writes_app_sources_outside_the_choke_point():
    """#1202td: the rule, not the list. Any runtime module with a raw `write_text` is either
    guarded (it must route through `framework_write_1202cw`) or exempt with a reason -- so the
    next module to repair a lane file has to be classified by whoever writes it.

    This is the same correction #1202tb made to #1202sw: a hardcoded set of examples cannot
    show that nothing is missing. Enumerate what the tree contains."""
    unclassified = []
    for f in sorted(RUNTIME.rglob("*.py")):
        rel = str(f.relative_to(RUNTIME))
        if rel in PROJECTORS or rel in _FRAMEWORK_ONLY_WRITERS_1202TD:
            continue
        if _raw_write_lines(f):
            unclassified.append(rel)
    assert unclassified == [], (
        "these runtime modules write files and are neither guarded nor exempt. If the module "
        "can write a LANE-OWNED path, route it through framework_write_1202cw and add it to "
        "PROJECTORS; if it only writes framework-owned paths, add it to "
        "_FRAMEWORK_ONLY_WRITERS_1202TD with the reason: %s" % unclassified)


def test_no_exemption_is_stale():
    """A file that stops writing, or starts routing through the guard, must leave the
    exemption list -- otherwise the list becomes a place to hide a future raw write."""
    stale = []
    for rel in _FRAMEWORK_ONLY_WRITERS_1202TD:
        f = RUNTIME / rel
        if not f.is_file():
            stale.append(f"{rel} (gone)")
            continue
        if not _raw_write_lines(f):
            stale.append(f"{rel} (no raw write left)")
    assert stale == [], "exemptions that no longer describe anything: %s" % stale


def test_the_newly_guarded_modules_really_route_their_lane_writes():
    """Non-vacuity for the two modules #1202td moved: they must actually call the guard, and
    every clobber they declare cites its ticket (checked by the test above, which now covers
    them because PROJECTORS grew)."""
    for name in ("heal_pipeline.py", "frontend_page_projector.py"):
        src = (RUNTIME / name).read_text(encoding="utf-8")
        assert src.count("_fw_write_1202cw(") >= 2, name
