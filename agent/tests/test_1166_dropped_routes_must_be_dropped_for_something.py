"""#1166: a dropped lane route must be dropped IN FAVOUR OF something.

`_custom_route_overrides_projected` decides on SHAPE alone -- bare collection,
item-by-{param}, nested child CRUD keep the projected handler -- and never asks
whether a projected handler for that method+path actually exists.

Measured on BOTH delivered artifacts: within the same platform resource, POST
and GET /api/v1/tenants are kept while DELETE /api/v1/tenants/{tenant_id} is
dropped as "standard CRUD" -- and the projector never touches the spine
(users/tenants), so nothing serves it. r14 live: DELETE
/api/v1/tenants/default answered 404, on an endpoint the contract DECLARES and
the lane IMPLEMENTED. Both artifacts also fail the declared-vs-served sweep on
exactly that path.

The check cannot run at include time: the projected handlers are appended to
main.py BELOW `include_router`, so they are not registered yet. It runs at
startup, when the route table is complete, and restores only what nothing else
serves. Verified live on r14 after the fix: DELETE -> 200, and the log says
"restored 1 lane route(s)" -- one of fourteen, so "projected wins" is intact.
"""
import ast
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _CUSTOM_ROUTES_INCLUDE as TPL)


def test_the_template_is_valid_python():
    ast.parse(TPL)


def test_dropped_routes_are_remembered():
    assert "_FW_DROPPED_1166" in TPL
    assert "_FW_DROPPED_1166.append(" in TPL


def test_the_repair_runs_at_startup_not_at_include_time():
    """At include time the projected handlers are not registered yet, so a check
    there would restore everything and undo `projected wins`."""
    assert '@app.on_event("startup")' in TPL
    i = TPL.index("_fw_restore_unserved_dropped_1166")
    j = TPL.index("app.include_router(_custom_router)")
    assert j < i, "the hook must be declared after the include, and RUN later"


def _hook():
    i = TPL.index("async def _fw_restore_unserved_dropped_1166")
    return TPL[i:TPL.index("except Exception as _e1166", i)]


def test_it_only_restores_what_nothing_else_serves():
    h = _hook()
    assert "continue" in h and "_served" in h
    assert "getattr(_rt, \"methods\"" in h and "app.router.routes.append" in h


def test_the_repair_can_never_break_startup():
    i = TPL.index("async def _fw_restore_unserved_dropped_1166")
    body = TPL[i:TPL.index("\n\n", TPL.index("_e1166", i))]
    assert "except Exception as _e1166" in body


def test_it_says_what_it_restored():
    """Silently re-adding a route is the #691 mistake: a correct action nobody can
    audit."""
    h = TPL[TPL.index("async def _fw_restore_unserved_dropped_1166"):]
    # #1202tf: the property is that the restore ANNOUNCES itself, not that the announcement
    # carries our ticket number. The message ships in the delivered app's logs, where a
    # framework ticket means nothing to the reader and leaks our internals -- the standing
    # rule against internal tags in generated output. The ticket stays in the surrounding
    # framework comment, which is where the next reader of THIS file needs it.
    assert "restored %d lane route(s)" in h and "warning(" in h
    assert "#1166" not in h.split("warning(")[1][:400], (
        "a framework ticket must not ship inside a served log message")


def _predicate():
    """Exec the shape predicate standalone, the way #528's harness does."""
    g = {"_DEGENERATE_RESOURCES": set(), "_NESTED_CHILD_RESOURCES": set(),
         "_OWNER_SCOPED_RESOURCES": set(), "_REGISTERED_RESOURCES": set()}
    i = TPL.index("def _custom_route_overrides_projected(")
    exec(compile(ast.parse(TPL[i:TPL.index("\ntry:", i)]), "<t>", "exec"), g)
    return g["_custom_route_overrides_projected"]


def test_the_shape_predicate_still_drops_the_tenant_delete():
    """The predicate is UNCHANGED -- #1166 does not loosen it, it repairs the
    consequence. If this ever flips, the fix has become a behaviour change."""
    f = _predicate()
    assert f("DELETE", "/api/v1/tenants/{tenant_id}") is False
    assert f("POST", "/api/v1/tenants") is True
    assert f("GET", "/api/titles/trending") is True
