r"""#664: #71's escalation counter lived in memory, so it fired 4 times in 4928 rejections.

#71 (r75/r76) exists to break a real loop: the verifier authors a chain step against an endpoint
the contract never defined, gets "endpoints NOT registered", and re-submits. Its fix counts
rejects PER ENDPOINT across chain names and escalates the guidance from the second one — the
reasoning is right and its unit tests pass.

They pass because they hold ONE `RegistryHub` instance across both calls. The counter was
`self._chain_reject_endpoint_counts`, an in-memory attribute, while every other fact this hub
holds is a JsonStore on disk. Across a process boundary or a re-spawned lane it resets to zero.

Measured over the 249 run logs:

    4928 chain rejections across 132 runs      4 escalations   (0.08%)
    median 28 rejections per run, max 126 (r98, PUT /api/profiles/{})
    pre-#71 median 26/run   post-#71 median 30/run   — no improvement, which is what an
                                                       inert fix looks like

And the rejections themselves are CORRECT: the registry holds only GET and POST /api/profiles,
so `PUT /api/profiles/{id}` genuinely does not exist. The defect is not the refusal, it is that
the guidance written to stop the retry loop was never reaching the retrier.

Proven directly before and after: one instance escalates on the 2nd reject either way; a FRESH
instance per reject escalated never before this change and from the 2nd after it.
"""
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub

_HALLUCINATED = [{"method": "PUT", "path": "/api/profiles/{id}", "body": {"name": "x"}}]
_REAL = [{"method": "GET", "path": "/api/profiles"}]


def _hub(d):
    rh = RegistryHub(Path(d))
    for m, p in (("POST", "/auth/register"), ("POST", "/auth/login"),
                 ("GET", "/api/profiles"), ("POST", "/api/profiles")):
        rh.register_endpoint(m, p, status="implemented")
    return rh


def _escalated(res):
    return "been rejected" in str((res or {}).get("error") or "")


# --- the defect ---------------------------------------------------------------------------------

def test_a_fresh_instance_per_reject_now_escalates(tmp_path):
    """The production shape: the hub is rebuilt between the verifier's attempts."""
    got = [_escalated(_hub(tmp_path).register_verification_chain(f"c{i}", _HALLUCINATED))
           for i in range(3)]
    assert got == [False, True, True]


def test_the_count_is_on_disk_where_every_other_hub_fact_lives(tmp_path):
    _hub(tmp_path).register_verification_chain("c", _HALLUCINATED)
    assert (Path(tmp_path) / "registryhub_chain_reject_counts.json").is_file()


def test_the_escalation_reports_the_accumulated_count(tmp_path):
    for i in range(4):
        res = _hub(tmp_path).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert "rejected 4 times" in str(res["error"])


# --- #71's semantics are preserved exactly --------------------------------------------------------

def test_the_first_reject_is_still_plain(tmp_path):
    assert not _escalated(_hub(tmp_path).register_verification_chain("c", _HALLUCINATED))


def test_it_still_counts_per_ENDPOINT_across_varying_chain_names(tmp_path):
    """r76's finding: the verifier renames the chain each time, so name-keying never fired."""
    _hub(tmp_path).register_verification_chain("alpha", _HALLUCINATED)
    res = _hub(tmp_path).register_verification_chain("completely_different", _HALLUCINATED)
    assert _escalated(res)


def test_a_different_missing_endpoint_starts_its_own_count(tmp_path):
    _hub(tmp_path).register_verification_chain("a", _HALLUCINATED)
    other = [{"method": "PUT", "path": "/api/my-list/{id}", "body": {}}]
    assert not _escalated(_hub(tmp_path).register_verification_chain("b", other))


def test_registering_the_endpoint_ends_the_escalation(tmp_path):
    """Self-invalidating: once it exists it leaves `unregistered`, so nothing escalates."""
    for i in range(3):
        _hub(tmp_path).register_verification_chain(f"c{i}", _HALLUCINATED)
    rh = _hub(tmp_path)
    rh.register_endpoint("PUT", "/api/profiles/{id}", status="implemented")
    res = rh.register_verification_chain("now_valid", _HALLUCINATED)
    assert not _escalated(res)


def test_a_valid_chain_is_unaffected(tmp_path):
    res = _hub(tmp_path).register_verification_chain("good", _REAL)
    assert "error" not in res or not _escalated(res)


def test_the_guidance_still_tells_the_agent_what_to_do(tmp_path):
    for i in range(2):
        res = _hub(tmp_path).register_verification_chain(f"c{i}", _HALLUCINATED)
    err = str(res["error"])
    assert "DROP those steps" in err
    assert "ask the backend lane to implement" in err


# --- it must never cost the reject -----------------------------------------------------------

def test_a_broken_store_still_produces_a_plain_reject(tmp_path, monkeypatch):
    """Best-effort is the contract #71 set: bookkeeping faults fall through."""
    rh = _hub(tmp_path)

    class _Boom:
        def value(self):
            raise RuntimeError("disk gone")

        def set(self, *a, **k):
            raise RuntimeError("disk gone")

    monkeypatch.setattr(rh, "_chain_rejects", _Boom())
    res = rh.register_verification_chain("c", _HALLUCINATED)
    assert "NOT registered in RegistryHub" in str(res["error"])


def test_the_in_memory_fallback_still_works_when_the_store_is_dead(tmp_path, monkeypatch):
    rh = _hub(tmp_path)

    class _Boom:
        def value(self):
            raise RuntimeError("x")

        def set(self, *a, **k):
            raise RuntimeError("x")

    monkeypatch.setattr(rh, "_chain_rejects", _Boom())
    rh.register_verification_chain("a", _HALLUCINATED)
    assert _escalated(rh.register_verification_chain("b", _HALLUCINATED))


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    flat = " ".join(inspect.getsource(rh).replace("#", " ").split())
    assert "4928 chain rejections" in flat and "4 escalations" in flat
    assert "median 30 vs 26" in flat


def test_why_it_was_inert_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    flat = " ".join(inspect.getsource(rh).split())
    assert "a fresh instance per reject never escalates" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
