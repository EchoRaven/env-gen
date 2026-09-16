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


def schema_currency_1202fj(project_dir: Any) -> Dict[str, Any]:
    """Is the RUNNING database's schema the one these ORM models describe?

    {"verdict": "current"|"drifted"|"unknown", "detail": str}. Same contract as
    #1202ex's build currency, and for the same reason: a projected route that 500s is
    reported as an application defect, so the framework has to be able to say whether it
    was judging what it built.

    Only the MATCH is exact. A drift lists the columns the models declare and the live
    table lacks -- which is the direction that 500s (`SELECT` of a missing column). Extra
    live columns are not reported: an older column the models dropped harms nothing.

    Never raises; an unreadable database says so rather than claiming either verdict.
    """
    try:
        live = live_schema_1202fj(project_dir)
        if not live:
            return {"verdict": "unknown", "detail": "the live schema could not be read"}
        from .route_projector import _orm_models
        from pathlib import Path as _P
        proj = _P(str(project_dir))
        backend = proj / "app" / "backend"
        if not backend.is_dir():
            return {"verdict": "unknown", "detail": "no app/backend to read models from"}
        models = _orm_models(backend) or {}
        if not models:
            return {"verdict": "unknown", "detail": "no ORM models parsed"}
        missing = []
        for table, meta in models.items():
            have = live.get(table)
            if have is None:
                continue          # table absent entirely is #952's territory, not this
            for col in (meta.get("cols") or []):
                if col not in have:
                    missing.append("%s.%s" % (table, col))
        if not missing:
            return {"verdict": "current",
                    "detail": "every modelled column exists in the running database"}
        return {"verdict": "drifted",
                "detail": ("the running database is older than these models -- %d modelled "
                           "column(s) do not exist in it (%s%s). A projected read of any of "
                           "them 500s with UndefinedColumn. Recreate the stack "
                           "(compose down -v && up) before trusting these results."
                           % (len(missing), ", ".join(sorted(missing)[:8]),
                              ", ..." if len(missing) > 8 else ""))}
    except Exception as exc:
        return {"verdict": "unknown", "detail": "%s: %s" % (type(exc).__name__, exc)}


def live_schema_1202fj(project_dir: Any, *, timeout: int = 30) -> Dict[str, set]:
    """{table: {column, ...}} as the RUNNING database actually has it, or {} when unreadable.

    The compose file mounts `app/database/init/01_init.sql` at
    /docker-entrypoint-initdb.d, and Postgres runs those scripts ONLY on an empty volume --
    with `CREATE TABLE IF NOT EXISTS` besides. So when the ORM models change after a stack
    is up, the DDL is regenerated and written, the live tables do not move, and the
    projected handlers -- built from the CURRENT models -- SELECT columns that do not
    exist:

        (psycopg.errors.UndefinedColumn) column "actor_name" does not exist

    tiktok-r96 died on that twice. It reads as an application defect on a route tagged
    FRAMEWORK-PROJECTED, and it sent me chasing a type-mismatch regression that was not
    there (see the correction on a5030b03).

    The drift is a WINDOW, not a state: measured directly against r96's live database right
    after a `down -v && up`, models and schema agreed exactly. It opens when the models move
    after the stack is up and closes at the next recreate.

    Same shape as #1202ex, which measures whether the IMAGE is the source on disk; this
    measures whether the SCHEMA is the models. Reuses this module's container resolution and
    psql pattern rather than opening a second way to reach the database.
    """
    out: Dict[str, set] = {}
    try:
        from pathlib import Path        # module-local, as the other probes here do
        proj = Path(str(project_dir))
        compose = None
        for cand in (proj / "docker" / "docker-compose.yml",
                     proj.parent / "docker" / "docker-compose.yml",
                     proj / "docker-compose.yml"):
            if cand.exists():
                compose = cand
                break
        if compose is None:
            return {}
        from .container_runtime import runtime_bin
        cid = _db_container_1039(compose, timeout)
        if not cid:
            return {}
        import subprocess
        q = ("SELECT table_name, column_name FROM information_schema.columns "
             "WHERE table_schema = 'public'")
        res = subprocess.run(
            [runtime_bin(), "exec", cid, "sh", "-c",
             'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAF"\t" -c ' + _shq(q)],
            capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            return {}
        for line in (res.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            out.setdefault(parts[0].strip(), set()).add(parts[1].strip())
    except Exception as exc:
        # Not silent: an empty result here reads as "the schema matched" to any caller
        # that does not know the difference, which is #883's failure mode. It also hid a
        # NameError in this function's first draft -- `Path` is imported per-probe in this
        # module and I had left it out, so every call returned {} and looked like a clean
        # measurement. Say which it was.
        from .message_format import state_changed_1202ad
        if state_changed_1202ad("live_schema_1202fj", "%s: %s" % (type(exc).__name__, exc)):
            logging.getLogger(__name__).warning(
                "#1202fj live schema read FAILED (%s: %s) — schema currency is NOT CHECKED, "
                "not clean.", type(exc).__name__, str(exc)[:160])
        return {}
    return out


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
        # #1202fb: state, not heartbeat. netflix-r43 (live) printed this 57 times in one run
        # against 9 successful counts of the same measurement, and the successes are quiet --
        # so the log says "NOT CHECKED, not clean" 57 times about an audit that DID run. It
        # misread that way to me while mining, which is the whole failure mode #883 exists to
        # prevent, arriving from the other direction: not a silent empty, a deafening one.
        #
        # The repeats are legitimate and transient -- the audit is called between validations
        # while the stack is down -- so `warn_once_1201` is the wrong shape twice over: it
        # would drop the count, and its wording ("the mechanism being OFF, not a transient")
        # would be false here.
        #
        # #1202ad's helper is the right one and this is its SIXTH site; its own table lists
        # `#1202v seed audit "0 of N"` -- this same file, already fixed once for the same
        # noise, at a different line. A reason that CHANGES still prints in full, and so does
        # a return to a reason already seen, which is what keeps #883's rule intact.
        from .message_format import state_changed_1202ad
        if state_changed_1202ad("seed_audit:not_measured_1039", str(why)):
            logging.getLogger(__name__).warning(
                "#1039 live seed row-count DID NOT RUN (%s) — falling back to the "
                "`status == 'defined'` filter, which examines 0 tables in 145 of 147 runs. The "
                "audit's verdict below is therefore NOT CHECKED, not clean.", why)
        else:
            logging.getLogger(__name__).debug(
                "#1039 live seed row-count still not running (%s)", why)
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


_LIVE_COUNTS_REL_1202DJ = "shared/seed_live_counts_1202dj.json"
# The stack is torn down and rebuilt around each validation, so a measurement is only good
# for the cycle that took it. Half an hour spans one validation window comfortably and
# expires long before the next milestone could re-seed differently.
_LIVE_COUNTS_TTL_1202DJ = 1800.0


def _project_root_1202dj(project_dir):
    """The canonical run root, normalised the SAME two ways `live_row_counts_1039` is.

    Both normalisations are traps this repo has already paid for, and a reader that skips
    them is blind from exactly the callers that matter:

      #1044 — every lane works in `<project>/worktrees/<lane>/`, so a worktree path must be
              hoisted; only the canonical tree ever runs a stack.
      #563  — callers hold `<project>/app` as often as the project root.

    Shared so the writer and the reader cannot drift into disagreeing about where the file
    lives — the resumed r44 captured counts and the audit still examined 0 of 12 tables,
    because this reader resolved neither case.
    """
    from pathlib import Path as _P
    proj = _P(project_dir)
    parts = proj.parts
    if "worktrees" in parts:
        return _P(*parts[:parts.index("worktrees")])
    # `<project>/app` -> `<project>`. A run root is marked by the dir the stack boots from
    # or the one this record lives in; checking both means the hoist works before either the
    # stack or the record exists, and stays put for a path that is neither (so "no record"
    # cannot become someone else's record).
    def _is_root(d):
        return (d / "docker").is_dir() or (d / "shared").is_dir()
    if not _is_root(proj) and _is_root(proj.parent):
        return proj.parent
    return proj


def record_live_counts_1202dj(project_dir: Any, counts: Dict[str, int]) -> None:
    """Store row counts taken while the database was known to be up.

    `live_row_counts_1039` works — verified against a live stack — but it is called from gate
    evaluation, and the framework cycles the stack (`down -v`, `up`) around each validation,
    so the container is usually gone by then. Every one of the 2728 seed_audit lines in the
    corpus is the failure warning. This is the other end: validation records what it saw at
    `backend_health`, the one moment the stack is provably live.

    An empty map is NOT stored — a failed read must never become "every table is zero".
    """
    if not counts:
        return
    try:
        import json
        import time
        from pathlib import Path
        p = _project_root_1202dj(project_dir) / _LIVE_COUNTS_REL_1202DJ
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": time.time(), "counts": dict(counts)}),
                     encoding="utf-8")
    except Exception:
        pass


def recent_live_counts_1202dj(project_dir: Any,
                              max_age_sec: float = _LIVE_COUNTS_TTL_1202DJ) -> Dict[str, int]:
    """Counts recorded during this validation cycle, or ``{}``.

    ``{}`` means NOT MEASURED and is returned for every failure — absent, corrupt, stale.
    The audit then behaves exactly as it does today. That is the invariant #1039's own
    docstring states ("an empty result must mean 'not measured'") and the one #1023d shows
    the cost of losing: `is_clean` cannot tell "examined nothing" from "found nothing wrong".
    """
    try:
        import json
        import time
        from pathlib import Path
        rec = json.loads(
            (_project_root_1202dj(project_dir) / _LIVE_COUNTS_REL_1202DJ).read_text(
                encoding="utf-8"))
        if not isinstance(rec, dict):
            return {}
        if (time.time() - float(rec.get("at") or 0)) > max_age_sec:
            return {}
        counts = rec.get("counts")
        return dict(counts) if isinstance(counts, dict) and counts else {}
    except Exception:
        return {}


def audit_seed_data(hub_registry, project_dir: Any = None) -> SeedReport:
    schema_hub = getattr(hub_registry, "schema_hub", None)
    if schema_hub is None or not hasattr(schema_hub, "list_tables"):
        return SeedReport()
    tables = schema_hub.list_tables() or {}
    seed_regs = schema_hub.list_seed_registrations() or {}
    try:   # #1202ow: the last capture of this run, however old — used only to refuse a flip
        _last_live_1202ow = recent_live_counts_1202dj(project_dir, max_age_sec=float("inf")) \
            if project_dir is not None else {}
    except Exception as _e1202ow:
        # Empty here is fail-CLOSED (no earlier capture -> #956's flag stands), but say so.
        from .message_format import warn_once_1201
        warn_once_1201("seed_audit.last_live_capture_1202ow",
                       "the last live seed capture, so a table counted earlier in this run may "
                       "flip back to missing_seed when its count ages", _e1202ow)
        _last_live_1202ow = {}

    # #956 repair: when the database is reachable, its exact row counts are authoritative and
    # the `status == "defined"` filter (which skips 1729 of 1745 corpus tables) is bypassed.
    # Strictly additive: `{}` — no DB, no compose, any error — leaves every branch below
    # exactly as it was.
    _live = live_row_counts_1039(project_dir) if project_dir is not None else {}
    # #1202dj: the read above is right and almost never gets to happen — the stack is cycled
    # around each validation, so the container is gone by gate time (2728 of 2728 corpus
    # attempts failed). Fall back to what validation measured at `backend_health`, when the
    # database was provably up. Still `{}` when absent/stale/corrupt, so the additive
    # contract #956 wrote down holds: no measurement leaves every branch below untouched.
    _live_src_1202dj = "live COUNT(*) at gate time (#956)"
    if not _live and project_dir is not None:
        _live = recent_live_counts_1202dj(project_dir)
        if _live:
            _live_src_1202dj = "live COUNT(*) captured at backend_health (#1202dj)"
    # #1168: density was audited, parentage never was. Same additive contract as #1039:
    # `{}` on no DB / no compose / any error, so every branch below is untouched.
    _orphans_1168 = (orphan_fk_rows_1168(project_dir)
                     if project_dir is not None else {})
    _spine = _spine_tables_1039()

    flagged: List[dict] = []
    _examined_956 = 0
    for name, table in tables.items():
        # #1202du: parked probe tables (#1202dw CORRECTION: an AGENT parks them, the
        # framework does not emit them — see validation_runner's netflix-local-r6 note) (`__noop_orchestrator_probe__`,
        # `__noop_orchestrator_state_check__`). r44's registry holds both, and the audit flagged
        # the second `missing_seed` — sending the backend lane to grep `app/backend` for
        # something the FRAMEWORK registered and nowhere in its scope. #251's rule, a third time
        # after #1202ds: the exemption cannot depend on metadata a lane must set, and `provider`
        # here reads "backend", so only our own naming convention identifies it. Ahead of BOTH
        # paths: the `_live` branch consults `_spine`, the legacy branch consults nothing.
        if str(name).startswith("__"):
            continue
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
                               "source": _live_src_1202dj}})
            elif n < min_rows:
                flagged.append({
                    "table": name, "reason": "low_row_count",
                    "detail": {"row_count": n, "min_seed_rows": min_rows,
                               "source": _live_src_1202dj}})
            continue
        if (table.get("status") or "defined") != "defined":
            continue
        _examined_956 += 1
        meta = table.get("metadata") or {}
        min_rows = meta.get("min_seed_rows", _DEFAULT_MIN_ROWS)
        if min_rows == 0:
            continue  # explicit opt-out

        reg = seed_regs.get(name)
        # #1202ow: WITHOUT a fresh live row count this branch asks the seed-REGISTRATION store,
        # which no run writes — and a fresh count has a TTL (`recent_live_counts_1202dj`). So
        # the verdict swung with nothing but time: inside the TTL a measured table read clean,
        # after it the same table read `missing_seed`. Measured: 50 flips on an unchanged table
        # count across 12 of 22 runs (fastest 3.7s, r125; r120 alternated missing:13 /
        # missing:0 about once a minute) and 15 runs dispatched a backend P0 "Seed the empty
        # business table" while live counts showed every business table non-empty.
        #
        # #956 decided — and its tests pin — that a table NEVER measured and not registered is
        # still flagged; that stands. What changes is only this: a table THIS RUN has already
        # counted at or above its minimum is not declared empty because the count went stale.
        # The last capture is real evidence; a missing registration is not new evidence.
        if reg is None:
            _n_last = _last_live_1202ow.get(name)
            if isinstance(_n_last, int) and _n_last >= int(min_rows or 0):
                continue
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
