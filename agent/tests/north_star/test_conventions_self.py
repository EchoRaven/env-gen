"""Self-tests for the convention-tolerant oracle helpers.

These pin the BEHAVIOR contracts the helpers must hold:
- ``assert_created`` raises on missing id (R2 round-6 fix — previously
  silently returned None, defeating the helper's anti-tolerance purpose).
- ``_id_of`` is composable (returns None, doesn't raise).
- ``items_of`` is composable (returns [], doesn't raise).
- ``assert_unauthorized`` accepts 401 and 403.
- ``assert_client_error`` accepts 400 OR 422 when expect ∈ {400, 422};
  insists on JSON content-type to catch the "200 with HTML app shell"
  anti-pattern.

This file lives under ``tests/north_star/`` so the A2 collection
isolation applies — default ``pytest tests/`` does NOT collect it.
Run explicitly via:
  pytest tests/north_star/ --confcutdir=tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

# R1 round-14: previously `from tests.north_star._conventions import ...` —
# absolute import that only resolves if `agent/` is on sys.path as a package
# root, which `pytest tests/` does not guarantee (`tests/__init__.py` is
# absent by design). The other gate files (test_classifier_acceptance.py /
# test_itt_recompute.py) use the same sibling-import pattern below; this
# brings test_conventions_self.py into alignment so all three gate files
# collect cleanly regardless of cwd or pytest invocation pattern.
_NORTH_STAR_DIR = Path(__file__).resolve().parent
if str(_NORTH_STAR_DIR) not in sys.path:
    sys.path.insert(0, str(_NORTH_STAR_DIR))

from _conventions import (  # noqa: E402
    _id_of,
    assert_client_error,
    assert_created,
    assert_unauthorized,
    items_of,
)


def _mock_resp(status_code, body=None, content_type="application/json"):
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.json.return_value = body if body is not None else {}
    return resp


class AssertCreatedRequiresId(unittest.TestCase):
    """R2 round-6: assert_created must NOT silently return None when
    the response body has no recoverable id field."""

    def test_raises_on_missing_id_with_201(self):
        resp = _mock_resp(201, body={"some_other_key": "but no id"})
        with self.assertRaises(AssertionError) as ctx:
            assert_created(resp)
        self.assertIn("missing id", str(ctx.exception))

    def test_raises_on_missing_id_with_200(self):
        resp = _mock_resp(200, body={"unrelated": "fields"})
        with self.assertRaises(AssertionError):
            assert_created(resp)

    def test_raises_on_empty_body(self):
        resp = _mock_resp(201, body={})
        with self.assertRaises(AssertionError):
            assert_created(resp)

    def test_raises_on_non_json_body(self):
        resp = mock.MagicMock()
        resp.status_code = 201
        resp.json.side_effect = ValueError("not json")
        with self.assertRaises(AssertionError) as ctx:
            assert_created(resp)
        self.assertIn("not JSON", str(ctx.exception))

    def test_returns_id_on_valid_response(self):
        resp = _mock_resp(201, body={"id": "post_123", "body": "hello"})
        self.assertEqual(assert_created(resp), "post_123")

    def test_returns_nested_id(self):
        resp = _mock_resp(200, body={"data": {"_id": "post_456"}})
        self.assertEqual(assert_created(resp), "post_456")

    def test_accepts_alternative_id_keys(self):
        for key in ("id", "_id", "uuid", "pk"):
            with self.subTest(key=key):
                resp = _mock_resp(201, body={key: f"val_{key}"})
                self.assertEqual(assert_created(resp), f"val_{key}")

    def test_rejects_wrong_status_code(self):
        # 404, 500 etc. — not 200/201 → assertion fails BEFORE id check
        for code in (400, 404, 422, 500):
            with self.subTest(code=code):
                resp = _mock_resp(code, body={"id": "ignored"})
                with self.assertRaises(AssertionError) as ctx:
                    assert_created(resp)
                self.assertIn("create expected 200/201", str(ctx.exception))


class IdAndItemsExtractorsAreComposable(unittest.TestCase):
    """``_id_of`` and ``items_of`` are pure extractors — they return
    None/[] on missing, callers are responsible for asserting."""

    def test_id_of_returns_none_on_missing(self):
        self.assertIsNone(_id_of({"no_id_here": "x"}))

    def test_id_of_returns_none_on_non_dict(self):
        self.assertIsNone(_id_of([1, 2, 3]))
        self.assertIsNone(_id_of("string"))
        self.assertIsNone(_id_of(None))

    def test_items_of_returns_empty_on_missing(self):
        self.assertEqual(items_of({"no_items": "here"}), [])

    def test_items_of_returns_empty_on_non_dict_non_list(self):
        self.assertEqual(items_of("string"), [])
        self.assertEqual(items_of(None), [])

    def test_items_of_returns_list_when_bare(self):
        self.assertEqual(items_of([1, 2, 3]), [1, 2, 3])

    def test_items_of_unwraps_common_envelopes(self):
        for key in ("posts", "items", "data", "results"):
            with self.subTest(key=key):
                self.assertEqual(items_of({key: ["a", "b"]}), ["a", "b"])


class AssertUnauthorizedAcceptsBothCodes(unittest.TestCase):
    def test_401_passes(self):
        assert_unauthorized(_mock_resp(401))

    def test_403_passes(self):
        assert_unauthorized(_mock_resp(403))

    def test_200_fails(self):
        with self.assertRaises(AssertionError):
            assert_unauthorized(_mock_resp(200))


class AssertClientErrorRequiresJsonBody(unittest.TestCase):
    """200 with HTML app-shell anti-pattern catch."""

    def test_400_with_json_passes(self):
        assert_client_error(_mock_resp(400, content_type="application/json"))

    def test_400_with_html_fails(self):
        with self.assertRaises(AssertionError) as ctx:
            assert_client_error(_mock_resp(400, content_type="text/html"))
        self.assertIn("HTML app shell", str(ctx.exception))

    def test_422_synonymous_with_400_when_expect_400(self):
        assert_client_error(_mock_resp(422), expect=400)
        assert_client_error(_mock_resp(400), expect=422)

    def test_exact_expect_strict(self):
        with self.assertRaises(AssertionError):
            assert_client_error(_mock_resp(404), expect=403)

    def test_any_4xx_when_no_expect(self):
        for code in (400, 401, 403, 404, 422, 451):
            with self.subTest(code=code):
                assert_client_error(_mock_resp(code))


if __name__ == "__main__":
    unittest.main()
