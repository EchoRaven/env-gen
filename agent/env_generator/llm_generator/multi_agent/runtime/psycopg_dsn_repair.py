"""Framework-owned raw-psycopg DSN repair.

Root cause (instagram MM run #10, 2026-06-09): the backend lane wrote handlers that open
RAW psycopg connections via ``psycopg.connect(_database_url())`` where ``_database_url()``
returns the env ``DATABASE_URL`` verbatim — but that env is the SQLAlchemy URL
``postgresql+psycopg://sandbox:sandbox@database:5432/app``. ``psycopg.connect`` rejects the
``+psycopg`` dialect suffix (``ProgrammingError: missing "=" after
"postgresql+psycopg://..." in connection info string``) → every such endpoint 500s
(/api/users/suggested, /api/feed, /api/explore, get_public_user_profile … 14 sites in one
run) → api_smoke stalls the milestone.

The SQLAlchemy engine genuinely needs ``postgresql+psycopg://`` (psycopg3 driver), so the
env can't change; only the RAW-psycopg call sites need a clean DSN. Mirrors the other
by-construction repairs: wrap every ``psycopg.connect(<first-arg>)`` with a
``_psycopg_dsn(...)`` helper that strips a ``+<driver>`` dialect from the scheme.
Deterministic, idempotent, best-effort; touches nothing when the app never uses raw
psycopg.

#62 (outlook run-47, live): the original repair only touched ``main.py`` and only
matched a connect whose DSN was the SOLE argument. The custom-routes era moved the
lane's raw psycopg into ``custom_routes.py``, and the lane authored
``psycopg.connect(conninfo, row_factory=dict_row)`` — neither matched, so every
auth/me + folders read 500'd for 5+ validation cycles on a correct app. The repair
now covers every lane-owned backend module and any trailing-argument shape.
"""

from __future__ import annotations

import re
from pathlib import Path

# #1202td: `_TARGET_FILES` includes `custom_routes.py`, which `path_is_lane_owned_1202cw`
# reports LANE-OWNED — so this module rewrites lane work and belongs at the choke point.
try:
    from .path_routed_workspace import framework_write_1202cw as _fw_write_1202cw
except Exception:   # pragma: no cover - standalone import without package context
    def _fw_write_1202cw(_p, _text, **_kw):
        Path(str(_p)).write_text(_text, encoding=_kw.get("encoding", "utf-8"))  # raw: shim
        return True
from typing import Any, Dict

# The FIRST psycopg.connect argument — an os.getenv/environ lookup, a call like
# ``_database_url()``, or a bare name/attr — regardless of trailing kwargs (#62:
# ``psycopg.connect(conninfo, row_factory=dict_row)`` matched NOTHING under the
# old only-argument regex). A string LITERAL first arg is left alone (it is not
# the env URL; rewriting hand-written conninfo strings risks breaking them).
_CONNECT_RE = re.compile(
    r"psycopg\.connect\(\s*"
    r"((?:os\.(?:getenv|environ\.get)\(\s*[^()]*\)|[\w.]+\(\)|[\w.]+))"
    r"\s*(?=[,)])")

# Lane-owned backend modules that open raw connections. main.py is framework-
# projected but historically carried lane handlers too; custom_routes.py is the
# custom-routes-era home of lane SQL.
_TARGET_FILES = ("main.py", "custom_routes.py")

_HELPER = (
    "\n\ndef _psycopg_dsn(url):\n"
    '    """Strip a SQLAlchemy dialect (e.g. postgresql+psycopg://) so raw psycopg\n'
    '    accepts the DSN. The SQLAlchemy engine keeps the +driver form; only raw\n'
    '    psycopg.connect() call sites are normalised."""\n'
    "    import re as _re\n"
    '    return _re.sub(r"^([a-z][a-z0-9]*)\\+[a-z0-9_]+://", r"\\1://", url or "")\n'
)


def _repair_one(py_file: Path) -> int:
    src = py_file.read_text(encoding="utf-8")
    if "psycopg.connect(" not in src or "_psycopg_dsn(" in src:
        return 0  # nothing to do / already repaired (idempotent)

    # the trailing ``,``/``)`` delimiter is NOT consumed (lookahead), so the
    # replacement adds exactly one paren to close the _psycopg_dsn(...) wrapper.
    new_src, n = _CONNECT_RE.subn(r"psycopg.connect(_psycopg_dsn(\1)", src)
    if n == 0:
        return 0

    # Inject the helper after the module's import block (before first def/class/@).
    lines = new_src.splitlines(keepends=True)
    insert_at = 0
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith(("def ", "class ", "@", "app =")):
            insert_at = i
            break
        if s.startswith(("import ", "from ")) or s.strip() == "" or s.startswith("#"):
            insert_at = i + 1
    new_src = "".join(lines[:insert_at]) + _HELPER + "".join(lines[insert_at:])

    _fw_write_1202cw(py_file, new_src,
                     clobber_ok="#1202td: this repair EXISTS to rewrite the lane's backend "
                                "modules — its own docstring says lane-owned")
    return n


def repair_psycopg_dsn(backend_dir: Any) -> Dict[str, Any]:
    """Wrap every ``psycopg.connect(<first-arg>)`` in the lane-owned backend modules
    with ``_psycopg_dsn(<first-arg>)`` and inject the helper per file. Returns
    ``{"wrapped": n}`` (0 when there is no raw psycopg to fix)."""
    backend_dir = Path(backend_dir)
    wrapped = 0
    for name in _TARGET_FILES:
        py_file = backend_dir / name
        if not py_file.exists():
            continue
        try:
            wrapped += _repair_one(py_file)
        except Exception:
            continue
    return {"wrapped": wrapped}
