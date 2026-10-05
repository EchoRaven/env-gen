r"""#1203fp: the kickoff handed RegistryHub a path RegistryHub forbids, and the run died.

`_build_contract`'s `auto_from_ui_declaration` reconcile copies a path out of a ui_page's
`apis_used` VERBATIM and appends it as an endpoint. `apis_used` carries the parameterised form
with a BARE placeholder -- `POST /api/videos/{}/like` -- written there by the frontend lane AND
by the orchestrator itself (r153/r157: writer=orchestrator). RegistryHub's #1202xl guard then
refuses it ("every {...} must be a NAMED identifier and must be the WHOLE segment"), the refusal
becomes `phase='partial_failure'`, and `orchestrator.run()` raises

    RuntimeError: Kickoff did not finalize cleanly: phase='partial_failure',
    failures=[{'hub': 'registryhub', 'item': {'method': 'POST',
               'path': '/api/videos/{}/like', 'source': 'auto_from_ui_declaration'},
               'error': ValueError("invalid path parameter '{}' ...")}]

which kills the whole run -- AFTER its first delivery, because this is the kickoff for the NEXT
milestone. Every instance in the corpus is the same shape:

    run   failing path                releases cut before it died
    r145  /api/videos/{}              1.0.0
    r146  /api/videos/{}              1.0.0, 1.1.0
    r147  /api/videos/{}/comments     1.0.0
    r152  /api/videos/{}/comments     1.0.0
    r153  /api/videos/{}/comments     1.0.0
    r156  /api/videos/{}/comments     1.0.0
    r157  /api/videos/{}/comments     1.0.0
    r160  /api/videos/{}/like         1.0.0

Eight runs, every one stopping at the first milestone of a four-milestone plan. 119 such
`apis_used` entries exist across 15 runs; these eight are where the entry was not already a
known endpoint, so the append fired.

#1202xl is RIGHT to refuse -- a route with a bare `{}` cannot be served, and r121 shipped an MCP
tool pointing at `{encodeURIComponent}(id)` for want of that guard. Its own blast-radius note
reads "of the 4,940 registered paths in the corpus, exactly 2 are newly rejected ... Zero
collateral", and that count could not see this class: it measured paths already STORED, and a
`{}` path is never stored precisely because it is refused.

`{id}` is not invented here. Measured over every parameterised segment in the corpus: 1100 bare
`{name}` vs 510 `{x_id}` vs 4 `{xId}`; `{id}` alone 979 times; and after each noun segment the
bare form leads (`videos` -> `id` 445 vs `video_id` 198, `titles` -> `id` 132, `comments` ->
`id` 85). So no singularisation heuristic is needed.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    _build_contract, _name_bare_path_params_1203fp, _param_blind_key_1203fp)
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


def _drafts(apis_used, declared_endpoints=()):
    """A minimal two-section draft carrying one ui_page with the given apis_used."""
    return {
        "backend": {"endpoints": [dict(e) for e in declared_endpoints],
                    "data_model": {"tables": []}},
        "frontend": {"ui_pages": [{"id": "fyp_feed", "name": "fyp_feed", "route": "/",
                                   "component": "ForYouFeedPage",
                                   "apis_used": list(apis_used)}],
                     "ui_components": []},
    }


def _auto(contract):
    return [e for e in (contract.get("endpoints") or [])
            if e.get("source") == "auto_from_ui_declaration"]


class TheBarePlaceholderIsNamed(unittest.TestCase):
    def test_the_bare_segment_becomes_the_registrys_own_convention(self):
        self.assertEqual(_name_bare_path_params_1203fp("/api/videos/{}/like"),
                         "/api/videos/{id}/like")
        self.assertEqual(_name_bare_path_params_1203fp("/api/videos/{}"), "/api/videos/{id}")
        self.assertEqual(_name_bare_path_params_1203fp("/api/users/{}/follow"),
                         "/api/users/{id}/follow")

    def test_an_already_named_path_is_returned_unchanged(self):
        for p in ("/api/videos/{video_id}/like", "/api/v1/tenants/{tenant_id}",
                  "/api/users/{username}", "/api/videos", "/api/videos/feed"):
            self.assertEqual(_name_bare_path_params_1203fp(p), p)

    def test_a_malformed_segment_is_not_quietly_turned_into_a_parameter(self):
        """r121's `{encodeURIComponent}(id)` must stay refused: #1202xl exists for it, and a
        producer that 'fixed' it here would re-open exactly what that guard closed."""
        p = "/api/videos/{encodeURIComponent}(id)"
        self.assertEqual(_name_bare_path_params_1203fp(p), p)


class TheKeyIsParameterBlind(unittest.TestCase):
    def test_every_parameter_spelling_is_one_endpoint(self):
        keys = {_param_blind_key_1203fp("POST", p) for p in (
            "/api/videos/{}/like", "/api/videos/{id}/like",
            "/api/videos/{video_id}/like", "/api/videos/{videoId}/like")}
        self.assertEqual(len(keys), 1, keys)

    def test_different_endpoints_stay_different(self):
        self.assertNotEqual(_param_blind_key_1203fp("POST", "/api/videos/{id}/like"),
                            _param_blind_key_1203fp("POST", "/api/videos/{id}/save"))
        self.assertNotEqual(_param_blind_key_1203fp("POST", "/api/videos/{id}"),
                            _param_blind_key_1203fp("DELETE", "/api/videos/{id}"))

    def test_the_method_and_trailing_slash_are_normalised(self):
        self.assertEqual(_param_blind_key_1203fp("post", "/api/videos/{id}/"),
                         _param_blind_key_1203fp("POST", "/api/videos/{id}"))

    def test_a_malformed_segment_is_not_collapsed(self):
        self.assertNotEqual(_param_blind_key_1203fp("GET", "/api/videos/{encodeURIComponent}(id)"),
                            _param_blind_key_1203fp("GET", "/api/videos/{id}"))


class TheRegistryAcceptsWhatTheKickoffProduces(unittest.TestCase):
    """The decisive test: the two sides of the crash, in one assertion. Before this patch the
    contract carried `/api/videos/{}/like` and `register_endpoint` raised on it."""

    def _hub(self):
        return RegistryHub(Path(tempfile.mkdtemp()))

    def test_r160s_own_declaration_now_registers(self):
        contract = _build_contract(_drafts([
            "POST /api/videos/{}/like", "DELETE /api/videos/{}/like",
            "POST /api/videos/{}/save", "DELETE /api/videos/{}/save"]))
        auto = _auto(contract)
        self.assertEqual(len(auto), 4, auto)
        hub = self._hub()
        for ep in auto:
            self.assertNotIn("{}", ep["path"], ep)
            # actor='orchestrator' is what finalize_kickoff really uses -- the role gate
            # names it: "the kickoff coordinator (actor='orchestrator') registers contracts
            # during finalize_kickoff".
            hub.register_endpoint(method=ep["method"], path=ep["path"],
                                  provider="backend", agent="orchestrator")   # must not raise

    def test_the_pre_patch_path_is_still_refused_by_the_registry(self):
        """A positive control for the guard itself -- if #1202xl ever stopped refusing, this
        patch would be solving a problem that no longer exists and the test should say so."""
        hub = self._hub()
        with self.assertRaises(ValueError):
            hub.register_endpoint(method="POST", path="/api/videos/{}/like",
                                  provider="backend", agent="orchestrator")

    def test_a_declared_twin_under_another_param_name_is_not_duplicated(self):
        """Renaming the placeholder without a param-blind membership test would trade the crash
        for a duplicate registration of an endpoint the backend already declared."""
        contract = _build_contract(_drafts(
            ["POST /api/videos/{}/like"],
            declared_endpoints=[{"method": "POST", "path": "/api/videos/{video_id}/like"}]))
        self.assertEqual(_auto(contract), [])

    def test_a_genuinely_new_endpoint_is_still_appended(self):
        """Negative control for the blindness: it must not swallow a real gap."""
        contract = _build_contract(_drafts(
            ["POST /api/videos/{}/share"],
            declared_endpoints=[{"method": "POST", "path": "/api/videos/{video_id}/like"}]))
        auto = _auto(contract)
        self.assertEqual([e["path"] for e in auto], ["/api/videos/{id}/share"])

    def test_two_apis_used_spellings_of_one_endpoint_append_once(self):
        contract = _build_contract(_drafts(
            ["POST /api/videos/{}/like", "POST /api/videos/{video_id}/like"]))
        self.assertEqual(len(_auto(contract)), 1, _auto(contract))


if __name__ == "__main__":
    unittest.main()
