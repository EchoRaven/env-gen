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
from typing import Any, Dict, List, Optional

from .route_projector import _OWNER_FK_NAMES, _orm_models, _owner_fk
def _write_py_995(path, text, *, what: str = ""):
    """#995 guard, imported defensively.

    Some modules here are imported STANDALONE by tests (no package context), where a relative
    import raises. The guard degrades to a plain write in that case rather than breaking the
    import — and says so in this docstring rather than pretending it is still checking.
    """
    try:
        from .safe_code_write import write_py_if_still_parses as _w
    except Exception:
        path.write_text(text, encoding="utf-8")
        return True
    return _w(path, text, what=what)


# #784: tables an actor reference can point at. `profiles` is here because #777
# established the profile as a NARROWER actor than the user on this corpus, so a
# model carrying both user_id and profile_id has two candidate actors, not one.
_ACTOR_TABLES_784 = ("users", "profiles", "accounts", "members")


def _table_of(ref: Any) -> str:
    """``users`` / ``users.id`` / ``ForeignKey('users.id')`` -> ``users``."""
    return str(ref or "").strip().strip("'\"").split("(")[-1].strip("'\")").split(".")[0]


def _reachable_tables_974(table: str, models: Dict[str, Any], _seen=None) -> set:
    """Every table reachable from *table* by following its FKs, transitively."""
    _seen = _seen or set()
    out: set = set()
    for _col, tgt in ((models.get(table) or {}).get("fks") or {}).items():
        t = _table_of(tgt)
        if t and t not in _seen:
            out.add(t)
            out |= _reachable_tables_974(t, models, _seen | {t})
    return out


def _narrowest_actor_974(owner_ish, fks, models) -> Optional[str]:
    """#974: resolve an ambiguous owner WITHOUT guessing, or return None.

    Two owner-ish FKs are only ambiguous if neither is a REFINEMENT of the other. When one
    actor table transitively references the other — ``profiles.user_id -> users.id`` — the
    descendant is the narrower scope, and a row owned by that profile is owned by exactly
    one user. Picking it is a deduction from the declared FK graph, not a guess.

    ★ The safety asymmetry is what makes this admissible where #784 refused. Scoping to the
    NARROWER actor can only ever return too little; scoping to the wider one can return
    another user's rows. So a wrong answer here is a visible over-restriction, never a
    silent cross-user leak — the exact failure #784 was protecting against.

    Returns None (still ambiguous) when the actors are SIBLINGS. ``messages(sender_id,
    recipient_id)`` points both at ``users``: no refinement exists, guessing would hand an
    inbox handler the caller's sent mail, and that case must keep failing loudly.
    """
    targets = {c: _table_of(fks.get(c)) for c in owner_ish}
    if any(not t for t in targets.values()):
        return None                                   # an unresolvable reference
    if len(set(targets.values())) < len(targets):
        return None                                   # siblings on one actor table
    for col, tbl in targets.items():
        others = {t for c, t in targets.items() if c != col}
        if others and others <= _reachable_tables_974(tbl, models):
            return col
    return None


def repair_handler_fk_aliases(backend_dir: Any) -> Dict[str, Any]:
    """Rewrite ``<Model>.<missing_owner_alias>`` → ``<Model>.<actual_owner_fk>`` in
    main.py. Returns ``{"fixed": [...], "ambiguous": [...]}`` — ``ambiguous`` names the models
    carrying more than one owner-ish column, where the repair REFUSES to guess (#784)."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"fixed": [], "ambiguous": [], "narrowed": []}
    models = _orm_models(backend_dir)
    if not models:
        return {"fixed": [], "ambiguous": [], "narrowed": []}
    src = main_py.read_text(encoding="utf-8")
    fixed: List[str] = []
    ambiguous: List[str] = []   # #784: models the repair refuses to guess on
    narrowed: List[str] = []    # #974: models where an actor REFINEMENT resolved it
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
            # #974: ambiguous only if neither actor REFINES the other (see
            # _narrowest_actor_974). netflix r158 died here: my_list / ratings /
            # continue_watching each carry user_id AND profile_id, the repair refused 90
            # times, business_chain wedged for 7 cycles and the run aborted without
            # delivering. `profiles` references `users`, so profile_id is the narrower
            # scope and the deduction is free.
            _narrowed = _narrowest_actor_974(owner_ish, fks, models)
            if _narrowed is None:
                ambiguous.append(f"{cls}: {owner_ish}")
                continue
            narrowed.append(f"{cls}: {owner_ish} -> {_narrowed}")
            actual = _narrowed
        for alias in _OWNER_FK_NAMES:
            if alias == actual or alias in cols:
                continue  # only rewrite an alias the model genuinely LACKS
            pattern = re.compile(rf"\b{re.escape(cls)}\.{re.escape(alias)}\b")
            new_src, n = pattern.subn(f"{cls}.{actual}", src)
            if n:
                src = new_src
                fixed.append(f"{cls}.{alias} -> {cls}.{actual} (x{n})")
    if fixed:
        _write_py_995(main_py, src, what="repair_handler_fk_aliases")
    return {"fixed": fixed, "ambiguous": ambiguous, "narrowed": narrowed}
