"""RunHub probe planner — pure functions, no IO.

`plan_probe(endpoint_dict, base_url, example_body=None)` returns either:
  - `ProbePlan(method, url, headers, body)` — ready to execute
  - `ProbeSkip(reason)` — endpoint should not be probed (auth, destructive, deprecated)

`classify_probe_result(status_code, body_excerpt, auth_required, transport_error)`
returns a `ProbeOutcome(verdict, severity, note)`.

Verdict matrix:
  2xx, 3xx                            -> pass
  401, 403 when auth_required=True    -> pass
  401, 403 when auth_required=False   -> fail (P2)
  404                                 -> fail (P1)  (route not wired)
  4xx (other)                         -> fail (P2)
  5xx                                 -> fail (P1)
  transport_error="timeout"           -> fail (P1)
  transport_error="connection_refused"-> fail (P0)
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union


@dataclass
class ProbePlan:
    method: str
    url: str
    body: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=lambda: {"accept": "application/json"})
    # #1203e0: did this plan supply everything the contract says the endpoint REQUIRES?
    # `plan_probe` sends `example_body or {}` and the one caller never passes an
    # `example_body`, so for any endpoint with a required request field the answer is no --
    # and the app's 400/422 is then the CORRECT answer to a malformed question, which
    # `classify_probe_result` must not score against the handler. Default True so every
    # pre-#1203e0 construction keeps its meaning.
    request_complete: bool = True


@dataclass
class ProbeSkip:
    reason: str  # "auth_required" | "destructive" | "not_live" | "path_params"


@dataclass
class ProbeOutcome:
    verdict: str          # "pass" | "fail"
    severity: str = "P3"  # P0 | P1 | P2 | P3
    note: str = ""


_DESTRUCTIVE = {"DELETE"}


def _required_request_fields_1203e0(endpoint: Dict[str, Any]) -> set:
    """The request fields the contract says are REQUIRED, per the registry's own convention.

    `schema.request` is a dict of ``field -> type`` where a trailing ``?`` means optional --
    measured over every run directory: `request` is a dict in 4505 records and absent in 816,
    its values are `str` 6164 times, `dict` 48 and `bool` 5, and 2090 of the string types carry
    no ``?`` against 4074 that do.

    A non-string value counts as required, which is not a guess: the prober supplies NOTHING,
    so anything declared is something it did not send. The question this answers is "did we ask
    a well-formed question", and the honest answer for an unrecognised type is no.
    """
    sch = endpoint.get("schema")
    req = sch.get("request") if isinstance(sch, dict) else None
    if not isinstance(req, dict):
        return set()
    return {f for f, t in req.items()
            if not (isinstance(t, str) and t.rstrip().endswith("?"))}


# #1203d6: the statuses an endpoint can hold and still be worth asking. Corpus-wide the only
# values that exist are `implemented` (4968), `defined` (249) and `deprecated` (83).
_LIVE_STATUSES_1203D6 = {"defined", "implemented"}

# #1203d9: a path the prober cannot fill in. `plan_probe` builds `base_url + path` literally, so
# `GET /api/places/{id}` is requested as the string `/api/places/{id}`, 404s, and
# `classify_probe_result` scores it `fail` P1 -- which `deliverability` turns into the blocker
# "latest run has N failed endpoint probe(s)".
#
# This is NOT hypothetical and NOT introduced by #1203d6: of the 369 `fail` probes already on
# disk, 50 (14%) are templated paths -- `GET /api/titles/{id}`, `/api/genres/{id}/titles`. It is
# a pre-existing false-blocker on the 27 templated endpoints the old status rule happened to
# probe, and #1203d6 would have multiplied it by ~20 (526 of the 3864 endpoints it makes
# probeable, across 161 runs). Asking requires an id the prober does not have, and inventing one
# would fabricate the answer, so the honest verdict is "not asked", named as such.
#
# Measured form: `{x}` only -- 1516 of the 5300 endpoint records. Neither `/:x` (Express) nor
# `<x>` (Flask) appears anywhere in the corpus, so the predicate is not widened to guess at them.
_PATH_PARAM_1203D9 = re.compile(r"\{[^/{}]+\}")


def plan_probe(
    endpoint: Dict[str, Any],
    base_url: str,
    example_body: Optional[Dict[str, Any]] = None,
    auth_required: Optional[bool] = None,
) -> Union[ProbePlan, ProbeSkip]:
    """#1202kl: `auth_required` may be handed in, RESOLVED.

    `auth_required` lives in up to three places on an endpoint record and the framework
    settled that question long ago -- `_stated_auth_1202hi`, schema first, because that is
    what `register_endpoint(schema=...)` writes. This module is a leaf and must not import
    the projector, so the caller resolves it and passes it; `None` keeps the raw read, which
    is what every pre-#1202kl caller relies on.
    """
    # #1203d6: this used to skip every status that was not exactly "defined", reporting it as
    # `not_defined` -- and the only other live status in this system is `implemented`, which the
    # FRAMEWORK assigns to an endpoint after auditing that its route exists and answers.
    #
    # So the probe battery skipped precisely the endpoints the framework had verified, and
    # probed the ones that were merely declared and might not be built yet (a `defined`
    # endpoint with no route 404s -> fail P1). Backwards in both directions.
    #
    # MEASURED over every run directory: 4968 of the 5300 endpoint records are `implemented`
    # (94%, 169 runs), 249 `defined`, 83 `deprecated`. There is NO draft/planned status anywhere
    # in the corpus -- the case this skip was written for does not exist. 11543 of the 58000
    # probe records in the corpus are `not_defined` skips, and in r149 and r140 every single one
    # of them (256/256 and 424/424) names an `implemented` endpoint.
    #
    # What that cost: `deliverability.functionally_validated` asks only whether any probe
    # FAILED, so a run that enumerated 29 endpoints and probed none of them satisfied it -- and
    # that flag downgrades the dead-artifact, visual and ui_flow blockers from hard to warning.
    # 146 of the 532 `deliverable` verdicts in the gate ledgers (27%, 9 runs, r149/r148/r145
    # among them) rest on a run whose probes were 100% skipped. #1203d6 also makes that flag
    # ask for evidence rather than for the absence of bad news.
    # The original intent survives as an ALLOW-list: probe what is live, skip what is not.
    # `agent/tests/test_runhub_probes.py` pinned this branch with `status: "draft"` -- a value
    # that appears in no run directory -- so the test stayed green while the real data took the
    # other path for 169 runs. Fixture shape is test blindness.
    status = str(endpoint.get("status") or "defined").lower()
    if status not in _LIVE_STATUSES_1203D6:
        return ProbeSkip(reason="not_live")

    method = (endpoint.get("method") or "GET").upper()
    path = endpoint.get("path") or "/"
    if auth_required is None:
        auth_required = bool(endpoint.get("auth_required"))
    auth_required = bool(auth_required)

    if method in _DESTRUCTIVE:
        return ProbeSkip(reason="destructive")

    # POST/PUT/PATCH require auth -> skip; GET still probes (401 will be tolerated at classify).
    if method in ("POST", "PUT", "PATCH") and auth_required:
        return ProbeSkip(reason="auth_required")

    body: Optional[Dict[str, Any]] = None
    if method in ("POST", "PUT", "PATCH"):
        body = example_body if example_body is not None else {}

    # Last, so a templated DELETE still reads as `destructive` and a templated authed write as
    # `auth_required` -- those reasons say more than this one does.
    if _PATH_PARAM_1203D9.search(path):
        return ProbeSkip(reason="path_params")

    url = base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)
    # #1203e0: an honest record of whether the question is well formed. Note this is a set
    # DIFFERENCE, not a flag: the day a caller starts passing `example_body`, the endpoints it
    # covers become complete on their own, with no second place to update.
    _missing1203e0 = _required_request_fields_1203e0(endpoint) - set((body or {}).keys())
    return ProbePlan(method=method, url=url, body=body,
                     request_complete=not _missing1203e0)


def classify_probe_result(
    status_code: Optional[int],
    body_excerpt: str,
    auth_required: bool,
    transport_error: Optional[str] = None,
    headers: Optional[dict] = None,
    request_complete: bool = True,          # #1203e0
) -> ProbeOutcome:
    if transport_error == "connection_refused":
        return ProbeOutcome(verdict="fail", severity="P0",
                            note="connection refused — service not running")
    if transport_error == "timeout":
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="probe timed out")
    if transport_error:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"transport error: {transport_error}")

    if status_code is None:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="no status code received")
    if 200 <= status_code < 400:
        return ProbeOutcome(verdict="pass")
    if status_code in (401, 403) and auth_required:
        return ProbeOutcome(verdict="pass", note="auth-protected as expected")
    if status_code == 404:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="route not wired (404 on declared endpoint)")
    # #1203e0: a 400/422 answering a request we could not make well-formed. The app is
    # REJECTING A MALFORMED REQUEST, which is correct behaviour, and scoring it against the
    # handler is the same category error the line above this one already avoids for auth:
    # `401/403 when auth_required -> pass, "auth-protected as expected"`.
    #
    # MEASURED over every run directory: of the 369 failing probe records on disk, 115 are
    # `unexpected status 422` and 32 `unexpected status 400`, i.e. **147 (40%) are this** --
    # `POST /auth/register`, `/auth/login`, `/oauth/token`, all probed with `{}` because
    # `plan_probe`'s only caller never passes an `example_body`. `fail_count > 0` then raises
    # the blocker "latest run has N failed endpoint probe(s)", which cannot self-clear: the
    # probe will send `{}` again next tick.
    #
    # It had been largely hidden by a SECOND defect: the old status rule skipped `implemented`
    # endpoints (#1203d6), so by the time validation ran the auth pair was usually already
    # promoted and never asked. Fixing d6 removed that shield -- r151 was stopped at $11.70
    # nine minutes in once its registry showed `POST /auth/register` and `POST /auth/login`
    # heading for exactly this, which would have been a permanent blocker on
    # FRAMEWORK-OWNED endpoints.
    #
    # What this verdict claims is only what the probe established: the route is wired and the
    # handler validates. A 404 would still have failed, and so does a 500 below -- the two
    # answers that ARE about the handler.
    if status_code in (400, 422) and not request_complete:
        return ProbeOutcome(
            verdict="pass",
            note="%d: route wired and validating — this probe sent no request data, and the "
                 "contract declares required field(s) it cannot invent, so the rejection is "
                 "the correct answer to a malformed question, not a verdict on the handler "
                 "(a 404 or 5xx here would have been)" % status_code)
    # #1001: a 405 on a registered, implemented endpoint is a CONTRACT violation, not an
    # oddity. It fell through to the P2 catch-all below as "unexpected status 405", which is
    # what r162's backend lane was working from while nine open tasks piled up behind it.
    #
    # Two things are wrong with that. The severity buried a delivery blocker underneath the
    # P0s the lane already held; and the note carried no fact, so the task said "reproduce
    # POST … returning 405" instead of showing it.
    #
    # HTTP requires a 405 to carry `Allow:` naming the methods the server DOES accept, which
    # is precisely the missing diagnosis — the app bound some methods for this path and not
    # this one. #1000 preserved that header at capture; this quotes it.
    if status_code == 405:
        _allow = ""
        try:
            for _k, _v in (headers or {}).items():
                if str(_k).lower() == "allow":
                    _allow = str(_v).strip()
                    break
        except Exception:
            _allow = ""
        _note = ("405: the path exists but this METHOD is not bound"
                 + (f" — the app accepts [{_allow}]. Compare that list against the route "
                    f"declaration; the handler is registered somewhere the app never loaded, "
                    f"or is bound under a different method/prefix." if _allow
                    else " (no Allow header returned, which itself violates HTTP)"))
        return ProbeOutcome(verdict="fail", severity="P1", note=_note)
    if 500 <= status_code < 600:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"server error {status_code}")
    return ProbeOutcome(verdict="fail", severity="P2",
                        note=f"unexpected status {status_code}")


__all__ = [
    "ProbePlan", "ProbeSkip", "ProbeOutcome",
    "plan_probe", "classify_probe_result",
]
