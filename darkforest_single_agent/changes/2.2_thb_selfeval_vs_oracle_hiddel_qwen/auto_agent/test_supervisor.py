"""Checks for the quota and account boundaries of the durable auto-agent."""
import unittest

import quota_utils
import run_auto_agent as agent


class QuotaTests(unittest.TestCase):
    def test_real_five_hour_message(self):
        msg = "You've hit your 5-hour limit · resets 2:10am (America/Indiana/Indianapolis)"
        self.assertEqual(quota_utils.classify_failure(msg), "limit")
        self.assertIsNotNone(quota_utils.reset_wait_s(msg))

    def test_limit_without_reset_and_api_status(self):
        self.assertEqual(quota_utils.classify_failure("You've hit your 5-hour limit"), "limit")
        self.assertEqual(quota_utils.classify_failure("api_error_status=429"), "limit")
        self.assertEqual(quota_utils.classify_failure("session limit reached"), "limit")

    def test_auth_is_not_treated_as_overload(self):
        self.assertEqual(quota_utils.classify_failure("api_error_status=401 api error"), "auth")
        self.assertEqual(quota_utils.classify_failure("overloaded 529"), "overload")


class AccountBoundaryTests(unittest.TestCase):
    def test_only_acct2_token_is_passed_to_claude(self):
        env = agent.claude_env()
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], agent.ACCT2_CONFIG)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("CLAUDE_OAUTH_TOKEN_FILE", env)

    def test_normal_reply_cannot_finish_incomplete_jobs(self):
        self.assertFalse(agent.goal_complete())

    def test_resume_uses_supported_safety_prompt_flag(self):
        args = agent.build_claude_args("continue", "123", True)
        self.assertIn("--append-system-prompt", args)
        self.assertNotIn("--append-system-prompt-file", args)
        self.assertIn("--resume", args)
        self.assertIn("--model", args)
        self.assertIn("claude-opus-5-5", args)
        self.assertIn("medium", args)


if __name__ == "__main__":
    unittest.main()
