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
by-construction repairs: wrap every ``psycopg.connect(<arg>)`` with a ``_psycopg_dsn(...)``
helper that strips a ``+<driver>`` dialect from the scheme. Deterministic, idempotent,
best-effort; touches nothing when the app never uses raw psycopg.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

# A psycopg.connect argument: a call like ``_database_url()`` or a bare name/attr.
_CONNECT_RE = re.compile(r"psycopg\.connect\(\s*([\w.]+\(\)|[\w.]+)\s*\)")

_HELPER = (
    "\n\ndef _psycopg_dsn(url):\n"
    '    """Strip a SQLAlchemy dialect (e.g. postgresql+psycopg://) so raw psycopg\n'
    '    accepts the DSN. The SQLAlchemy engine keeps the +driver form; only raw\n'
    '    psycopg.connect() call sites are normalised."""\n'
    "    import re as _re\n"
    '    return _re.sub(r"^([a-z][a-z0-9]*)\\+[a-z0-9_]+://", r"\\1://", url or "")\n'
)


def repair_psycopg_dsn(backend_dir: Any) -> Dict[str, Any]:
    """Wrap every ``psycopg.connect(<arg>)`` with ``_psycopg_dsn(<arg>)`` and inject the
    helper. Returns ``{"wrapped": n}`` (0 when there is no raw psycopg to fix)."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"wrapped": 0}
    src = main_py.read_text(encoding="utf-8")
    if "psycopg.connect(" not in src or "_psycopg_dsn(" in src:
        return {"wrapped": 0}  # nothing to do / already repaired (idempotent)

    new_src, n = _CONNECT_RE.subn(r"psycopg.connect(_psycopg_dsn(\1))", src)
    if n == 0:
        return {"wrapped": 0}

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

    main_py.write_text(new_src, encoding="utf-8")
    return {"wrapped": n}
