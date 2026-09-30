r"""#1202zw: the registry rewrote the lane's response_key and never said so.

`register_endpoint` enforces the canonical envelope — `item` / `items`, whatever the projector
emits for that method and path — by overwriting `metadata.response_key` and the schema copy. It
is the right call and it was silent, so the one party that could act on it never heard.

WHAT THE SILENCE COSTS. The registry now says `items`; the lane's HANDLER still returns what the
lane declared, because nothing rewrites code. A lane that notices the mismatch compensates the
only way it can from inside the handler — by emitting BOTH. r139 ships exactly that:

    return {"items": videos, "videos": videos, "total": len(videos), ...}

the two lists byte-identical (same five ids, 4,435 bytes each) in an 8,272-byte response: 107% of
the body is the payload, carried twice. Measured over the corpus with the precise predicate — the
same `ast.Name` under two string keys AND a `len(<that name>)` in the same dict proving it is a
collection — 13 runs carry the shape, 14 sites.

★ THE MECHANISM WAS ALREADY HERE, twice. #731 returns `_note` for schema keys nothing reads and
#1202qr returns `_auth_flip_refused`, both on a COPY so the note reaches the caller without being
persisted, and #731's own comment states the reasoning this reuses: "A note on the RETURN closes
it inside one tool call ... the agent finds out while it can still act — the difference between
self-correcting in the same turn and losing a run." `registryhub_register_endpoint` hands the
returned dict straight back as its `ToolResult`, so the lane reads it in the turn it registered.

★ AND THE NOTE WAS TRACED TO ITS RECIPIENT, because "announced where the lane cannot read" is a
defect this tree has shipped before. `hub_tools.py` returns the dict as `ToolResult(data=...)`;
`step_pipeline/tooling.py` renders it with `json.dumps(result_str, indent=2)` and carries a
standing decision beside it — "NO compression / NO cap (user decision 2026-06-24): the FULL tool
result reaches the agent — truncated tool output is a correctness hazard". So the key arrives
whole, in the turn it was registered. #1116's convention reserves `notices` for framework remarks
about the CALL; this is a remark about the RECORD, which is why it travels the same way #731's
`_note` and #1202qr's `_auth_flip_refused` do.

Additive: the coercion, the stored record and every other reader are unchanged.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_AGENT, os.path.join(_AGENT, "env_generator", "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_NOTE = "_response_key_coerced_1202zw"


class TheCoercedKeyIsAnnounced(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="zw_"))
        self.rh = RegistryHub(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reg(self, path="/api/videos", key="videos", **md):
        return self.rh.register_endpoint(
            "GET", path, schema={"response_key": key}, provider="backend",
            agent="backend", status="implemented", response_key=key, **md)

    # ── the note ──────────────────────────────────────────────────────────────

    def test_a_rewritten_key_is_reported_to_the_caller(self):
        out = self._reg()
        self.assertIn(_NOTE, out, sorted(out))
        self.assertIn("videos", out[_NOTE])

    def test_the_note_names_what_it_was_replaced_with(self):
        out = self._reg()
        self.assertIn("items", out[_NOTE])

    def test_the_note_says_the_handler_must_change_too(self):
        """★ The whole point. Knowing the registry changed the key is useless unless the lane
        also learns its handler has to emit it."""
        n = self._reg()[_NOTE]
        self.assertIn("HANDLER", n)

    def test_the_note_forbids_the_compensation_that_produced_r139(self):
        """Returning both is the move a lane makes when it notices the mismatch and cannot see
        why — and it doubles the payload."""
        n = self._reg()[_NOTE]
        self.assertIn("returning both is not a fix", n.lower())
        self.assertIn("doubles the payload", n)

    # ── what must not change ──────────────────────────────────────────────────

    def test_the_registration_still_stands(self):
        """Not a rejection: the endpoint is registered, with the canonical key."""
        self._reg()
        eps = self.rh.get_endpoints()
        rec = [v for v in eps.values() if isinstance(v, dict)
               and str(v.get("path")) == "/api/videos"]
        self.assertTrue(rec, eps)
        self.assertEqual((rec[0].get("metadata") or {}).get("response_key"), "items")

    def test_the_note_is_not_persisted(self):
        """★ It travels on a COPY. A note in the stored record would reach every other reader
        and pollute the schema the way #731's own check complains about.

        Serialised, not top-level: the first version asserted only on the record's own keys, and
        a mutation that wrote the note into `metadata` — the dict this function actually edits —
        left it green. A nested leak is the likelier one."""
        import json
        self._reg()
        blob = json.dumps(self.rh.get_endpoints(), default=str)
        self.assertNotIn(_NOTE, blob, blob[:400])

    def test_a_canonical_key_is_silent(self):
        out = self._reg(key="items")
        self.assertNotIn(_NOTE, out, sorted(out))

    def test_the_exempt_kinds_are_still_exempt(self):
        """`auth` / `oauth` / `infra` / `spine` / `control_plane` / `custom` never had the key
        coerced, so there is nothing to announce for them either."""
        out = self._reg(path="/api/auth/login", key="token", kind="auth")
        self.assertNotIn(_NOTE, out, sorted(out))

    def test_a_non_api_path_is_untouched(self):
        out = self.rh.register_endpoint(
            "GET", "/health", schema={"response_key": "status"}, provider="backend",
            agent="backend", status="implemented", response_key="status")
        self.assertNotIn(_NOTE, out, sorted(out))


if __name__ == "__main__":
    unittest.main()
