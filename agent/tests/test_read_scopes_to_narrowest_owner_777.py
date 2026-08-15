r"""#777: reads scoped by the WIDER owner, so every profile saw every other profile's rows.

`_owner_fk` walks `_OWNER_FK_NAMES` in order and takes the first hit. `profile_id` is LAST, with
a stated rationale:

    # Last in the list so a user-level owner (user_id/account_id) still wins when both exist;
    # the VALUE is resolved to the caller's profile by _fw_owner_val (backend).

That reasoning is correct for FILLING a column on write. It does not transfer to SCOPING a read:
if the rows are per-profile and the filter is `user_id == caller`, every profile on the account
sees every other profile's rows.

The projector already recorded the consequence a few lines away — *"r141 shipped GET /api/my-list
and GET /api/continue-watching unscoped for exactly this reason, while r142 was safe only because
its draw happened to pick profile_id"* — and r151 shipped it again:

    DDL              my_list / ratings / continue_watching declare BOTH user_id and profile_id
    POST /api/my-list          writes profile_id x6
    GET  /api/my-list          profile_id x0, user_id x1
    GET  /api/continue-watching profile_id x0, user_id x5

#776 detects that shape (2 of 16 corpus runs declare both and read by the wider one). This is the
half that prevents it: a READ filters on the narrowest owner the table declares.

Scope held deliberately: the create/write path keeps `_owner_fk`, because the NOT-NULL argument
for filling `user_id` is still true, and the DELETE owner gate is left alone — an unmeasured
question recorded rather than an assumed one. Same first-match-over-an-unordered-list shape as
#506's accent resolution.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp


# --- the predicate ---------------------------------------------------------------------------

@pytest.mark.parametrize("cols,owner,expected", [
    (["id", "user_id", "profile_id", "title_id"], "user_id", "profile_id"),   # r151's shape
    (["id", "profile_id"], "profile_id", "profile_id"),
    (["id", "user_id", "body"], "user_id", "user_id"),                        # no narrower owner
    (["id", "account_id", "profile_id"], "account_id", "profile_id"),
    (["id"], None, None),
])
def test_the_read_owner(cols, owner, expected):
    assert rp._read_owner_fk_777({"cols": cols}, owner) == expected


@pytest.mark.parametrize("junk", [None, {}, {"cols": None}, {"cols": "notalist"}, "x"])
def test_junk_falls_back_to_the_existing_owner(junk):
    assert rp._read_owner_fk_777(junk, "user_id") == "user_id"


def test_a_public_table_is_untouched():
    """`posts(user_id, body)` — a user-owned feed with no narrower owner. Must not change."""
    assert rp._read_owner_fk_777({"cols": ["id", "user_id", "body"]}, "user_id") == "user_id"


# --- only the READ sites use it -------------------------------------------------------------------

def _src() -> str:
    return inspect.getsource(rp)


def test_all_three_read_filters_use_it():
    s = _src()
    assert s.count("read_owner_fk") >= 4, "3 read sites + the assignment"
    for frag in ('getattr(obj, "{read_owner_fk}", None)',
                 'query.filter(getattr({cls}, "{read_owner_fk}")',
                 'db.query({cls}).filter(getattr({cls}, "{read_owner_fk}")'):
        assert frag in s, frag


def test_the_DELETE_owner_gate_still_uses_the_original():
    """Deliberately out of scope: an unmeasured question, not an assumed one. If this ever
    changes it must come with its own measurement."""
    s = _src()
    i = s.index('m == "DELETE" and last_param')
    blk = s[i:s.index("elif", i + 10)]
    assert '"{owner_fk}"' in blk
    assert "read_owner_fk" not in blk


def test_the_write_path_still_uses_owner_fk():
    """The NOT-NULL argument for filling user_id is untouched."""
    s = _src()
    assert "_owner_fk(meta) if auth else None" in s


def test_it_only_applies_when_the_read_is_scoped_at_all():
    s = _src()
    assert "_read_owner_fk_777(meta, owner_fk) if read_scoped else owner_fk" in s


# --- provenance ------------------------------------------------------------------------------------

def test_the_rationale_it_overturns_is_quoted():
    d = " ".join((rp._read_owner_fk_777.__doc__ or "").split())
    assert "still wins when both exist" in d
    assert "holds for FILLING a column on write" in d


def test_r151_is_recorded_with_its_numbers():
    d = " ".join((rp._read_owner_fk_777.__doc__ or "").split())
    assert "writing profile_id six times" in d
    assert "filtering on user_id alone" in d


def test_the_projectors_own_earlier_note_is_credited():
    d = " ".join((rp._read_owner_fk_777.__doc__ or "").split())
    assert "r142 was safe only because its draw happened to pick profile_id" in d


def test_the_scope_limit_is_stated():
    d = " ".join((rp._read_owner_fk_777.__doc__ or "").split())
    assert "READS only" in d
    assert "unmeasured question rather than an assumed one" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
