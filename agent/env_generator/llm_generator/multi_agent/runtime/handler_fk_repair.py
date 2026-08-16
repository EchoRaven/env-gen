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

# #784: tables an actor reference can point at. `profiles` is here because #777
# established the profile as a NARROWER actor than the user on this corpus, so a
# model carrying both user_id and profile_id has two candidate actors, not one.
_ACTOR_TABLES_784 = ("users", "profiles", "accounts", "members")


def repair_handler_fk_aliases(backend_dir: Any) -> Dict[str, Any]:
    """Rewrite ``<Model>.<missing_owner_alias>`` → ``<Model>.<actual_owner_fk>`` in
    main.py. Returns ``{"fixed": [...], "ambiguous": [...]}`` — ``ambiguous`` names the models
    carrying more than one owner-ish column, where the repair REFUSES to guess (#784)."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"fixed": [], "ambiguous": []}
    models = _orm_models(backend_dir)
    if not models:
        return {"fixed": [], "ambiguous": []}
    src = main_py.read_text(encoding="utf-8")
    fixed: List[str] = []
    ambiguous: List[str] = []   # #784: models the repair refuses to guess on
    for _table, meta in models.items():
        cls = meta.get("cls")
        cols = set(meta.get("cols") or [])
        if not cls:
            continue
        actual = _owner_fk(meta)  # the model's real owner FK (author_id/user_id/…)
        if not actual or actual not in cols:
            continue
        # #784: the docstring's contract is "the model has a SINGLE owner FK" — enforce it.
        # `_owner_fk` returns the FIRST match in `_OWNER_FK_NAMES` order, so on a model carrying
        # two of them it does not resolve the ambiguity, it hides it. `_OWNER_FK_NAMES` includes
        # directional halves (`sender_id`, `follower_id`, `from_user_id`), so on
        # `messages(sender_id, recipient_id)` a broken `Message.user_id` in an INBOX handler would
        # be silently rewritten to `sender_id` — the handler then returns the caller's SENT mail
        # and passes, which is a wrong-owner read that no test would notice.
        # A loud AttributeError 500 is the better failure here: owner-scoping changes are safety
        # changes (#568/#569), and this repair exists to unstick a stall, not to guess an actor.
        # Ambiguity is decided by what a column POINTS AT, not by whether its name is on a
        # curated list — the first cut of this guard counted `_OWNER_FK_NAMES` members and missed
        # the messages case entirely, because the dangerous counterpart (`recipient_id`) is
        # precisely the name NOT on the list. Generated models declare
        # `ForeignKey("users.id")` / `ForeignKey("profiles.id")`, so the actor references are
        # readable directly.
        fks = meta.get("fks") or {}
        owner_ish = sorted({c for c in cols
                            if c in _OWNER_FK_NAMES
                            or str(fks.get(c) or "") in _ACTOR_TABLES_784})
        if len(owner_ish) > 1:
            ambiguous.append(f"{cls}: {owner_ish}")
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
    return {"fixed": fixed, "ambiguous": ambiguous}
