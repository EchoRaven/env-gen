"""``oauth_contract_gate(env, api_url)`` -> a ready-to-seed user_gate dict."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class TestOauthContractGate(unittest.TestCase):
    def test_returns_valid_code_check_gate(self):
        from multi_agent.bundled_tests.gate_templates import oauth_contract_gate
        gate = oauth_contract_gate(env="slack", api_url="http://localhost:8034")
        self.assertEqual(gate["type"], "code_check")
        self.assertIn("name", gate)
        self.assertIn("OAuth", gate["name"])
        self.assertIn("slack", gate["name"].lower())
        # params shape
        params = gate["params"]
        self.assertIn("command", params)
        # The command must reference the bundled test script (absolute path)
        # and the API URL env var the script reads.
        self.assertIn("test_slack.py", params["command"])
        self.assertIn("SLACK_API_URL=http://localhost:8034", params["command"])
        self.assertEqual(params["expect_exit"], 0)
        # Timeout is a positive int with a reasonable default.
        self.assertGreaterEqual(params["timeout"], 30)

    def test_supports_all_bundled_envs(self):
        from multi_agent.bundled_tests.gate_templates import (
            oauth_contract_gate,
            list_supported_envs,
        )
        envs = list_supported_envs()
        # The 7 sample envs copied from env-factory.
        self.assertTrue({"slack", "paypal", "atlassian", "telegram", "whatsapp", "zoom", "salesforce"}.issubset(set(envs)))

        for env in envs:
            gate = oauth_contract_gate(env=env, api_url=f"http://localhost:8000")
            self.assertEqual(gate["type"], "code_check")
            self.assertIn(env, gate["params"]["command"].lower())

    def test_unknown_env_raises(self):
        from multi_agent.bundled_tests.gate_templates import oauth_contract_gate
        with self.assertRaises(ValueError):
            oauth_contract_gate(env="nonexistent-env-xyz", api_url="http://localhost:8000")

    def test_custom_timeout_honored(self):
        from multi_agent.bundled_tests.gate_templates import oauth_contract_gate
        gate = oauth_contract_gate(env="slack", api_url="http://localhost:8034", timeout=300)
        self.assertEqual(gate["params"]["timeout"], 300)

    def test_shell_metacharacters_in_api_url_are_escaped(self):
        """code_check runs the command via subprocess.run(cmd, shell=True),
        so any shell metacharacter in api_url must be quoted away."""
        from multi_agent.bundled_tests.gate_templates import oauth_contract_gate
        # Classic injection: a trailing `; rm -rf /` should NOT split.
        gate = oauth_contract_gate(
            env="slack",
            api_url="http://x.com; rm -rf /tmp/data",
        )
        cmd = gate["params"]["command"]
        # The injected payload must appear INSIDE a quoted token, not as
        # a separate shell command. shlex.quote wraps with single quotes
        # when special chars are present.
        self.assertIn("'http://x.com; rm -rf /tmp/data'", cmd)
        # Belt-and-suspenders: the bare semicolon must not appear outside
        # quotes (i.e. anywhere followed by a shell command).
        self.assertNotIn("; rm -rf /tmp/data python3", cmd)


if __name__ == "__main__":
    unittest.main()
