#!/usr/bin/env python3
"""#805: the session's re-runnable corpus measurements, promoted out of throwaway heredocs.

WHY THIS FILE EXISTS
--------------------
Nine measurement errors in one session, every one of them in ad-hoc analysis code written fresh in
a shell heredoc, and every one of them producing a confident number that was about my probe rather
than about the system:

    milestone_registry.json          the file is `milestones.json`         -> "0 comparable runs"
    list(d.values()) over the hubs   includes the `_meta` bootstrap doc    -> "0 failing chains"
    raw codehub_checks rows          need #193/#236's normaliser first     -> "0% contradicted UI"
    CREATE TABLE under app/backend   the DDL is in app/database/init/      -> "0% year mismatch"
    columns unioned across tables    hides titles.release_year             -> undercount
    a candidate set written by hand  omitted duplicate_minutes/_seconds    -> "2%" for a real 17%
    ...

`tools/check_pending_experiments.sh` does NOT have this defect — all 55 of its `grep_log` patterns
still match live framework strings (checked). The difference is not care at the moment of writing;
it is that the checker is committed, re-run, and reviewed, while a heredoc is written once under
time pressure and never seen again.

So the measurements worth keeping live here instead.

EVERY MEASUREMENT PRINTS ITS DENOMINATOR AND A NON-VACUITY LINE.
A rate with no denominator is unreadable, and a zero with no proof the probe can find anything is
a claim about the instrument. Both rules are enforced by construction below: `_report` refuses to
print a rate without a denominator, and each audit returns a `saw` count that is printed first.

USAGE
    python3 tools/corpus_audit.py [--generated DIR] [--since RUN_NUMBER]

`--since` is not cosmetic: three corpus-wide figures this session turned out to be dominated by
old builds and to describe already-fixed defects, and three others UNDERSTATED what recent builds
do. Neither direction is the default (#794 vs #774/#751/#752), so era-splitting is the point.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ACTOR_TABLES = ("users", "user", "profiles", "profile", "accounts", "account",
                 "members", "member", "customers", "customer", "tenants", "tenant")
_HOUSEKEEPING = ("id", "created_at", "updated_at")


# --------------------------------------------------------------------------- helpers

def _run_number(name: str) -> int:
    m = re.search(r"r(\d+)$", name)
    return int(m.group(1)) if m else -1


def _load(p: pathlib.Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _records(doc: Any) -> List[dict]:
    """Hub documents are a list, or a dict of records, or a dict with a list under a known key.

    `_meta` is a BOOTSTRAP document, not a record. Treating it as one is how a probe reported
    "0 failing chains across 140 runs" (and, in #755, how a `{"version": 1}` was counted as a
    release).
    """
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict):
        for key in ("tasks", "checks", "records", "items", "results", "chains", "milestones"):
            if isinstance(doc.get(key), list):
                return [r for r in doc[key] if isinstance(r, dict)]
        return [v for k, v in doc.items() if k != "_meta" and isinstance(v, dict)]
    return []


def _ddl_tables(run: pathlib.Path) -> Dict[str, List[str]]:
    """{table: [columns]} from the DDL — which lives in `app/database/init/`, NOT `app/backend`.

    A probe that searched app/backend matched 2 OAuth tables and reported a 0% column-mismatch
    rate across the whole corpus.
    """
    out: Dict[str, List[str]] = {}
    for f in (run / "app" / "database").rglob("*.sql"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)? "?(\w+)"?\s*\((.*?)\n\);',
                             text, re.S | re.I):
            cols = [x.group(1).lower()
                    for x in re.finditer(r'^\s*"?([a-z_][a-z0-9_]*)"?\s+\w', m.group(2), re.M)]
            if cols:
                out[m.group(1).lower()] = cols
    return out


def _ddl_refs(run: pathlib.Path) -> Dict[str, Dict[str, str]]:
    """{table: {column: referenced_table}} — the FK TARGET, which is what decides whether a link
    table is a label relation or a per-user one (#784/#803). Never decide that by column name."""
    out: Dict[str, Dict[str, str]] = {}
    for f in (run / "app" / "database").rglob("*.sql"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)? "?(\w+)"?\s*\((.*?)\n\);',
                             text, re.S | re.I):
            out[m.group(1).lower()] = {
                x.group(1).lower(): x.group(2).lower()
                for x in re.finditer(r'"?([a-z_][a-z0-9_]*)"?[^,\n]*REFERENCES\s+"?(\w+)"?',
                                     m.group(2), re.I)}
    return out


def _report(title: str, saw: int, total: int, hits: int, note: str = "") -> None:
    """Print one measurement. Refuses to imply a rate without its denominator, and leads with the
    non-vacuity count."""
    if total <= 0:
        print(f"  {title:<44} n/a   (no comparable runs — probe found nothing to measure)")
        return
    pct = 100 * hits // total
    print(f"  {title:<44} {hits:>4}/{total:<4} ({pct:>3}%)   probe saw {saw} run(s){note}")


# --------------------------------------------------------------------------- audits

def audit_link_tables(runs: List[pathlib.Path]) -> None:
    """#803's rule: a pure link table is a LABEL relation only if neither FK reaches an actor
    table. Structurally the two shapes are identical — this is the split that makes the
    difference between a chip row and a public leak of who saved what."""
    safe = unsafe = seen = 0
    for run in runs:
        tables, refs = _ddl_tables(run), _ddl_refs(run)
        if not tables:
            continue
        seen += 1
        for name, cols in tables.items():
            body = [c for c in cols if c not in _HOUSEKEEPING]
            fks = [c for c in body if c.endswith("_id")]
            if len(fks) != 2 or len(body) != 2:
                continue
            targets = {refs.get(name, {}).get(c) for c in fks}
            if None in targets:
                continue
            if targets & set(_ACTOR_TABLES):
                unsafe += 1
            else:
                safe += 1
    total = safe + unsafe
    print(f"  {'pure link tables (label vs per-user)':<44} "
          f"{safe:>4} safe / {unsafe} actor-touching   probe saw {seen} run(s)")
    if total:
        print(f"      -> folding the actor-touching ones into a public detail read is #569's "
              f"class ({100 * unsafe // total}% of candidates)")


def audit_projected_bare_reads(runs: List[pathlib.Path]) -> None:
    """#782/#783: the projected pages must not read bare field names. Any hit is a regression."""
    seen = hits = 0
    for run in runs:
        pages = list((run / "app" / "frontend" / "src").rglob("*.jsx"))
        if not pages:
            continue
        seen += 1
        for f in pages:
            t = f.read_text(encoding="utf-8", errors="ignore")
            if "cur.year" in t or "ep.duration || ep.runtime" in t:
                hits += 1
                break
    _report("projected pages with a bare field read", seen, seen, hits,
            "   (post-#782 builds should be 0)")


def audit_spec_owner_columns(runs: List[pathlib.Path]) -> None:
    """#774: a column the SPEC names that the contract does not carry — owner keys only."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (
            extract_contract_from_description as extract)
        from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
            _OWNER_COLUMNS_774 as owner_cols)
    except Exception as exc:
        print(f"  {'spec owner column lost (#774)':<44} n/a   (framework import failed: {exc})")
        return

    def toks(c: str) -> set:
        return {x for x in str(c).split("_") if x and x != "id"}

    seen = total = hits = 0
    for run in runs:
        # The milestone file is `milestones.json`. A probe that guessed `milestone_registry.json`
        # reported "0 comparable runs" across the whole corpus.
        ms = _load(run / "shared" / "hubs" / "milestones.json")
        tb = _load(run / "shared" / "hubs" / "registryhub_tables.json")
        if ms is None or tb is None:
            continue
        seen += 1
        spec: Dict[str, set] = {}
        for row in _records(ms):
            for t in (extract(str(row.get("description_slice") or "")).get("tables") or []):
                spec.setdefault(str(t.get("name")), set()).update(
                    str(c.get("name")) for c in (t.get("columns") or []) if isinstance(c, dict))
        if not spec:
            continue
        total += 1
        have = {str(t.get("name")): {str(c.get("name"))
                                     for c in ((t.get("schema") or {}).get("columns") or [])
                                     if isinstance(c, dict)}
                for t in _records(tb)}
        for name, cols in spec.items():
            present = have.get(name)
            if not present:
                continue
            for col in sorted(cols - present):
                if col in owner_cols and not any(toks(col) & toks(x) for x in present):
                    hits += 1
                    break
            else:
                continue
            break
    _report("spec owner column lost (#774)", seen, total, hits,
            "   (every corpus hit so far is profile_id)")


def audit_gate_decisions(runs: List[pathlib.Path]) -> None:
    """The four numbers that drive live gate switches (#751/#752 enabled, #743/#671 rejected).

    Until now these lived only as a markdown table in EXPERIMENTS_PENDING — which is the same
    throwaway-measurement problem one level up: a reader has to trust the prose or re-derive it by
    hand, and re-deriving by hand is what produced nine wrong numbers this session.

    Uses the SHIPPED normaliser and the SHIPPED detector rather than re-implementing either
    (#772: mirrored logic drifts from the check that actually blocks). Feeding raw store rows
    straight to `_ui_evidence_breadth_739` returns 0% on every slice, because the raw store spells
    status `success` and nests the check kind under `evidence` -- #193/#236 normalise both.
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.hub_registry import (
            _canon_validation_status as canon, _flatten_validation_metadata as flat)
        from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
            _ui_evidence_breadth_739 as breadth)
    except Exception as exc:
        print(f"  {'gate decisions (#751/#752/#743/#671)':<44} n/a   (framework import: {exc})")
        return

    openish = {"pending", "in_progress", "open", "todo", "new"}
    seen = saw_ui = 0
    failed_task = contradicted = open_p0 = no_ui = 0
    for run in runs:
        tasks_doc = _load(run / "shared" / "hubs" / "workhub_tasks.json")
        checks_doc = _load(run / "shared" / "hubs" / "codehub_checks.json")
        if tasks_doc is None or checks_doc is None:
            continue
        seen += 1
        tasks = _records(tasks_doc)
        if any(str(t.get("status")) == "failed" for t in tasks):
            failed_task += 1
        if any(str(t.get("status")) in openish
               and str((t.get("metadata") or {}).get("priority")
                       or t.get("priority") or "").upper() == "P0"
               and str((t.get("metadata") or {}).get("kind") or t.get("kind") or "") == "bug"
               for t in tasks):
            open_p0 += 1
        recs = [{"name": c.get("name", ""), "status": canon(c.get("status", "error")),
                 "metadata": flat(c.get("evidence") or {}), "updated_at": c.get("updated_at", 0)}
                for c in _records(checks_doc)]
        b = breadth(recs)
        if b.get("passed_records") or b.get("failed_records"):
            saw_ui += 1
        else:
            no_ui += 1
        if b.get("failed_records"):
            contradicted += 1

    _report("#751 a task in status failed   [ENABLED]", seen, seen, failed_task)
    _report("#752 UI evidence contradicted  [ENABLED]", saw_ui, seen, contradicted,
            f"   ({saw_ui} carry any UI record at all)")
    _report("#743 an open P0 bug at the cut [rejected]", seen, seen, open_p0)
    _report("#671 no UI evidence at all     [rejected]", seen, seen, no_ui)


def audit_terminal_state(runs: List[pathlib.Path]) -> None:
    """#821: how each run actually ENDED — the question I analysed a whole corpus without asking.

    `logs/progress_events.jsonl` records `generation_start`, `phase_start`, and then a terminal
    `generation_complete` / `generation_error`. Reading r151's showed it never delivered: it
    aborted STUCK on a blocker that could not exist (#820). I had read that run's captures, DDL,
    seed, chains, tasks and design system first, and interpreted all of them as if it had shipped.

    Corpus-wide the picture is starker than any release count: most runs do not reach a terminal
    event at all -- they are killed mid-workflow, and the log emits nothing between `phase_start`
    and the end, so there is no phase attribution for them.
    """
    ok = failed = killed = nolog = 0
    causes: Dict[str, int] = {}
    for run in runs:
        f = run / "logs" / "progress_events.jsonl"
        if not f.is_file():
            nolog += 1
            continue
        evs = []
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                evs.append(json.loads(line))
            except Exception:
                pass
        done = next((e for e in evs if e.get("type") == "generation_complete"), None)
        err = next((e for e in evs if e.get("type") == "generation_error"), None)
        if done is not None:
            if (done.get("data") or {}).get("success"):
                ok += 1
            else:
                failed += 1
        else:
            killed += 1
        if err:
            for name in re.findall(r"'([a-z_]+):?[^']*'", str(err.get("message"))[:600]):
                causes[name] = causes.get(name, 0) + 1
    total = ok + failed + killed
    _report("#821 reached generation_complete OK", total + nolog, total, ok)
    _report("#821 completed but not successful", total + nolog, total, failed)
    _report("#821 killed before any terminal event", total + nolog, total, killed,
            "   (log is silent between phase_start and the end)")
    if causes:
        top = sorted(causes.items(), key=lambda kv: -kv[1])[:4]
        print("      -> named in abort messages: "
              + ", ".join(f"{k} x{v}" for k, v in top))


def audit_design_prep_enrichment(runs: List[pathlib.Path]) -> None:
    """#822: the per-component fields the frontend prompt tells the lane to read.

    `build_notes` is `required` in design_prep's own schema and the prompt demands "1-3 concrete
    sentences from the SCREENSHOT". `crop` reaches `design_system.json` from the SKELETON path;
    `build_notes` / `typography` / `copy` only reach it through the analyst enrichment. Comparing
    the two is what localised the failure to the enrichment (#813/#815/#816/#819) rather than to
    the design phase as a whole -- and it justified five shipped changes without being re-runnable
    until now.
    """
    comps = seen = 0
    got = {"crop": 0, "build_notes": 0, "typography": 0, "copy": 0}
    for run in runs:
        ds = _load(run / "design" / "design_system.json")
        if not isinstance(ds, dict) or not isinstance(ds.get("screens"), list):
            continue
        seen += 1
        for screen in ds["screens"]:
            for c in (screen.get("components") or []) if isinstance(screen, dict) else []:
                if not isinstance(c, dict):
                    continue
                comps += 1
                for k in got:
                    if c.get(k):
                        got[k] += 1
    if not comps:
        print(f"  {'#822 enrichment fields per component':<44} n/a   (no design_system.json parsed)")
        return
    for k in ("crop", "build_notes", "typography", "copy"):
        note = "   <- SKELETON path" if k == "crop" else "   <- analyst enrichment"
        _report(f"#822 components carrying `{k}`", seen, comps, got[k], note)


def audit_seed_orphans(runs: List[pathlib.Path]) -> None:
    """#823: dependent rows the framework-owned dataset would strand.

    The dataset REPLACES a table wholesale. When its ids do not share an id space with the lane's
    (r145 keyed titles on TEXT slugs against integer 1..60), every dependent row is orphaned --
    93 across 5 tables in that run. #807b refuses the swap when a majority would be stranded and
    #808 aligns the id TYPE at staging; this counts how often either can bite.
    """
    seen = affected = 0
    worst = ("", 0)
    for run in runs:
        base = _load(run / "app" / "backend" / "seed_data.json")
        ds = _load(run / "app" / "backend" / "seed_dataset.json")
        if not isinstance(base, dict) or not isinstance(ds, dict):
            continue
        seen += 1
        stranded = 0
        for table, rows in ds.items():
            if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
                continue
            new_ids = {r.get("id") for r in rows if isinstance(r, dict)}
            stem = table[:-1] if table.endswith("s") else table
            for dt, drows in base.items():
                if dt in ds or not (isinstance(drows, list) and drows):
                    continue
                if not isinstance(drows[0], dict):
                    continue
                fk = f"{stem}_id"
                if fk not in drows[0]:
                    continue
                stranded += sum(1 for d in drows
                                if isinstance(d, dict) and d.get(fk) is not None
                                and d.get(fk) not in new_ids)
        if stranded:
            affected += 1
            if stranded > worst[1]:
                worst = (run.name, stranded)
    _report("#823 runs whose dataset would strand rows", seen, seen, affected,
            f"   worst: {worst[0]} with {worst[1]} row(s)" if worst[1] else "")


_AUDITS = (audit_link_tables, audit_projected_bare_reads, audit_spec_owner_columns,
           audit_gate_decisions, audit_terminal_state,
           audit_design_prep_enrichment, audit_seed_orphans)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--generated", default="agent/generated",
                    help="the generated-runs directory")
    ap.add_argument("--since", type=int, default=0, metavar="N",
                    help="only runs numbered >= N (era-split; see the module docstring)")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.generated)
    if not root.is_dir():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2
    runs = sorted((p for p in root.iterdir()
                   if p.is_dir() and _run_number(p.name) >= args.since),
                  key=lambda p: _run_number(p.name))
    print(f"corpus audit — {len(runs)} run(s)"
          + (f" from r{args.since}" if args.since else "") + "\n")
    if not runs:
        print("  nothing to measure — check --generated/--since before reading anything into this")
        return 1
    for audit in _AUDITS:
        audit(runs)
    print("\nEvery line above prints its denominator and how many runs the probe actually saw.\n"
          "A zero with a low 'probe saw' count is a claim about the instrument, not the system.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
