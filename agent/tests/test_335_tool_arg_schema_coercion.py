"""#335: coerce LLM-authored tool args to their declared JSON-Schema type.

Every tool declares PARAMETERS as JSON-Schema, and the schema is what the model
is shown. But nothing ever enforced or coerced it, so a gateway that emits an
integer as "1" or an object as a JSON *string* produced two separate P0s:

1. THE r91 RUN-KILLER. `codehub_record_check` declares
   `evidence: {"type": "object"}`; the verifier passed a JSON STRING. It was
   persisted verbatim, and every reader of `validation:*` evidence then raised
   `'str' object has no attribute 'get'` / `.items()`. r91's store holds 4 such
   rows out of 32 validation records, and the log carries
   `framework delivery raised (non-fatal)` **218 times** over 4h26m -- the
   entire delivery-gate layer (deadline, stuck-abort, no-convergence abort,
   remediation dispatch) sat inside that one try block and was dead. The run
   ended `Run budget exceeded ... without delivery`, 0 files generated. One
   malformed row is a permanent poison pill.

2. THE VERIFIER'S KICKOFF PATH. `milestone_index` is declared
   `{"type": "integer", "minimum": 0}` and annotated `Optional[int]`, but
   workhub's service does a strict `isinstance(..., int)` and raises. Across
   the corpus the model passed a STRING every time ('1' x401, '2' x68,
   '0' x33) -- 502 failures, and 71% of `kickoff_declare_predicate` calls in
   the recent runs. r92's M2 lost all 10 of its declared predicates, so the
   milestone was verified against nothing.

Both are the same defect: the schema is advertised and never applied. Coercing
once at the dispatch chokepoint fixes this entire class rather than the two
sites that happened to hurt.

Fail-open by construction: anything that cannot be coerced is passed through
untouched, so this can never turn a working call into a failing one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _coerce(schema, args):
    from multi_agent.agents.runtime.tooling import coerce_tool_args
    return coerce_tool_args(schema, args)


INT_SCHEMA = {"type": "object", "properties": {
    "milestone_index": {"type": "integer", "minimum": 0},
    "meeting_id": {"type": "string"}}}
OBJ_SCHEMA = {"type": "object", "properties": {
    "evidence": {"type": "object"}, "name": {"type": "string"}}}


class IntegerCoercion(unittest.TestCase):

    def test_digit_string_becomes_int(self):
        """The exact r91/r92 kickoff payload."""
        out = _coerce(INT_SCHEMA, {"milestone_index": "1", "meeting_id": "doc_x"})
        self.assertEqual(out["milestone_index"], 1)
        self.assertIsInstance(out["milestone_index"], int)

    def test_zero_is_not_swallowed(self):
        self.assertEqual(_coerce(INT_SCHEMA, {"milestone_index": "0"})["milestone_index"], 0)

    def test_integral_float_becomes_int(self):
        self.assertEqual(_coerce(INT_SCHEMA, {"milestone_index": 2.0})["milestone_index"], 2)

    def test_bool_is_not_treated_as_an_int(self):
        """bool is a subclass of int in Python — a True must not become 1."""
        out = _coerce(INT_SCHEMA, {"milestone_index": True})
        self.assertIs(out["milestone_index"], True)

    def test_unparseable_passes_through_untouched(self):
        out = _coerce(INT_SCHEMA, {"milestone_index": "abc"})
        self.assertEqual(out["milestone_index"], "abc")

    def test_none_passes_through(self):
        self.assertIsNone(_coerce(INT_SCHEMA, {"milestone_index": None})["milestone_index"])


class ObjectCoercion(unittest.TestCase):

    def test_json_string_becomes_a_dict(self):
        """The r91 killer: evidence arrived as a JSON string."""
        raw = '{"url": "http://localhost:8003/", "http_status": 200, "flow": "fyp_feed"}'
        out = _coerce(OBJ_SCHEMA, {"evidence": raw, "name": "validation:ui_flow:fyp_feed"})
        self.assertIsInstance(out["evidence"], dict)
        self.assertEqual(out["evidence"]["http_status"], 200)
        # The consumers that raised in r91 must now work.
        self.assertEqual(out["evidence"].get("flow"), "fyp_feed")
        list(out["evidence"].items())

    def test_non_json_string_is_wrapped_not_persisted_raw(self):
        """A bare string must never reach a consumer that calls .get()/.items()."""
        out = _coerce(OBJ_SCHEMA, {"evidence": "looks good"})
        self.assertIsInstance(out["evidence"], dict)
        self.assertEqual(out["evidence"], {"raw": "looks good"})

    def test_json_string_encoding_a_non_object_is_wrapped(self):
        out = _coerce(OBJ_SCHEMA, {"evidence": "[1, 2]"})
        self.assertIsInstance(out["evidence"], dict)

    def test_a_real_dict_is_left_alone(self):
        ev = {"http_status": 200}
        self.assertIs(_coerce(OBJ_SCHEMA, {"evidence": ev})["evidence"], ev)


class OtherScalarTypes(unittest.TestCase):

    def test_boolean_strings(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        for raw, want in (("true", True), ("True", True), ("false", False),
                          ("False", False)):
            self.assertIs(_coerce(schema, {"flag": raw})["flag"], want)

    def test_number_string_becomes_float(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "number"}}}
        self.assertEqual(_coerce(schema, {"ratio": "1.5"})["ratio"], 1.5)

    def test_array_json_string_becomes_list(self):
        schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        self.assertEqual(_coerce(schema, {"items": '["a","b"]'})["items"], ["a", "b"])

    def test_array_non_json_passes_through(self):
        schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        self.assertEqual(_coerce(schema, {"items": "a,b"})["items"], "a,b")


class NeverBreaksAnythingThatWorkedBefore(unittest.TestCase):

    def test_unknown_keys_are_untouched(self):
        out = _coerce(INT_SCHEMA, {"surprise": "1"})
        self.assertEqual(out["surprise"], "1")

    def test_missing_schema_is_a_no_op(self):
        args = {"milestone_index": "1"}
        self.assertEqual(_coerce(None, args), args)
        self.assertEqual(_coerce({}, args), args)

    def test_garbage_schema_never_raises(self):
        self.assertEqual(_coerce({"properties": "nonsense"}, {"a": 1}), {"a": 1})

    def test_input_dict_is_not_mutated(self):
        args = {"milestone_index": "1"}
        _coerce(INT_SCHEMA, args)
        self.assertEqual(args["milestone_index"], "1")


class AgainstTheRealToolSchemas(unittest.TestCase):
    """Pin the two schemas whose violation produced the P0s."""

    def _schema_of(self, tool_name):
        import importlib
        mod = importlib.import_module("tools.hub_tools")
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if isinstance(cls, type) and getattr(cls, "NAME", None) == tool_name:
                return getattr(cls, "PARAMETERS", None)
        return None

    def test_record_check_evidence_is_declared_object(self):
        schema = self._schema_of("codehub_record_check")
        self.assertIsNotNone(schema, "codehub_record_check not found")
        self.assertEqual(
            (schema.get("properties") or {}).get("evidence", {}).get("type"), "object")
        out = _coerce(schema, {"pr_id": "main", "name": "validation:ui_flow:x",
                               "status": "success", "evidence": '{"http_status": 200}'})
        self.assertIsInstance(out["evidence"], dict)

    def test_kickoff_predicate_milestone_index_is_declared_integer(self):
        schema = self._schema_of("kickoff_declare_predicate")
        self.assertIsNotNone(schema, "kickoff_declare_predicate not found")
        self.assertEqual(
            (schema.get("properties") or {}).get("milestone_index", {}).get("type"),
            "integer")
        self.assertEqual(_coerce(schema, {"milestone_index": "1"})["milestone_index"], 1)


if __name__ == "__main__":
    unittest.main()


class StringIsTheOneTypeNotCoerced(unittest.TestCase):
    """#1066 — state the coverage, so the gap is a decision and not a surprise.

    `_coerce_one` handles integer, number, boolean, object and array. `string` —
    the most common declared type — is absent, and the docstring gives a reason
    for each of the five it does handle without mentioning the sixth.

    No run shows harm from it: across the 201 kept logs there is not one
    `'list' object has no attribute 'lower'/'strip'/'startswith'`, and no
    stringified content-block list. But the failure mode WOULD be silent rather
    than loud — `content[:300]` slices a list, `"api" in content` becomes
    membership — so the absence of exceptions is not by itself evidence of
    absence, and the next reader should not have to work that out again.

    What the fail-open promise guarantees today, pinned: a non-string reaching a
    string param is returned UNTOUCHED, never mangled.
    """

    def test_a_list_for_a_string_param_is_left_alone(self):
        schema = {"properties": {"name": {"type": "string"}}}
        blocks = [{"type": "text", "text": "hi"}]
        out = _coerce(schema, {"name": blocks})
        self.assertIs(out["name"], blocks,
                      "fail-open: untouched, not str()'d and not dropped")

    def test_an_int_for_a_string_param_is_left_alone(self):
        schema = {"properties": {"name": {"type": "string"}}}
        out = _coerce(schema, {"name": 7})
        self.assertEqual(out["name"], 7)

    def test_a_real_string_is_unchanged(self):
        schema = {"properties": {"name": {"type": "string"}}}
        out = _coerce(schema, {"name": "ok"})
        self.assertEqual(out["name"], "ok")

    def test_the_other_five_types_are_still_coerced(self):
        """Non-vacuity: this class documents an omission, not a broken coercer."""
        schema = {"properties": {"n": {"type": "integer"},
                                 "f": {"type": "number"},
                                 "b": {"type": "boolean"},
                                 "o": {"type": "object"},
                                 "a": {"type": "array"}}}
        out = _coerce(schema, {"n": "3", "f": "1.5", "b": "true",
                                        "o": '{"k": 1}', "a": '["x"]'})
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["f"], 1.5)
        self.assertIs(out["b"], True)
        self.assertEqual(out["o"], {"k": 1})
        self.assertEqual(out["a"], ["x"])
