"""#1202gr — three more readers of `auth_required` take the copy #1202ga proved loses.

`#1202ga` established the precedence: an endpoint record carries `auth_required` in up to
three places, and `schema` is what the lane writes, so `schema` wins over the `metadata`
mirror. `resolve_endpoint_auth` implements it and the projector obeys it. Three other readers
never got the message, each wrong in a different way:

  * `heal_pipeline` re-registers an endpoint with `bool(metadata OR schema)` — an OR, not a
    precedence, so a STALE True beats the lane's fresh False and gets WRITTEN BACK as current.
    It fired 3x in r98, 4x in r97, 4x in r96, on exactly `/api/videos/{id}/comments`,
    `/api/videos/{id}/like`, `/api/videos/{id}/save`, `/api/users/{id}/follow` — the same
    endpoints those runs' chains failed on.
  * `remediation_dispatcher` reads top-level then `metadata`, never `schema`.
  * `registryhub.detect_breaking_change`'s caller builds both sides from `metadata` alone, so
    a stale True reads as `auth_added` — "auth was added to POST /auth/register", i.e. you
    must be logged in to log in. 147 `/auth/*` breaking P0s across 29 runs on this machine,
    34 of them with `auth_added` as the ONLY signal, filed at a lane that does not own
    `/auth/*` (the framework's own OAuth2 AS serves it) and duly cancelled.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402
from multi_agent.runtime.route_projector import resolve_endpoint_auth  # noqa: E402

# The r98 shape, verbatim from generated/.../registryhub_endpoints.json: the lane corrected
# `schema`, the `metadata` mirror still says the opposite.
_R98_RECORD = {
    "method": "GET", "path": "/api/videos",
    "schema": {"auth_required": False, "response": {"id": "int"}},
    "metadata": {"auth_required": True, "response_key": "items"},
}


def test_the_resolver_is_the_one_the_breaking_detector_asks():
    """Both sides of the comparison must come through the resolver, not the raw mirror."""
    src = (LLM / "multi_agent" / "runtime" / "registryhub.py").read_text(encoding="utf-8")
    at = src.index("breaking = self.detect_breaking_change(")
    block = src[src.rindex("old_full = {", 0, at):at]
    assert "_resolved_auth_1202gr" in block, (
        "the breaking-change comparison still reads the metadata mirror directly:\n%s" % block)


def test_a_stale_mirror_no_longer_reads_as_auth_added():
    from multi_agent.runtime.registryhub import _resolved_auth_1202gr
    assert _resolved_auth_1202gr(_R98_RECORD) is False, (
        "the lane's schema correction lost to the stale metadata mirror")


def test_requiring_auth_to_authenticate_is_never_breaking():
    """You cannot be logged in in order to log in — the framework's own AS serves these."""
    hub = RegistryHub.__new__(RegistryHub)
    old = {"path": "/auth/register", "method": "POST", "auth_required": False,
           "response": {"token": "str"}}
    new = {**old, "auth_required": True}
    out = RegistryHub.detect_breaking_change(hub, old, new)
    assert out["auth_added"] is False, "still reports auth added to the register endpoint"
    assert out["is_breaking"] is False, (
        "still files a P0 for a contradiction the framework itself serves around")


def test_a_real_business_endpoint_still_reports_auth_added():
    """The guard must be the auth surface only — #647: never widen a rule past its evidence."""
    hub = RegistryHub.__new__(RegistryHub)
    old = {"path": "/api/videos", "method": "GET", "auth_required": False,
           "response": {"id": "int"}}
    new = {**old, "auth_required": True}
    out = RegistryHub.detect_breaking_change(hub, old, new)
    assert out["auth_added"] is True and out["is_breaking"] is True, (
        "a real auth change on a business endpoint stopped being reported")


def test_the_healer_no_longer_writes_the_stale_copy_back():
    """`bool(metadata or schema)` is an OR; the precedence has to win instead."""
    src = (LLM / "multi_agent" / "runtime" / "heal_pipeline.py").read_text(encoding="utf-8")
    at = src.index("#566f/#566i/#566n completed request schema")
    call = src[src.rindex("registryhub.register_endpoint(", 0, at):at]
    assert "auth_required" in call
    assert "or schema.get(\"auth_required\")" not in call, (
        "the healer still ORs the stale mirror over the lane's correction:\n%s" % call)
    assert "resolve_endpoint_auth" in call or "_resolved_auth_1202gr" in call, (
        "the healer does not go through the precedence:\n%s" % call)


def test_the_remediation_dispatcher_consults_the_schema_copy():
    src = (LLM / "multi_agent" / "runtime" / "remediation_dispatcher.py").read_text(
        encoding="utf-8")
    at = src.index('authed[(str(rec.get("method", "")).upper()')
    block = src[src.rindex("for rec in _walk_records_1176", 0, at):at]
    assert '"schema"' in block or "_resolved_auth_1202gr" in block, (
        "the dispatcher still decides auth without ever reading `schema`:\n%s" % block)


def test_the_precedence_helper_agrees_with_the_projector():
    """One datum, one precedence — the whole point of #1202ga."""
    from multi_agent.runtime.registryhub import _resolved_auth_1202gr
    for rec in (_R98_RECORD,
                {"method": "GET", "path": "/api/x", "metadata": {"auth_required": True}},
                {"method": "GET", "path": "/api/y", "auth_required": True, "metadata": {}},
                {"method": "GET", "path": "/api/z"}):
        expected = resolve_endpoint_auth(rec.get("method"), rec.get("path"), rec,
                                        rec.get("metadata"))
        assert _resolved_auth_1202gr(rec) == expected, (
            "the helper and the projector disagree about %r" % (rec,))
