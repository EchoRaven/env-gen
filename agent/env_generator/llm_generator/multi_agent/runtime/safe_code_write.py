"""#995: a framework repair may not leave a generated file worse than it found it.

46 functions across `runtime/` write generated CODE; six validate it before writing. #979 was
one of the other forty — the router-prologue repair spliced `router = APIRouter()` after the
last import LINE, and for the 26 corpus files whose imports end in `from models import (` that
landed inside the parentheses. A SyntaxError, and the backend does not boot.

#979 corrected that one splice. The CLASS survived it: the same accident is one edit away in
every other unguarded repair, and it fires in an already-broken state, so the fresh error
reads as the lane's own mistake and the lane is sent to fix code the framework just corrupted.

These repairs share a narrow, cheap invariant — they MODIFY an existing valid module, so **if
it parsed before it must parse after**.

This lives in its own module on purpose. The first attempt at #995 put the helper inside
`backend_scaffold.py`, which is dense with triple-quoted templates of generated code, and
string-position placement dropped it into `_AUTH_DEPENDENCY_PY` — where it would have been
written into every generated app. A module with no templates cannot be got wrong that way.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

_LOG = logging.getLogger(__name__)


def _scrubbed_1202mi(text: str, filename: str) -> str:
    """Strip this framework's ticket tags and past-run names from the comments
    and docstrings of Python it writes into the generated app. Never raises: a
    failed scrub must not stop a repair from landing."""
    try:
        from .provenance_scrub import scrub_provenance_1202mi
        return scrub_provenance_1202mi(text, filename)
    except Exception:
        return text


def write_py_if_still_parses(path: Path, new_text: str, *, what: str = "") -> bool:
    """Write ``new_text`` to ``path`` unless doing so would break a file that currently parses.

    Returns True when written. On refusal the file keeps its previous content — strictly
    better than a backend that will not start — and a warning names the repair and the syntax
    error so the next reader does not have to bisect for it.

    Deliberately permissive in two directions:

    * if the ORIGINAL does not parse, the write goes through. A repair whose whole job is
      fixing broken syntax must not be blocked by this guard.
    * anything that is not ``.py`` is written unchecked. There is no cheap parser here for
      JSX, and a guard that pretends to check is worse than one that says it does not.
    """
    if path.suffix != ".py":
        path.write_text(new_text, encoding="utf-8")
        return True

    # #1202mi: this is the THIRD way framework-authored Python reaches the
    # generated app (the others are `framework_write_1202cw` and
    # backend_skeleton's direct writes), and it serves four callers --
    # handler_fk_repair, backend_scaffold, route_projector, heal_pipeline. A
    # scrub wired to only some of the ways in is the defect `#1202mg` was about;
    # I reproduced it here by not counting the ways in before wiring.
    new_text = _scrubbed_1202mi(new_text, path.name)

    old = ""
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except Exception:
            old = ""
    if old:
        try:
            ast.parse(old)
        except SyntaxError:
            path.write_text(new_text, encoding="utf-8")
            return True

    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        _LOG.warning(
            "#995 REFUSED a repair that would not parse: %s%s — %s at line %s. "
            "The file keeps its previous content.",
            path.name, f" ({what})" if what else "", exc.msg, exc.lineno)
        return False

    path.write_text(new_text, encoding="utf-8")
    return True
