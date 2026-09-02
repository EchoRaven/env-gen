"""Seed data audit (Cutover 21)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
import logging
from typing import Optional, Any, Dict, List, Set
from .message_format import join_capped  # #1034


# Placeholder marker words (case-insensitive)
_PLACEHOLDER_WORDS = {
    "test", "foo", "bar", "baz", "qux", "asdf", "qwerty",
    "lorem", "ipsum", "placeholder", "dummy", "sample", "example_user",
    "todo", "tbd", "xxxx",
}

# Sequential name pattern: word followed by 1+ digits (e.g., user1, item_2, name3)
_SEQUENTIAL_RE = re.compile(r"^[a-zA-Z_]+[\s_-]?\d+$")


# #1202i: the framework's OWN staged asset paths are not lane-authored placeholder content.
#
# `ensure_assets_staged_for_build` writes avatars as `/assets/placeholders/ph-avatar-N.svg`,
# and the substring scan below then reads its own file naming as evidence that the lane wrote
# placeholder data. Measured over the 94 generated seeds: 181 tables cross the advisory
# threshold and 74 of them — 41% — do so ONLY because of these paths.
#
# This does not touch the policy the comments below describe. The BLOCKING check keeps its
# strict word-boundary vocabulary ("latest" must not hit "test"), and the advisory scan keeps
# its deliberate substring match over the full word list. It stops the audit reading the
# framework's own filenames as the lane's content, which is not a judgement about seeds at all.
def _is_framework_asset_1202i(value: str) -> bool:
    v = str(value or "")
    return v.startswith("/assets/") or "/assets/placeholders/" in v


def detect_placeholder_score(rows: List[dict]) -> float:
    if not rows:
        return 0.0
    score = 0.0

    # 1. Generic placeholder words in any string value
    # Each distinct placeholder word per value counts once (so "lorem ipsum"
    # in one value scores both 'lorem' and 'ipsum').
    placeholder_hit_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            if _is_framework_asset_1202i(v):
                continue
            lowered = v.lower()
            for word in _PLACEHOLDER_WORDS:
                if word in lowered:
                    placeholder_hit_count += 1
    score += min(placeholder_hit_count, 5) * 0.15

    # 2. Sequential-name pattern
    sequential_hits = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            if _SEQUENTIAL_RE.match(v.strip()):
                sequential_hits += 1
                break
    score += min(sequential_hits, 3) * 0.30

    # 3. All-same-boolean across rows (only if >=3 rows)
    if len(rows) >= 3:
        bool_columns: Dict[str, Set[bool]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                if isinstance(v, bool):
                    bool_columns.setdefault(k, set()).add(v)
        for vals in bool_columns.values():
            if len(vals) == 1:
                score += 0.20
                break  # only count once

    return min(score, 1.0)


@dataclass
class SeedReport:
    flagged_tables: List[dict] = field(default_factory=list)
    # #1168: {"table.column": orphan_count} for seeded rows whose owner FK points at a
    # parent that does not exist. Reported, never part of `is_clean` — a false seed
    # blocker wedges a run (#566j), and this is evidence for the lane, not a verdict.
    orphan_fk_rows: dict = field(default_factory=dict)
    # #1023d: how many tables this audit actually LOOKED AT, and how many it could have.
    # `is_clean` is `not flagged_tables`, so an audit that examined nothing returns True and
    # is indistinguishable from one that examined everything and found nothing wrong. #956
    # measured the gap: the loop only inspects tables still marked `defined`, and **145 of 147
    # runs have no `defined` table at all** — so for essentially the whole project this has
    # reported a clean verdict while inspecting zero tables.
    #
    # The VERDICT is deliberately unchanged. Making `is_clean` False when nothing was examined
    # would flag 145 of 147 runs, and #956 showed why that is wrong on the merits too: r154's
    # twelve tables would all read `missing_seed` while its live database held titles 60,
    # title_genres 57, episodes 16, genres 10 and four more, every one above the minimum — the
    # audit's notion of "seeded" is `list_seed_registrations()`, and the app seeds by SQL
    # INSERT. False blockers wedge runs (#566j).
    #
    # So this only stops the unmeasured state being INVISIBLE, the same way #790 publishes the
    # checks that could not run rather than letting them read as passes. The real repair counts
    # rows at gate time, which needs a live database and stays open.
    examined: int = 0
    candidates: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.flagged_tables

    @property
    def measured(self) -> bool:
        """False when the audit inspected nothing — `is_clean` then carries no information."""
        return self.examined > 0 or self.candidates == 0

    @property
    def all_flagged_paths(self) -> Set[str]:
        return {f"seed:{f['table']}" for f in self.flagged_tables}

    def to_dict(self) -> dict:
        return {
            "flagged_tables": list(self.flagged_tables),
            "is_clean": self.is_clean,
            # #1023d: a consumer reading is_clean must be able to see whether anything was read.
            "examined": self.examined,
            "candidates": self.candidates,
            "measured": self.measured,
        }


# #647, re-measured at #851 over 144 runs (2500 seeded tables, 12 distinct names — 3.5x #647's
# sample): rows per table are p10 **5**, median 12, p90 51, max 143. The bar still sits exactly on
# p10, and the share of real tables below it FELL from 3% to **1.2%** (6 below 3). Calibrated, not
# guessed — and now confirmed on a larger corpus rather than left at its original sample.
_DEFAULT_MIN_ROWS = 5
_PLACEHOLDER_THRESHOLD = 0.5


def _spine_tables_1039() -> frozenset:
    """Framework-owned identity/tenancy tables — never app seed content.

    Imports the canonical set rather than re-spelling it; `completeness_audit._SPINE_FALLBACK`
    is the precedent for the fallback, and the two agree member-for-member (checked).
    `_seed_meta` and `alembic_version` are framework BOOKKEEPING tables emitted by
    backend_skeleton's template, legitimately tiny or empty.
    """
    try:
        from .database_scaffold import _SPINE_OWNED_TABLES as _spine
        base = set(_spine)
    except Exception:
        base = {"tenants", "users", "oauth_clients", "oauth_authorization_codes"}
    return frozenset(base | {"_seed_meta", "alembic_version"})


def live_row_counts_1039(project_dir: Any, *, timeout: int = 30) -> Dict[str, int]:
    """Exact `COUNT(*)` per public table from the RUNNING database, or `{}`.

    #956's stated repair: "count ROWS at gate time — the database is up when this runs".
    The audit's notion of seeded-ness is `list_seed_registrations()`, which holds 0 records
    across the corpus while the app seeds via SQL INSERT, so the audit examined 0 tables in
    145 of 147 runs.

    ★ `COUNT(*)`, deliberately, NOT `pg_stat_user_tables.n_live_tup`. That column is an
    autovacuum ESTIMATE and can read 0 for a freshly-seeded table — a false zero here becomes
    a false `missing_seed` blocker, and false blockers wedge runs (#566j cost r117/r120 a
    75-minute no-deliver abort). An estimate is not a count.

    Returns `{}` on ANY failure — no DB, no container, bad parse. An empty result must mean
    "not measured" and is never interpreted as "every table is empty".
    """
    from pathlib import Path as _P
    counts: Dict[str, int] = {}
    try:
        proj = _P(project_dir)
        # #563's trap: callers hold `app_root` (<project>/app) as often as the project root,
        # and a compose file looked for in the wrong one reads as "no database" — a silent
        # downgrade to the dead path. Accept either, plus the compose dir itself.
        #
        # #1044 (r176, live): every LANE gets a git worktree under `<project>/worktrees/<lane>/`
        # and each one carries its own `docker/docker-compose.yml`, so the search above happily
        # matched `worktrees/orchestrator/docker/docker-compose.yml` — a real file whose compose
        # project has NO containers. Only one stack runs, launched from the canonical
        # `<project>/docker/`. The symptom was not an error: it was
        # `#1039 ... DID NOT RUN (no database container resolved from .../worktrees/orchestrator/
        # docker/docker-compose.yml)`, i.e. the audit silently reverting to the dead path on a
        # run whose database was up and healthy. Hoist out of a worktree FIRST so the canonical
        # tree always wins.
        _parts = proj.parts
        if "worktrees" in _parts:
            proj = _P(*_parts[:_parts.index("worktrees")])
        compose = None
        for cand in (proj / "docker" / "docker-compose.yml",
                     proj.parent / "docker" / "docker-compose.yml",
                     proj / "docker-compose.yml"):
            if cand.exists():
                compose = cand
                break
        if compose is None:
            return _not_measured_1039("no docker-compose.yml under %s (nor its parent)" % proj)
        from .container_runtime import runtime_bin
        cid = _db_container_1039(compose, timeout)
        if not cid:
            return _not_measured_1039(
                "no database container resolved from %s (tried services database/db/postgres)"
                % compose)
        import subprocess
        # one round trip: build a UNION ALL of exact counts over the public tables
        sql = (
            "SELECT string_agg(format('SELECT %L AS t, COUNT(*) AS n FROM %I', "
            "tablename, tablename), ' UNION ALL ') FROM pg_tables "
            "WHERE schemaname = 'public'")
        def _psql(q):
            return subprocess.run(
                [runtime_bin(), "exec", cid, "sh", "-c",
                 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAF"\t" -c ' + _shq(q)],
                capture_output=True, text=True, timeout=timeout)
        built = _psql(sql)
        inner = (built.stdout or "").strip()
        if built.returncode != 0 or not inner:
            return _not_measured_1039(
                "could not list public tables: rc=%s %s"
                % (built.returncode, (built.stderr or "").strip()[:200]))
        res = _psql(inner)
        if res.returncode != 0:
            return _not_measured_1039(
                "COUNT(*) query failed: rc=%s %s"
                % (res.returncode, (res.stderr or "").strip()[:200]))
        for line in (res.stdout or "").splitlines():
            if "\t" not in line:
                continue
            t, _, n = line.partition("\t")
            try:
                counts[t.strip()] = int(n.strip())
            except ValueError:
                continue
        if not counts:
            return _not_measured_1039("the query returned no parseable rows")
    except Exception as exc:
        return _not_measured_1039("%s: %s" % (type(exc).__name__, exc))
    return counts


def orphan_fk_rows_1168(project_dir: Any, *, timeout: int = 30) -> Dict[str, int]:
    """Seeded rows whose owner FK points at a parent that does not exist.

    The framework audits seed DENSITY (#84's floor, #1039's live COUNT(*)) and never
    once audits whether those rows REFERENCE anything. #1105 is what that costs: a seed
    backfilled a tenant nobody created, `users.tenant_id` pointed at it, and 58 of 59 runs
    lost every seeded user — found by disaster, not by a check. #1160 produced the same
    shape from the other end (the owner auto-fill wrote a USER id into a PROFILE column,
    so every my_list row referenced a profile that does not exist) and the only reason it
    surfaced was a hand probe of a live app.

    The DDL carries no FK CONSTRAINTS — #1162's foreign keys are ORM metadata, and the
    tables come from `01_init.sql` — so `information_schema` cannot answer this. The
    parentage is derived with the SAME rule #1162 renders from, `<x>_id` -> a table named
    `<x>`/`<x>s`/`<x>es`, entirely inside SQL so the two cannot drift on a
    schema this function never sees.

    Returns ``{"table.column": orphan_count}`` for the columns that HAVE orphans, or
    ``{}``. Like #1039: an empty result means "not measured or clean", never "everything
    is broken" — this is evidence, not a gate.
    """
    from pathlib import Path as _P
    out: Dict[str, int] = {}
    try:
        proj = _P(project_dir)
        _parts = proj.parts
        if "worktrees" in _parts:          # #1044: lanes carry their own dead compose
            proj = _P(*_parts[:_parts.index("worktrees")])
        compose = None
        for cand in (proj / "docker" / "docker-compose.yml",
                     proj.parent / "docker" / "docker-compose.yml",
                     proj / "docker-compose.yml"):
            if cand.exists():
                compose = cand
                break
        if compose is None:
            return out
        from .container_runtime import runtime_bin
        import subprocess
        cid = _db_container_1039(compose, timeout)
        if not cid:
            return out

        def _psql(q):
            return subprocess.run(
                [runtime_bin(), "exec", cid, "sh", "-c",
                 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAF"\t" -c ' + _shq(q)],
                capture_output=True, text=True, timeout=timeout)

        # Build one UNION ALL over every `<x>_id` column whose stem names a real table.
        build = (
            "SELECT string_agg(format("
            "  'SELECT %L, count(*) FROM %I c LEFT JOIN %I p ON c.%I = p.id"
            "   WHERE c.%I IS NOT NULL AND p.id IS NULL',"
            "  c.table_name||'.'||c.column_name, c.table_name, t.tablename,"
            "  c.column_name, c.column_name), ' UNION ALL ')"
            " FROM information_schema.columns c"
            " JOIN pg_tables t ON t.schemaname='public' AND t.tablename IN ("
            "   left(c.column_name, -3), left(c.column_name, -3)||'s',"
            "   left(c.column_name, -3)||'es')"
            " WHERE c.table_schema='public' AND c.column_name LIKE '%_id'"
            "   AND c.table_name <> t.tablename"
            "   AND EXISTS (SELECT 1 FROM information_schema.columns pk"
            "               WHERE pk.table_schema='public' AND pk.table_name=t.tablename"
            "                 AND pk.column_name='id')")
        built = _psql(build)
        inner = (built.stdout or "").strip()
        if built.returncode != 0 or not inner:
            return out
        res = _psql(inner)
        if res.returncode != 0:
            return out
        for line in (res.stdout or "").splitlines():
            if "\t" not in line:
                continue
            col, _, n = line.partition("\t")
            try:
                cnt = int((n or "0").strip())
            except ValueError:
                continue
            if cnt > 0:
                out[col.strip()] = cnt
    except Exception:
        return {}
    return out


def _not_measured_1039(why: str) -> Dict[str, int]:
    """Announce that the live row count did not happen, and return the empty mapping.

    #883's rule: an empty default inside a gate/audit must SAY it could not run, or it reads
    as a clean measurement. Here `{}` is the fail-open direction — it silently reverts the
    seed audit to the status-filter path that examines 0 tables in 145 of 147 runs — so the
    reason has to reach the log or the degradation is invisible. Same argument as `#790`'s
    `_swallowed_790`, spelled locally because importing `delivery_gate` from an audit it
    feeds would be circular.
    """
    try:
        logging.getLogger(__name__).warning(
            "#1039 live seed row-count DID NOT RUN (%s) — falling back to the "
            "`status == 'defined'` filter, which examines 0 tables in 145 of 147 runs. The "
            "audit's verdict below is therefore NOT CHECKED, not clean.", why)
    except Exception:
        pass
    return {}


_SAID_0_OF_1202V = None


def _db_container_1039(compose, timeout: int) -> str:
    """Resolve the database container id from the compose file, or "".

    A separate function so the per-service probe's `except: continue` is not an empty-default
    ASSIGN inside a gate file — #883 flags those, correctly, because that shape is how a
    failed probe comes to read as a measurement.
    """
    from .container_runtime import container_id
    # #1202x: probe only the services this compose file actually declares. The blind sweep
    # over ("database", "db", "postgres") means two of the three name a service the project
    # does not have, and each miss costs a `docker ps` and an ERROR line saying it found
    # other runs' containers instead. r30 logged 132 of those for `db` alone, on a project
    # whose only database service is `database` — an error about a service that was never
    # supposed to exist. Falls back to the full list when the file cannot be read, so a
    # parse failure loses nothing.
    _declared = _compose_services_1202x(compose)
    _order = [s for s in ("database", "db", "postgres") if not _declared or s in _declared]
    for svc in (_order or ["database", "db", "postgres"]):
        try:
            cid = container_id(compose, svc, timeout=timeout)
        except Exception:
            continue
        if cid:
            return cid
    return ""


def _compose_services_1202x(compose) -> set:
    """Service names declared in a compose file, or an empty set if it cannot be read.

    Deliberately not a YAML parse: this runs inside a gate, pyyaml is not guaranteed here, and
    an empty set means "do not narrow", which is the safe direction.
    """
    out = set()
    try:
        from pathlib import Path as _P
        import re as _re1202x
        text = _P(compose).read_text(encoding="utf-8")
        body = text.split("\nservices:", 1)
        if len(body) < 2:
            return out
        for line in body[1].splitlines():
            if line[:1] not in (" ", "\t") and line.strip():
                break                       # left the services block
            m = _re1202x.match(r"^  ([A-Za-z0-9._-]+):\s*$", line)
            if m:
                out.add(m.group(1))
    except Exception:
        return set()
    return out


def _shq(s: str) -> str:
    """Single-quote a string for `sh -c`."""
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


def audit_seed_data(hub_registry, project_dir: Any = None) -> SeedReport:
    schema_hub = getattr(hub_registry, "schema_hub", None)
    if schema_hub is None or not hasattr(schema_hub, "list_tables"):
        return SeedReport()
    tables = schema_hub.list_tables() or {}
    seed_regs = schema_hub.list_seed_registrations() or {}

    # #956 repair: when the database is reachable, its exact row counts are authoritative and
    # the `status == "defined"` filter (which skips 1729 of 1745 corpus tables) is bypassed.
    # Strictly additive: `{}` — no DB, no compose, any error — leaves every branch below
    # exactly as it was.
    _live = live_row_counts_1039(project_dir) if project_dir is not None else {}
    # #1168: density was audited, parentage never was. Same additive contract as #1039:
    # `{}` on no DB / no compose / any error, so every branch below is untouched.
    _orphans_1168 = (orphan_fk_rows_1168(project_dir)
                     if project_dir is not None else {})
    _spine = _spine_tables_1039()

    flagged: List[dict] = []
    _examined_956 = 0
    for name, table in tables.items():
        if _live:
            if name in _spine or name not in _live:
                # framework-owned, or the DB does not have this table at all (declared but
                # never created) — the latter is a SCHEMA defect other checks own, and
                # answering "missing seed" for it would name the wrong cause.
                continue
            _examined_956 += 1
            meta = table.get("metadata") or {}
            min_rows = meta.get("min_seed_rows", _DEFAULT_MIN_ROWS)
            if min_rows == 0:
                continue
            n = _live[name]
            if n == 0:
                flagged.append({
                    "table": name, "reason": "missing_seed",
                    "detail": {"min_seed_rows": min_rows, "live_row_count": 0,
                               "source": "live COUNT(*) at gate time (#956)"}})
            elif n < min_rows:
                flagged.append({
                    "table": name, "reason": "low_row_count",
                    "detail": {"row_count": n, "min_seed_rows": min_rows,
                               "source": "live COUNT(*) at gate time (#956)"}})
            continue
        if (table.get("status") or "defined") != "defined":
            continue
        _examined_956 += 1
        meta = table.get("metadata") or {}
        min_rows = meta.get("min_seed_rows", _DEFAULT_MIN_ROWS)
        if min_rows == 0:
            continue  # explicit opt-out

        reg = seed_regs.get(name)
        if reg is None:
            flagged.append({
                "table": name,
                "reason": "missing_seed",
                "detail": {"min_seed_rows": min_rows,
                           # #694: say WHAT register_seed_data is. The old hint read as if the
                           # generated app needed a startup call, and that is exactly how it was
                           # read: an agent spent a multi-turn investigation on a "seed-gate
                           # blocker" and reported back "recommended routing a backend task to
                           # add register_seed_data() startup" — the wrong lane, the wrong
                           # artifact, and a task queued against app code that must never
                           # contain it. It is an AGENT-FACING HUB TOOL (tools/seed_tools.py:19,
                           # NAME = "register_seed_data"); the caller of this audit calls it
                           # itself after inserting rows. Same class as #682 and #690: the
                           # remediation text, not the detection, is what costs the rounds.
                           #
                           # Rare but expensive: `missing_seed` fires 14 times across 253 logs,
                           # because the loop above only examines tables still marked `defined`
                           # and 1632 of the corpus's 1648 table records are `implemented` by
                           # then. Low frequency, high per-firing cost — which is the argument
                           # for fixing the wording rather than the detector.
                           #
                           # #694b, two measurements that bound how bad the old wording was and
                           # add one thing the paragraph above does not cover. First the cost:
                           # `[backend] GREP pattern=register_seed_data scope=app/backend` runs
                           # 84 times across 18 runs, every one returning "0 matches", and 3
                           # runs escalate to `P0 delivery-gate: register_seed_data for all 12
                           # tables (0/12 registered)`. Then the outcome: 0 `seed_registered`
                           # events and registryhub_seed_registrations at _meta.version 1
                           # (create only) in 146 of 146 runs — the tool has never once been
                           # called successfully, so this hint has never yet led anywhere.
                           #
                           # And the part that is not just wording: the `seed` bundle is granted
                           # to orchestrator and verifier only — backend, frontend and debugger
                           # do not hold it (agents_config.yaml). "Call it yourself" is the
                           # right instruction for the audit's caller and an impossible one for
                           # whoever the blocker is dispatched to, which is `backend` in all 18
                           # of those runs. The sentence below therefore says what to do when
                           # you do not have the tool, rather than assuming you do. Changing the
                           # GRANT is a routing decision with blast radius past this audit and
                           # is deliberately not made here.
                           "hint": ("Seed this table, then call the `register_seed_data` HUB "
                                    "TOOL yourself to record the row count. Do NOT add a "
                                    "register_seed_data() call to the generated backend — it "
                                    "is not app code and nothing in the app can call it. "
                                    "It also requires the table to be registered first. If the "
                                    "tool is not in your toolset, do not go looking for it in "
                                    "the app — report that you lack it and hand the item back; "
                                    "it lives in the `seed` bundle, which not every role "
                                    "holds.")},
            })
            continue

        row_count = reg.get("row_count", 0)
        if row_count < min_rows:
            flagged.append({
                "table": name,
                "reason": "low_row_count",
                "detail": {"row_count": row_count,
                           "min_seed_rows": min_rows},
            })
            continue

        score = detect_placeholder_score(reg.get("sample_excerpt") or [])
        if score >= _PLACEHOLDER_THRESHOLD:
            flagged.append({
                "table": name,
                "reason": "placeholder_content",
                "detail": {"placeholder_score": round(score, 2),
                           "threshold": _PLACEHOLDER_THRESHOLD,
                           "sample_size": len(reg.get("sample_excerpt") or [])},
            })

    # #956: a clean report from an audit that examined NOTHING is not a clean report.
    #
    # The loop above skips any table whose status is not exactly "defined". Across the corpus
    # that is 1729 `implemented` against 16 `defined`, and **145 of 147 runs have no `defined`
    # table at all** — so this audit has been returning "clean" while looking at zero tables.
    #
    # ★ Deliberately NOT widened to `implemented` here. r154 would then flag all twelve tables as
    # `missing_seed` while its database actually holds titles 60, title_genres 57, episodes 16,
    # genres 10, my_list 8, continue_watching 7, profiles 6, ratings 5 — every one above
    # `_DEFAULT_MIN_ROWS`. The app seeds through SQL INSERT and this audit's notion of "seeded" is
    # `list_seed_registrations()`, which returns 0. Widening the filter without also fixing the
    # definition would turn a dead check into twelve false blockers on a correctly seeded app,
    # and false blockers wedge runs (#566j, r117/r120: a 75-minute no-deliver abort).
    #
    # So: say the state out loud, change no verdict. The real repair is to count ROWS at gate time
    # — the database is up when this runs — and that needs a live run to validate, not a unit test.
    if not _examined_956 and tables:
        # #1202v: say it when the STATE changes, not once per gate evaluation. Measured:
        # r26 156 identical lines, r30 213, r22-r25 40-132 — for one unchanging fact.
        # #1202n removed the same noise from the heal declines; the rule is the same, and a
        # state that moves is still reported. The verdict is untouched.
        _state1202v = len(tables)
        global _SAID_0_OF_1202V
        if _SAID_0_OF_1202V != _state1202v:
            _SAID_0_OF_1202V = _state1202v
            logging.getLogger(__name__).warning(
            "SEED AUDIT EXAMINED 0 OF %d TABLES: every one has a status other than 'defined', "
            "which is the only status this audit inspects (corpus: 1729 implemented vs 16 "
            "defined; 145 of 147 runs have none). Its clean verdict below means NOT CHECKED, not "
            "nothing wrong. %d seed registration(s) exist while the app seeds via SQL. "
            "#956's repair IS now implemented — the audit counts live rows when it can reach "
            "the database — so reaching this line means the live count came back EMPTY: no "
            "project_dir was passed, no docker-compose.yml was found under it, or the db "
            "container/query failed. Fix the reachability, not the status filter.",
            len(tables), len(seed_regs))
    # #1023d: carry the coverage with the verdict, not only in a log line — a consumer reading
    # `is_clean` must be able to tell "checked and fine" from "checked nothing".
    return SeedReport(flagged_tables=flagged, examined=_examined_956,
                      candidates=len(tables), orphan_fk_rows=_orphans_1168)


# ---------------------------------------------------------------------------
# Fix #54 — content-quality audit of the AUTHORED app/backend/seed_data.json.
# The #41 gate proves the lane authored SOMETHING; this proves it authored
# ENOUGH and authored it REALISTICALLY (info density + state realism = the top
# similarity lever, PIPELINE.md; run-33 shipped SUCCESS on a 2-row token seed).
# Deliberately CONSERVATIVE — it feeds a NON-WAIVABLE deliverability blocker, so
# every signal must be near-zero-false-positive (adversarial review w6x6art4t
# killed two draft signals for false-blocking realistic seeds: the sequential-
# name rule — 'msg_1' string FK ids / 'Room 101' / 'iPhone 15' ARE realistic —
# and the full marker list — 'test'/'sample'/'bar'/'tbd' are ordinary domain
# vocabulary). What remains:
#   * thin seed — fewer than ENVGEN_SEED_MIN_TOTAL_ROWS (default 10) structured
#     rows in TOTAL across all tables ("a dozen realistic emails … populated on
#     first load" needs double digits; any real authoring attempt clears this;
#     0 structured rows also lands here — a {table: ["str", ...]} shape passes
#     #41's non-empty-list check but seeds nothing);
#   * unambiguous placeholder markers — ≥2 DISTINCT words from the STRICT set
#     below on WORD BOUNDARIES in one table (unlike detect_placeholder_score's
#     substring match, "latest" must NOT hit "test" — and 'test'/'sample' are
#     not in this set at all: a QA-tracker's realistic seed says 'test' in
#     every row).
# ---------------------------------------------------------------------------

# #647, re-measured at #851 across **151** runs: total seeded rows per run are median **145**
# (max 357). 144 runs authored a seed at all and their MINIMUM is **60** — six times the floor,
# with **zero near-misses** (no run lands between 10 and 20). The 7 runs below it authored nothing
# whatsoever, and all 7 are the early-killed class (#821): r19, r35, r38, r42, r44, r136, r140 —
# the same population as the audit exclusions in EXPERIMENTS item 171. The floor separates "the
# lane authored nothing" from real data with a margin that got WIDER on the larger sample.
_MIN_AUTHORED_TOTAL_ROWS = 10

# Strict subset of _PLACEHOLDER_WORDS that is placeholder in ANY domain. The
# full set stays for the ADVISORY registration audit (waived once functionally
# validated).
#
# #851: the claim here used to read "this hard-gate set must never collide with legitimate
# vocabulary". That is FALSE AS WRITTEN, and the counter-examples are exactly the non-Netflix
# domains this framework exists to generate: `qwerty` is keyboard vocabulary (a typing tutor, a
# peripherals store), `placeholder` is form vocabulary (a CMS, a form builder), `foo` is a band
# name, `dummy` is a crash-test noun. A blocking gate justified by an assertion that its own
# generality goal falsifies is #788's shape.
#
# What is actually true, and what makes it safe, is the **>=2 DISTINCT words in ONE table** rule
# below — a false positive needs two independent collisions in the same table, not one. That rule
# is the protection, and until #851 nothing tested it.
#
# Exposure, measured: **0 of 151 runs** contain even ONE of these words in any seed row. So the
# false-positive record is not "clean", it is EMPTY — the gate has never fired, and any claim
# about its precision is a prediction. Stated that way on purpose.
_HARD_MARKER_WORDS = frozenset({
    "lorem", "ipsum", "placeholder", "dummy", "asdf", "qwerty", "xxxx",
    "foo", "baz", "qux", "example_user",
})


def _word_boundary_markers(rows: List[dict]) -> List[str]:
    """DISTINCT hard-marker words appearing on a word boundary in any string
    value of ``rows`` (case-insensitive)."""
    hits: Set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            lowered = v.lower()
            for word in _HARD_MARKER_WORDS:
                if word in hits:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", lowered):
                    hits.add(word)
    return sorted(hits)


def audit_authored_seed(data: Any) -> List[str]:
    """Content-quality issues with an authored seed mapping ({table: [rows]}).

    Returns human-readable issue strings ([] = acceptable). Pure + deterministic
    (recomputed each gate tick, so a rewritten seed self-clears); tolerant of
    arbitrary JSON shapes — non-dict input is not audited; non-dict ROWS are not
    counted as structured rows (so a strings-only "seed" can't satisfy the
    floor)."""
    import os
    if not isinstance(data, dict):
        return []
    try:
        min_total = int(os.environ.get("ENVGEN_SEED_MIN_TOTAL_ROWS",
                                       str(_MIN_AUTHORED_TOTAL_ROWS)))
    except Exception:
        min_total = _MIN_AUTHORED_TOTAL_ROWS
    issues: List[str] = []
    total = 0
    for table, rows in data.items():
        if not isinstance(rows, list):
            continue
        dict_rows = [r for r in rows if isinstance(r, dict)]
        total += len(dict_rows)
        if not dict_rows:
            continue
        markers = _word_boundary_markers(dict_rows)
        if len(markers) >= 2:
            issues.append(
                f"table '{table}' reads as placeholder content "
                f"(markers: {join_capped(markers, len(markers), cap=5, sep=', ')}) "
                "— replace those exact "
                "values with believable domain content")
    if total < min_total:
        issues.append(
            f"only {total} structured row(s) (JSON objects) total across all "
            f"tables — populated list screens need >= {min_total}; add realistic "
            "rows (mixed states, believable names/subjects/timestamps) until the "
            "screens look like the references")
    return issues


def amplify_authored_seed(data: Any, min_total: Optional[int] = None) -> Any:
    """FIX #84 (instagram run-5, live): deterministically AMPLIFY a realistic-but-thin
    authored seed to the density floor by cloning-and-perturbing the lane's OWN rows —
    the lane authored 9 believable rows, the gate demands >= 10, and 7 remediation
    dispatches went unanswered → STUCK-abort while the DB was already dense (the gate
    audits the FILE). The framework owns the density floor like #74 owns demo
    concentration.

    Clones get: a fresh pk (int max+n / string suffix), perturbed unique credentials
    (email/username/handle/slug), timestamps shifted minutes apart, and ``<x>_id`` FK
    values rotated within the seed's own ``<x>s`` id pool; the tuple of a clone's FK
    fields is deduped against every existing row so join-table UNIQUE constraints can't
    collide (an exhausted combo space just stops cloning that table). Marker-flagged
    (placeholder) seeds are NOT amplified — garbage×N is garbage; dense/clean seeds
    return None (untouched). Pure + deterministic; returns the amplified mapping or
    None when no change is needed/possible."""
    import copy
    import os
    issues = audit_authored_seed(data)
    if not issues or any("placeholder content" in i for i in issues):
        return None
    if not any("structured row" in i for i in issues):
        return None
    if min_total is None:
        try:
            min_total = int(os.environ.get("ENVGEN_SEED_MIN_TOTAL_ROWS",
                                           str(_MIN_AUTHORED_TOTAL_ROWS)))
        except Exception:
            min_total = _MIN_AUTHORED_TOTAL_ROWS

    out = copy.deepcopy(data)
    tables = {t: rows for t, rows in out.items()
              if isinstance(rows, list) and any(isinstance(r, dict) for r in rows)}
    if not tables:
        return None

    # id pools per table (for FK rotation) + existing FK-field combos per table
    pools: Dict[str, List[Any]] = {
        t: [r["id"] for r in rows if isinstance(r, dict) and r.get("id") is not None]
        for t, rows in tables.items()}
    int_id_next: Dict[str, int] = {
        t: (max([i for i in ids if isinstance(i, int)] or [0]) + 1)
        for t, ids in pools.items()}

    def _fk_fields(row: dict) -> List[str]:
        return sorted(k for k in row if k != "id" and str(k).endswith("_id"))

    def _combo(row: dict):
        return tuple((k, row.get(k)) for k in _fk_fields(row))

    seen_combos: Dict[str, set] = {}
    for t, rows in tables.items():
        seen_combos[t] = {_combo(r) for r in rows if isinstance(r, dict) and _fk_fields(r)}

    def _shift_ts(val: str, n: int) -> str:
        try:
            from datetime import datetime, timedelta
            s = str(val)
            suffix = "Z" if s.endswith("Z") else ""
            dt = datetime.fromisoformat(s.rstrip("Z"))
            return (dt + timedelta(minutes=7 * n + 3)).isoformat() + suffix
        except Exception:
            return val

    total = sum(len([r for r in rows if isinstance(r, dict)]) for rows in tables.values())
    n = 0
    stalled = False
    while total < min_total and not stalled:
        stalled = True
        for t, rows in tables.items():
            if total >= min_total:
                break
            src_rows = [r for r in rows if isinstance(r, dict)]
            if not src_rows:
                continue
            base = src_rows[n % len(src_rows)]
            clone = copy.deepcopy(base)
            n += 1
            # fresh pk
            if "id" in clone:
                if isinstance(clone["id"], int):
                    clone["id"] = int_id_next[t]
                    int_id_next[t] += 1
                else:
                    clone["id"] = f"{clone['id']}-a{n}"
            # unique credentials
            v = clone.get("email")
            if isinstance(v, str) and "@" in v:
                local, _, dom = v.partition("@")
                clone["email"] = f"{local}+a{n}@{dom}"
            for k in ("username", "handle", "slug"):
                if isinstance(clone.get(k), str):
                    clone[k] = f"{clone[k]}-a{n}"
            # timestamps drift apart
            for k, v in list(clone.items()):
                if str(k).endswith("_at") and isinstance(v, str):
                    clone[k] = _shift_ts(v, n)
            # rotate FK values within their pools; dedup the combo (UNIQUE safety)
            fks = _fk_fields(clone)
            placed = False
            for attempt in range(4 + max((len(pools.get(str(k)[:-3] + "s", []))
                                          for k in fks), default=0)):
                for k in fks:
                    ref = str(k)[:-3]
                    pool = pools.get(ref + "s") or pools.get(ref) or []
                    if pool:
                        cur = clone.get(k)
                        idx = (pool.index(cur) if cur in pool else 0)
                        clone[k] = pool[(idx + n + attempt) % len(pool)]
                if not fks or _combo(clone) not in seen_combos.get(t, set()):
                    placed = True
                    break
            if not placed:
                continue                                   # combo space exhausted → skip
            if fks:
                seen_combos.setdefault(t, set()).add(_combo(clone))
            rows.append(clone)
            if clone.get("id") is not None:
                pools.setdefault(t, []).append(clone["id"])
            total += 1
            stalled = False
    grew = total > sum(len([r for r in rows if isinstance(r, dict)])
                       for rows in data.values() if isinstance(rows, list))
    return out if grew else None


__all__ = ["SeedReport", "audit_seed_data", "detect_placeholder_score",
           "audit_authored_seed", "amplify_authored_seed"]
