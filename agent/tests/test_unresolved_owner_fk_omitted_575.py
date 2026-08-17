r"""#575 (netflix r139, live): a body OWNER-FK whose `${var}` never resolved was filled from the
global last-id pool with ANOTHER user's id, turning a legitimate own-scope write into a fake
cross-user attempt that #566s correctly answered 403.

r139 `m2_continue_watching_state`:

    [1] GET  /api/profiles            auth=tokenA   save profileA<-items.0.id   -> save FAILED
    [3] POST /api/continue-watching   body={"profile_id": "${profileA}", ...}   -> 403
    [4] GET  /api/continue-watching?profile_id=17                               <- someone else's

The chain user registered seconds earlier and OWNS NOTHING, so the (correctly) owner-scoped
`GET /api/profiles` returned `{"items": []}` and the save starved. Three M2 chains failed this
way at once — `m2_my_list_ownership_and_toggle`, `m2_continue_watching_state`,
`m2_ratings_and_top10` — all with "profile_id does not belong to the caller". #566s was right
every time; the harness manufactured the violation.

Fix: omit, never guess. The projected create already fills an ABSENT owner FK with the caller's
own value (`valid.setdefault(ofk, _fw_owner_val(...))`), which is what the step meant. The
path-side ladder has had the equivalent rung since #32; the body side never did.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


def test_r139_an_unresolved_owner_fk_is_dropped():
    body = {"profile_id": "${profileA}", "title_id": 7, "progress_seconds": 42}
    out, dropped = ce._drop_unresolved_owner_fks(body)
    assert dropped == ["profile_id"]
    assert out == {"title_id": 7, "progress_seconds": 42}


def test_a_RESOLVED_owner_fk_is_kept():
    """The multi-profile case: a real captured id must still be sent (and #566s verifies it)."""
    body = {"profile_id": 17, "title_id": 7}
    out, dropped = ce._drop_unresolved_owner_fks(body)
    assert dropped == [] and out is body


def test_a_non_owner_fk_placeholder_is_left_to_the_existing_resolver():
    """`title_id` is a SUBJECT, not an owner — #10/#263's resolver still owns that case."""
    body = {"title_id": "${titleId}", "progress_seconds": 42}
    out, dropped = ce._drop_unresolved_owner_fks(body)
    assert dropped == [] and out is body


def test_every_owner_column_name_the_projector_knows_is_covered():
    for col in ("user_id", "author_id", "owner_id", "profile_id"):
        out, dropped = ce._drop_unresolved_owner_fks({col: "${x}", "keep": 1})
        assert dropped == [col] and out == {"keep": 1}


def test_partial_placeholders_and_literals_are_untouched():
    """Only a WHOLE-value placeholder is unresolved; a literal that merely contains one is not
    ours to judge."""
    for val in ("prefix-${x}", "17", "", "profile-1"):
        out, dropped = ce._drop_unresolved_owner_fks({"profile_id": val})
        assert dropped == [], val


def test_non_mapping_bodies_pass_through():
    for b in (None, [], "x", 5):
        out, dropped = ce._drop_unresolved_owner_fks(b)
        assert out is b and dropped == []


def test_the_drop_runs_before_the_guessing_fallback():
    """Order is the whole point: after `_resolve_unresolved_dollar_vars` the value would
    already be a foreign id and indistinguishable from a real one."""
    import inspect
    src = inspect.getsource(ce.execute_chain)
    i_drop = src.index("_drop_unresolved_owner_fks(body)")
    i_fill = src.index("_resolve_unresolved_dollar_vars(body")
    assert i_drop < i_fill, "the owner-FK strip must precede the last-id fallback"


def test_the_omission_is_recorded():
    import inspect
    src = inspect.getsource(ce.execute_chain)
    assert 'owner-fk-omitted:' in src, "a silent body edit is undiagnosable"


def test_575b_a_cross_user_denial_step_keeps_its_unresolved_owner_fk(monkeypatch):
    """Self-review catch. On a DENIAL probe the unresolved owner FK IS the probe: dropping it
    sends the write into the CALLER's own scope, the app correctly answers 201, and the step
    reports a leak that never happened. Leaving the literal makes the backend reject it — the
    convention the path-side ladder has followed since #59b."""
    seen = {}

    def fake(method, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"t","user":{"id":1}}',
                    "error": None}
        seen["body"] = body
        return {"status": 400, "body_text": '{"detail":"invalid profile_id"}', "error": None}

    monkeypatch.setattr(ce, "_http", fake)
    chain = {"name": "idor", "steps": [
        {"method": "POST", "path": "/auth/register", "body": {"email": "b_${rand}@x.io"},
         "save": {"tokenB": "access_token", "token": "access_token"}},
        {"method": "POST", "path": "/api/my-list", "auth": "tokenB",
         "body": {"profile_id": "${foreignProfile}", "title_id": 1},
         "expect": [403, 404]},
    ]}
    res = ce.execute_chain("http://app", chain)
    # #575b's contract: the key is NOT DROPPED on a denial step, and no omission is recorded.
    assert "profile_id" in (seen.get("body") or {}), seen
    assert not any("owner-fk-omitted" in str(a) for st in res["steps"]
                   for a in (st.get("autofilled") or [])), res["steps"]
    # (Residual, PRE-EXISTING, out of this change's scope: the generic #10/#263 body fallback
    # still substitutes last_id for the unresolved var on a denial step. That is behaviour #575
    # inherited, not introduced; the path side is guarded by #59b. Left alone deliberately — no
    # evidence of harm, and widening it would touch every FK, not just owner columns.)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
