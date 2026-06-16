"""Bundled test scripts shipped with the env-gen framework.

These are runnable Python scripts (not pytest cases) intended to be wired
as ``code_check`` user gates against an env-gen-built project. Each
subpackage groups tests by contract — e.g. ``oauth_contract`` is the
8-test minimum OAuth contract from the ``env-oauth-blueprint`` skill,
one file per upstream env (slack, paypal, atlassian, …).

See :mod:`multi_agent.bundled_tests.gate_templates` for helpers that
turn one of these scripts into a ready-to-seed ``user_gate`` dict.
"""
