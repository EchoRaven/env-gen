"""Framework-owned handler↔model FK-alias repair.

Root cause (instagram MM run #9, 2026-06-09): the backend lane authored a handler that
queries ``Post.user_id`` while the Post model's owner FK is ``author_id`` — an internal
handler↔model inconsistency that raises ``AttributeError: type object 'Post' has no
attribute 'user_id'`` → 500 → api_smoke ``business_endpoints_reachable`` fails and the
milestone stalls (run #9 burned its retry budget on ``GET /api/users/me → 500``).

Mirrors ``route_projector`` / ``database_scaffold``: rather than trust the lane to keep
its own handlers consistent with its own models, repair the contract surface
deterministically. For any ``<Model>.<owner_alias>`` reference where the alias is NOT a
real column on that model but the model has a single owner FK, rewrite it to that FK.
Only GUARANTEED-broken references are touched (the named attribute does not exist on the
class, so the code can only ever ``AttributeError``), so a valid query is never altered.
Idempotent, AST-introspected models, best-effort.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .route_projector import _OWNER_FK_NAMES, _orm_models, _owner_fk


def repair_handler_fk_aliases(backend_dir: Any) -> Dict[str, Any]:
    """Rewrite ``<Model>.<missing_owner_alias>`` → ``<Model>.<actual_owner_fk>`` in
    main.py. Returns ``{"fixed": [...]}`` (empty when nothing was broken)."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"fixed": []}
    models = _orm_models(backend_dir)
    if not models:
        return {"fixed": []}
    src = main_py.read_text(encoding="utf-8")
    fixed: List[str] = []
    for _table, meta in models.items():
        cls = meta.get("cls")
        cols = set(meta.get("cols") or [])
        if not cls:
            continue
        actual = _owner_fk(meta)  # the model's real owner FK (author_id/user_id/…)
        if not actual or actual not in cols:
            continue
        for alias in _OWNER_FK_NAMES:
            if alias == actual or alias in cols:
                continue  # only rewrite an alias the model genuinely LACKS
            pattern = re.compile(rf"\b{re.escape(cls)}\.{re.escape(alias)}\b")
            new_src, n = pattern.subn(f"{cls}.{actual}", src)
            if n:
                src = new_src
                fixed.append(f"{cls}.{alias} -> {cls}.{actual} (x{n})")
    if fixed:
        main_py.write_text(src, encoding="utf-8")
    return {"fixed": fixed}
