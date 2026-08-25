"""#1096 — two contract tables collapse to one ORM class, and the second silently shadows it.

Found by probing: with owner-scoping wired into the harness, tiktok-r35's `/api/messages`,
`/api/activity` and their by-id siblings all returned 500 —

    AttributeError: type object 'Message' has no attribute 'user_id'

`Message` HAS a `user_id`. The generated models.py defines it twice:

    class Message(Base):            class Message(Base):
        __tablename__ = "messages"      __tablename__ = "message"
        id, user_id, sender_id, …       id, sender_id, …          <- no user_id

r35's contract carries BOTH `messages` and `message`; `_class_name` singularises a trailing
plural, so both become `Message`, and in Python the second definition wins. Handlers projected
against `messages` — which is the table marked `owner_scoped_reads`, so its read filters on
`Message.user_id` — then resolve `Message` to the SECOND class and crash. Same collision for
`Notification`/`notification` and `LiveStream`/`live_stream`: three resources whose every read
500s, from a name collision nothing reported.

The mapping has to stay consistent across two emitters: `render_models` writes the `class`
lines and `_models_meta` hands `route_projector` the `cls` name it emits handlers against.
Both called `_class_name(table)` independently, so both collapsed identically — which is why
the models.py compiled and the failure only appeared at request time.

Disambiguation keeps the singular form for the table that IS singular and gives the plural
table its plural CamelCase (`message` -> `Message`, `messages` -> `Messages`), which is both
stable and readable; a numeric suffix is the last resort. 1 of 68 corpus contracts collides —
the same footing as #1095: rare, mechanism exact, fix forced, consequence a hard 500.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (_models_meta,  # noqa: E402
                                                  render_models)

_COLLIDING = {
    "messages": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                             {"name": "user_id", "type": "integer", "references": "users.id"},
                             {"name": "content", "type": "text"}]},
    "message": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                            {"name": "sender_id", "type": "integer", "references": "users.id"},
                            {"name": "content", "type": "text"}]},
}


def _classes(src: str):
    return re.findall(r"^class (\w+)\(Base\)", src, re.M)


class TheClassNamesAreUnique(unittest.TestCase):

    def test_r35s_pair_no_longer_collapses(self):
        names = _classes(render_models(_COLLIDING))
        dupes = {n for n in names if names.count(n) > 1}
        self.assertEqual(dupes, set(), f"a class is defined twice: {sorted(dupes)}")

    def test_both_tables_are_still_emitted(self):
        src = render_models(_COLLIDING)
        self.assertIn('__tablename__ = "messages"', src)
        self.assertIn('__tablename__ = "message"', src)

    def test_the_singular_table_keeps_the_singular_name(self):
        src = render_models(_COLLIDING)
        m = re.search(r'class (\w+)\(Base\):\s*\n\s*__tablename__ = "message"', src)
        self.assertTrue(m)
        self.assertEqual(m.group(1), "Message")

    def test_the_module_still_parses(self):
        import ast
        ast.parse(render_models(_COLLIDING))


class TheHandlerMappingAgreesWithTheModels(unittest.TestCase):
    """The whole failure was the two emitters agreeing on a name that shadows."""

    def test_every_meta_cls_is_a_class_the_models_define(self):
        src = render_models(_COLLIDING)
        defined = set(_classes(src))
        meta = _models_meta(_COLLIDING)
        for table, m in meta.items():
            self.assertIn(m["cls"], defined,
                          f"{table} is projected against {m['cls']}, which models.py never defines")

    def test_no_two_tables_share_a_cls(self):
        meta = _models_meta(_COLLIDING)
        seen = {}
        for table, m in meta.items():
            self.assertNotIn(m["cls"], seen,
                             f"{table} and {seen.get(m['cls'])} both project against {m['cls']}")
            seen[m["cls"]] = table

    def test_the_owner_column_resolves_on_the_right_class(self):
        """messages carries user_id; its handler must not resolve to the other table's class."""
        meta = _models_meta(_COLLIDING)
        self.assertIn("user_id", meta["messages"]["cols"])
        self.assertNotEqual(meta["messages"]["cls"], meta["message"]["cls"])


class OrdinaryContractsAreUnchanged(unittest.TestCase):

    def test_a_plain_plural_table_still_singularises(self):
        src = render_models({"posts": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True}]}})
        self.assertIn("class Post(Base):", src)

    def test_unrelated_tables_keep_their_names(self):
        src = render_models({
            "videos": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
            "comments": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]}})
        self.assertIn("class Video(Base):", src)
        self.assertIn("class Comment(Base):", src)


if __name__ == "__main__":
    unittest.main()
