"""#246 — a CREATE step that violates a UNIQUE constraint is not a broken endpoint.

r35 M2 (live): the verifier authored ``POST /api/users {"username": "${u3_name}"}`` where
NO step saves ``u3_name``, so the value is constant across cycles. Chains RE-RUN on every
validation cycle, so the create succeeded once and then returned
``400 {"detail":"integrity constraint violated"}`` forever — business_chain could never go
green again. Any create whose unique key does not vary has this failure mode.

The repair mirrors the existing 422 missing-field pattern: read the server's own error,
uniquify the unique-ish fields, retry once.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    _UNIQUE_ERR_RE,
    _UNIQUE_FIELDS,
)


def test_detects_the_real_r35_error_text():
    assert _UNIQUE_ERR_RE.search('{"detail":"integrity constraint violated"}')


def test_detects_common_unique_violation_dialects():
    for msg in (
        "UNIQUE constraint failed: users.username",          # sqlite
        'duplicate key value violates unique constraint',    # postgres
        '{"detail":"User already exists"}',                  # app-level
        "IntegrityError: integrity constraint violated",
    ):
        assert _UNIQUE_ERR_RE.search(msg), msg


def test_does_not_fire_on_unrelated_400s():
    for msg in (
        '{"detail":"Field required"}',
        '{"detail":"invalid email format"}',
        '{"detail":"password too short"}',
        "",
    ):
        assert not _UNIQUE_ERR_RE.search(msg), msg


def test_unique_fields_cover_the_classic_keys():
    for f in ("username", "email", "slug", "handle"):
        assert f in _UNIQUE_FIELDS


def _uniquify(body, sfx):
    """Mirror of the in-executor rewrite so the transform is unit-testable."""
    out, changed = dict(body), False
    for f in _UNIQUE_FIELDS:
        v = out.get(f)
        if isinstance(v, str) and v.strip():
            if "@" in v:
                lp, _, dom = v.partition("@")
                out[f] = f"{lp}_{sfx}@{dom}"
            else:
                out[f] = f"{v}_{sfx}"
            changed = True
    return out, changed


def test_uniquify_username_and_email_keep_shape():
    body = {"username": "user3", "email": "u3@example.com", "display_name": "User 3"}
    out, changed = _uniquify(body, "ab12cd")
    assert changed
    assert out["username"] == "user3_ab12cd"
    assert out["email"] == "u3_ab12cd@example.com"      # local-part only; domain intact
    assert out["display_name"] == "User 3"              # non-unique field untouched


def test_uniquify_noop_when_no_unique_field_present():
    body = {"display_name": "User 3", "avatar": "http://x/a.jpg"}
    out, changed = _uniquify(body, "ab12cd")
    assert not changed and out == body


def test_uniquify_ignores_non_string_values():
    body = {"username": 7, "email": None, "slug": "a-b"}
    out, changed = _uniquify(body, "zz")
    assert changed                      # slug changed
    assert out["username"] == 7 and out["email"] is None
    assert out["slug"] == "a-b_zz"
