"""FIX #72 — canonical per-user named-row consistency (outlook run-61, live 2026-07-03).

A lane handler routinely looks up a REQUIRED per-user singleton by a literal label and
500/404s when it is absent:

    sent_folder = db.query(Folder).filter(
        Folder.user_id == user_id, Folder.name == "Sent").first()
    if not sent_folder:
        raise HTTPException(status_code=500, detail="... Sent folder not found")

The framework's seed invents GENERIC names ("Getting Started", "Project Overview"),
so NO user — seeded or freshly-registered — has a folder named "Sent" (or ``kind ==
"trash"``). Every reply/forward/delete then 500s, and the business_chain gate wedges
forever on a handler that is actually CORRECT for a properly-provisioned user. This is
a lane↔framework CONSISTENCY defect: the lane names a canonical row the framework never
creates. By construction, the FRAMEWORK owns the seed and the register path, so it must
satisfy the canonical names the handlers reference.

This module detects those canonical rows from the lane's route source via two safe,
privilege-excluding signals (see ``detect_canonical_rows``): a 5xx-guarded lookup ("this
named row MUST exist") OR a lookup whose ``.id`` is filed as a foreign key ("this row is
a structural container the handler writes into" — run-62's graceful reply variant, where
a missing Sent folder silently orphans every reply to ``folder_id = NULL``). It then
projects a ``user_bootstrap.json`` spec that two runtime consumers enforce idempotently:
the seed LOADER (seeded users) and ``create_user`` (freshly-registered users, i.e. the
verification chain's user). Env-agnostic: driven entirely by the literals the handlers
reference — a music app's ``Playlist.name == "Liked Songs"`` gets the same treatment.

LOCAL-ONLY test companion: agent/tests/test_canonical_rows.py.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

# LABEL columns only — a literal filter on one of these in a required-singleton lookup
# names a canonical row to CREATE. status/state/role/is_* are deliberately EXCLUDED:
# ``.status == "pending"`` filters EXISTING content, and materialising a per-user row
# with status="pending" would fabricate spurious business objects (a phantom order).
_LABEL_COLS = ("name", "title", "label", "slug", "kind", "type", "category", "key",
               "code", "handle")

# The required-singleton idiom, captured in one shot so a literal only qualifies when the
# lookup RAISES on absence (the "must exist" signal). Tolerant of intervening filter args,
# whitespace and newlines, and ``not user or not sent_folder`` compound guards.
#   group 1 = assignment var   group 2 = Model (last dotted segment)   group 3 = filter args
_LOOKUP_RE = re.compile(
    r"(\w+)\s*=\s*[\w.]*?\bquery\(\s*[\w.]*?\.?(\w+)\s*\)\s*"
    r"((?:\.\s*(?:filter|filter_by)\([^;]*?\))+?)"
    r"\s*\.\s*(?:first|one_or_none|scalar)\s*\(\s*\)",
    re.DOTALL,
)
# a `<Model>.<label> == "literal"` OR `filter_by(<label>="literal")` inside the args
_FILTER_EQ_RE = re.compile(
    r"\.\s*(" + "|".join(_LABEL_COLS) + r")\s*==\s*[\"']([^\"']+)[\"']")
_FILTER_KW_RE = re.compile(
    r"\b(" + "|".join(_LABEL_COLS) + r")\s*=\s*[\"']([^\"']+)[\"']")
# The guard must raise a 5xx — "this named row MUST exist (broken server invariant)". A
# 4xx guard is DELIBERATELY excluded: ``if not admin_role: raise HTTPException(403, ...)``
# is an AUTHORIZATION gate whose absence is INTENTIONAL for unprivileged users, and
# materialising an "admin" row per user would be privilege escalation. 404 is likewise
# excluded as ambiguous (a legitimately-absent resource). Only a 5xx means "should never
# be missing" → safe to create.
_RAISE_5XX_RE = re.compile(
    r"raise\s+HTTPException\s*\((?:[^)]*?)"
    r"(?:status_code|status)\s*=\s*(?:5\d\d|status\.HTTP_5\d\d|[\w.]*HTTP_5\d\d)",
    re.DOTALL)


def _tablename_map(models_src: str) -> Dict[str, str]:
    """{ORMClassName: tablename} from ``class X(Base): __tablename__ = "t"``."""
    out: Dict[str, str] = {}
    cur: Optional[str] = None
    for line in (models_src or "").splitlines():
        m = re.match(r"\s*class\s+(\w+)\s*\(", line)
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"__tablename__\s*=\s*[\"'](\w+)[\"']", line)
        if m and cur:
            out[cur] = m.group(1)
            cur = None
    return out


def detect_canonical_rows(route_src: str, models_src: str) -> List[Dict[str, str]]:
    """Scan lane route source for required per-user canonical named rows.

    Returns a de-duplicated list of ``{"model", "table", "match_col", "literal"}`` — one
    per distinct (table, col, literal) whose singleton lookup RAISES on absence. Best-
    effort and never raises: a parse miss yields fewer entries, never a crash."""
    out: List[Dict[str, str]] = []
    try:
        tmap = _tablename_map(models_src)
        seen = set()
        src = route_src or ""
        for m in _LOOKUP_RE.finditer(src):
            var, model, args = m.group(1), m.group(2), m.group(3)
            # Accept the looked-up labeled singleton as a canonical row to bootstrap when
            # EITHER signal holds (both mean "this row should exist for the user", and
            # BOTH exclude an authorization gate):
            #   (A) MUST-EXIST — a 5xx guards ``not <var>`` ("broken invariant if absent",
            #       e.g. run-61 reply: ``if not sent_folder: raise HTTPException(500,...)``).
            #       A 4xx/403 authz gate is excluded → never fabricate a privilege row.
            #   (B) STRUCTURAL CONTAINER — ``<var>.id`` is assigned as a foreign-key value
            #       (``folder_id=sent_folder.id``), i.e. the row is the PARENT the handler
            #       files new child rows into (run-62 reply: graceful ``folder_id=
            #       sent_folder.id if sent_folder else None``). Without the container the
            #       write orphans the child (FK null) — the delivered Sent folder is forever
            #       empty. An authz check never assigns ``<var>.id`` as an FK, so this is
            #       still privilege-safe.
            tail = src[m.end():m.end() + 400]
            m5 = _RAISE_5XX_RE.search(tail)
            must_exist = bool(m5 and re.search(r"\bnot\s+" + re.escape(var) + r"\b", tail[:m5.end()]))
            fk_target = bool(re.search(r"\b\w+_id\s*=\s*" + re.escape(var) + r"\.id\b", tail))
            if not (must_exist or fk_target):
                continue
            table = tmap.get(model) or (model.lower() + "s" if not model.lower().endswith("s") else model.lower())
            for col, lit in _FILTER_EQ_RE.findall(args) + _FILTER_KW_RE.findall(args):
                key = (table, col, lit)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"model": model, "table": table, "match_col": col, "literal": lit})
    except Exception:
        return out
    return out


def build_bootstrap_spec(
    canonical: List[Dict[str, str]],
    tables: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Project the runtime spec both consumers enforce.

    Each entry: ``{table, owner_col, match_col, literal, row}`` where ``row`` is a
    complete, valid non-owner column set (built with the SAME deterministic value logic
    the seed uses, so NOT NULL columns are satisfied for ANY schema) with ``match_col``
    overridden to the canonical literal. Only per-user tables (a resolvable owner FK) are
    bootstrapped; a table with no owner column is not per-user, so a per-user default is
    meaningless and skipped."""
    if not canonical:
        return []
    specs: List[Dict[str, Any]] = []
    try:
        from .backend_skeleton import (_models_meta, _seed_cell, _seed_infer_fk,
                                        _SEED_OMIT)
        try:
            from .route_projector import _owner_fk
        except Exception:
            _owner_fk = lambda _m: None  # noqa: E731
        meta = _models_meta(tables)
        known = set(meta.keys()) | {"tenants"}
        counts = {t: 6 for t in meta}
        counts["users"] = 5
        pk_types = {t: meta[t].get("pk_type") for t in meta}
        seen = set()
        for c in canonical:
            table, mcol, lit = c["table"], c["match_col"], c["literal"]
            if table not in meta:
                continue
            owner = _owner_fk(meta.get(table, {}))
            if not owner:  # not per-user → a per-user default is meaningless
                continue
            key = (table, mcol, lit)
            if key in seen:
                continue
            seen.add(key)
            cols = [col for col in (meta[table].get("cols") or []) if col]
            fks = meta[table].get("fks") or {}
            _pk_name, _pk_type = meta[table].get("pk"), meta[table].get("pk_type")
            row: Dict[str, Any] = {}
            for col in cols:
                if col == owner or col == _pk_name or col.lower() in ("id",):
                    continue  # owner filled at insert; PK auto
                _fk = fks.get(col) or _seed_infer_fk(col, known)
                if _fk in (owner and "users", None) and col == owner:
                    continue
                v = _seed_cell(col, table, 0, _fk, counts,
                               pk_name=_pk_name, pk_type=_pk_type, pk_types=pk_types)
                if v is not _SEED_OMIT:
                    row[col] = v
            row[mcol] = lit
            # cosmetic: if the row also carries a ``name`` and the canonical col ISN'T
            # name, give it a readable label instead of a generic seed title.
            if mcol != "name" and "name" in cols:
                row["name"] = str(lit).replace("_", " ").title()
            specs.append({"table": table, "owner_col": owner,
                          "match_col": mcol, "literal": lit, "row": row})
    except Exception:
        return specs
    return specs


def bootstrap_spec_for_backend(output_dir: Any, tables: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convenience: read the lane's ``custom_routes.py`` + ``models.py`` under
    ``<output_dir>/app/backend`` and return the bootstrap spec. Empty on any miss."""
    try:
        from pathlib import Path
        be = Path(output_dir) / "app" / "backend"
        routes = ""
        cr = be / "custom_routes.py"
        if cr.exists():
            routes = cr.read_text(encoding="utf-8")
        models_src = ""
        mp = be / "models.py"
        if mp.exists():
            models_src = mp.read_text(encoding="utf-8")
        if not routes:
            return []
        canonical = detect_canonical_rows(routes, models_src)
        return build_bootstrap_spec(canonical, tables)
    except Exception:
        return []


# ── Runtime enforcement routine (emitted verbatim into seed_data.py AND oauth_store.py) ──
# psycopg3-style ``conn.execute`` with %s params. Idempotent: inserts a canonical row for a
# user only when absent. Never raises into the caller (a bootstrap failure must not break
# seeding or registration). Kept as SOURCE TEXT so both generated consumers embed one copy.
ENFORCE_ROUTINE_SRC = '''
def _enforce_user_bootstrap_rows(conn, user_id, specs):
    """Ensure a user has every canonical per-user named row a handler requires. Idempotent
    and best-effort: a per-row failure is swallowed so seeding/registration never breaks."""
    for _s in (specs or []):
        try:
            _t = _s.get("table"); _owner = _s.get("owner_col")
            _mcol = _s.get("match_col"); _lit = _s.get("literal")
            _row = dict(_s.get("row") or {})
            if not (_t and _owner and _mcol):
                continue
            _hit = conn.execute(
                'SELECT 1 FROM "{}" WHERE "{}" = %s AND "{}" = %s LIMIT 1'.format(_t, _owner, _mcol),
                (user_id, _lit)).fetchone()
            if _hit:
                continue
            _cols = {_owner: user_id}
            _cols.update(_row)
            _cols[_mcol] = _lit
            _cl = ", ".join('"{}"'.format(_c) for _c in _cols)
            _ph = ", ".join(["%s"] * len(_cols))
            conn.execute(
                'INSERT INTO "{}" ({}) VALUES ({})'.format(_t, _cl, _ph),
                tuple(_cols.values()))
        except Exception:
            continue


def _load_user_bootstrap_specs():
    """Read the framework-projected user_bootstrap.json sitting beside this module."""
    import json as _json, os as _os
    try:
        _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "user_bootstrap.json")
        if not _os.path.exists(_p):
            return []
        with open(_p, "r", encoding="utf-8") as _f:
            _d = _json.load(_f)
        return _d if isinstance(_d, list) else []
    except Exception:
        return []
'''
