r"""#1203n2: the denial probe denied with an identity the reset had already wiped.

r190 died on this. `creator_follow_unfollow_privacy` reads:

    0. POST /auth/register                       save actorUsername
    1. POST /api/v1/reset                        <- wipes the users table
    3. POST /api/users/${actorUsername}/follow   expect [409]      (a SELF-follow denial)

After the reset `${actorUsername}` no longer names the caller, so step 3 is an ordinary follow
of somebody else and answers 201. The step reported "DENIAL-PROBE got success — the request
was NOT rejected", which reads as an auth hole in the app -- while the delivered handler
implements the rule (`cannot_follow_self`, custom_routes.py:3668) and never got a self-follow
to reject. Four chains failed this way; `business_chain_failing` was the hold r190 died on,
after 15.7 hours, 29900 LLM calls and $1549.68 across five attempts, with 2 of 5 milestones.

NARROWED BY MEASUREMENT, TWICE -- and the first rule would have been a disaster:

    "a variable captured before a reset and used after it"   169 chains, 164 PASSING
    "...captured from an AUTH step"                            5 chains, 2 failing (r190)

Most such variables are TENANT ids, and resetting a tenant then using its id is exactly
right. Even the narrow rule is 3-of-5 passing, which is far too noisy to REJECT a chain on,
so this only ANNOTATES a step that has already failed as a denial probe -- the same policy as
#1203mx/#1203my. The three passing chains never see it.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    identity_wiped_by_reset_1203n2 as wiped,
)

R190 = [
    {"method": "POST", "path": "/auth/register", "save": {"token": "access_token",
                                                          "actorUsername": "user.username"}},
    {"method": "POST", "path": "/api/v1/reset"},
    {"method": "GET", "path": "/api/creators/suggested", "save": {"creatorUsername": "items.0.username"}},
    {"method": "POST", "path": "/api/users/${actorUsername}/follow", "expect": [409]},
    {"method": "DELETE", "path": "/api/users/${actorUsername}/follow", "expect": [409]},
    {"method": "POST", "path": "/api/users/${creatorUsername}/follow", "expect": [200, 201]},
]

TENANT = [
    {"method": "POST", "path": "/auth/register", "save": {"token": "access_token"}},
    {"method": "POST", "path": "/api/v1/tenants", "save": {"tenantId": "id"}},
    {"method": "POST", "path": "/api/v1/reset", "body": {"tenant_id": "${tenantId}"}},
    {"method": "GET", "path": "/api/v1/tenants/${tenantId}", "expect": [200]},
]


class TheWipedActorIsNamed(unittest.TestCase):
    def test_r190s_failing_step(self):
        s = wiped(R190, 3)
        self.assertIn("actorUsername", s)
        self.assertIn("/auth/register", s)
        self.assertIn("/api/v1/reset", s)

    def test_it_names_both_step_indices(self):
        s = wiped(R190, 3)
        self.assertIn("step[0]", s)
        self.assertIn("step[1]", s)

    def test_it_says_the_denial_cannot_hold(self):
        s = wiped(R190, 3)
        self.assertIn("no longer names the caller", s)
        self.assertIn("self-* denial cannot hold", s)

    def test_it_names_the_two_ways_out(self):
        s = wiped(R190, 3)
        self.assertIn("AFTER the reset", s)
        self.assertIn("drop the reset", s)

    def test_the_delete_step_too(self):
        self.assertIn("actorUsername", wiped(R190, 4))


class ItStaysSilentWhereTheShapeIsLegitimate(unittest.TestCase):
    def test_a_tenant_id_used_after_resetting_that_tenant(self):
        """The 164-of-169 case: reset a tenant, then use its id. Exactly right."""
        self.assertEqual(wiped(TENANT, 3), "")

    def test_a_variable_captured_AFTER_the_reset(self):
        self.assertEqual(wiped(R190, 5), "")      # creatorUsername saved at step 2

    def test_no_reset_in_between(self):
        steps = [R190[0], R190[3]]
        self.assertEqual(wiped(steps, 1), "")

    def test_the_ADVISED_order_is_not_flagged(self):
        """reset FIRST, then register, then use -- which is exactly what this annotation
        tells the author to do. Flagging it would punish the fix. Mutation N23 widens the
        window to `range(0, i)` and this is the case that catches it."""
        steps = [{"path": "/api/v1/reset"},
                 {"path": "/auth/register", "save": {"actorUsername": "user.username"}},
                 {"path": "/api/users/${actorUsername}/follow", "expect": [409]}]
        self.assertEqual(wiped(steps, 2), "")

    def test_a_reset_before_the_capture_and_another_after_is_still_flagged(self):
        """Only the reset that sits BETWEEN capture and use matters."""
        steps = [{"path": "/api/v1/reset"},
                 {"path": "/auth/register", "save": {"actorUsername": "user.username"}},
                 {"path": "/api/v1/reset"},
                 {"path": "/api/users/${actorUsername}/follow", "expect": [409]}]
        self.assertIn("step[2]", wiped(steps, 3))

    def test_a_variable_from_a_non_auth_step(self):
        steps = [{"path": "/api/creators/suggested", "save": {"u": "items.0.username"}},
                 {"path": "/api/v1/reset"},
                 {"path": "/api/users/${u}/follow"}]
        self.assertEqual(wiped(steps, 2), "")

    def test_a_step_with_no_variables(self):
        self.assertEqual(wiped(R190, 2), "")

    def test_the_first_step(self):
        self.assertEqual(wiped(R190, 0), "")


class ItNeverRaises(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertEqual(wiped([], 0), "")
        self.assertEqual(wiped(None, 1), "")

    def test_a_bad_index(self):
        self.assertEqual(wiped(R190, 99), "")
        self.assertEqual(wiped(R190, "x"), "")

    def test_unserialisable_step_contents(self):
        class _Bad:
            pass
        steps = [R190[0], R190[1], {"path": "/x/${actorUsername}", "body": {"o": _Bad()}}]
        self.assertIn("actorUsername", wiped(steps, 2))


class ItIsAppendedOnlyToAFailedDenialProbe(unittest.TestCase):
    """The reason the three passing chains with this shape never see it."""

    def _denial_branch(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
        tree = ast.parse(inspect.getsource(CE))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", "") != "identity_wiped_by_reset_1203n2":
                continue
            return node
        return None

    def test_the_executor_calls_it(self):
        self.assertIsNotNone(self._denial_branch())

    def test_it_is_handed_the_raw_steps_and_the_index(self):
        call = self._denial_branch()
        self.assertEqual([getattr(a, "id", None) for a in call.args], ["_steps", "idx"],
                         "it must see the UNSUBSTITUTED steps and this step's index")

    def test_the_call_sits_inside_the_denial_probe_sentence(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
        tree = ast.parse(inspect.getsource(CE))
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            dump = ast.dump(node)
            if "identity_wiped_by_reset_1203n2" in dump and "DENIAL-PROBE got success" in dump:
                found = True
        self.assertTrue(found, "the annotation is not part of the denial-probe sentence")


if __name__ == "__main__":
    unittest.main()
