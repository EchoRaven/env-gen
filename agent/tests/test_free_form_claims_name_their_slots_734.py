r"""#734: an object advertised as free-form must not be one the framework reads keys of.

Twice now the framework has read specific keys of a parameter it declared unstructured, and both
times the repair was a normaliser rather than a disclosure:

    schema        declared {"type": "object"}, no properties. The model guessed `query` for query
                  parameters; every consumer reads `request`. Invisible for a run, six catalogue
                  routes shipped unfiltered. Patched by folding one synonym (#730), then fixed
                  properly by publishing the slots (#732).
    evidence      described as "Free-form mapping with check output …" while the framework reads
                  summary / execution_mode / metadata.check / metadata.flow. #193's comment
                  records the cost: ui_flow records "INVISIBLE to _has_passing_ui_evidence /
                  flow_coverage / the retry decider / remediation-task creation, and the UI gates
                  cleared only via the functionally_validated waiver". Patched by normalising two
                  spellings; fixed by publishing (#733).

The user's objection is why this is a guard and not a third patch: agents inventing words is
normal, discovering each invention one run at a time does not converge, and a synonym table built
from one corpus cannot help the next app. What DOES generalise is the rule that the framework
must publish the slots it depends on, at the point of the call, since those slot names belong to
the framework rather than to any app's domain.

The invariant: a parameter whose description CLAIMS free-form must not also name required
structure — if the framework reads keys, say so instead of advertising freedom. Zero violations
today, which is the point: it is satisfied now and fires on the next one.
"""
import ast
import re
from pathlib import Path

import pytest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "tools"
_FREE = re.compile(r"free-?form|arbitrary|any (?:keys|shape|mapping)", re.I)


def _object_params():
    """(tool, param, spec) for every object-typed tool parameter we can parse."""
    out = []
    for f in TOOLS_DIR.rglob("*.py"):
        s = f.read_text(errors="ignore")
        # `[a-z_]+` silently skipped every tool whose name carries a digit — browser_check_a11y
        # and browser_a11y_tree are real. A sweep with an invisible blind spot reports a clean
        # zero for the wrong reason, which is the failure mode this whole file is about.
        for m in re.finditer(r'NAME = "([a-z0-9_]+)"', s):
            j = s.find("PARAMETERS = ", m.end())
            if j < 0 or j - m.end() > 1500:
                continue
            k = s.find("\n    async def", j)
            if k < 0:
                k = s.find("\n    def", j)
            try:
                d = ast.literal_eval(s[j + len("PARAMETERS = "):k].strip().rstrip(","))
            except Exception:
                continue
            for pn, spec in (d.get("properties") or {}).items():
                if isinstance(spec, dict) and spec.get("type") == "object":
                    out.append((m.group(1), pn, spec))
    return out


# --- the sweep works at all ----------------------------------------------------------------------

def test_the_sweep_finds_object_parameters():
    params = _object_params()
    assert len(params) >= 10, f"only parsed {len(params)} — has PARAMETERS' shape changed?"


def test_the_sweep_sees_tools_whose_names_contain_digits():
    """browser_check_a11y and browser_a11y_tree exist. The first version's `[a-z_]+` skipped
    them, so a clean result would have been clean for the wrong reason."""
    import re as _re
    names = set()
    for f in TOOLS_DIR.rglob("*.py"):
        names |= set(_re.findall(r'NAME = "([a-z0-9_]+)"', f.read_text(errors="ignore")))
    assert "browser_check_a11y" in names


def test_it_sees_the_two_that_motivated_it():
    names = {(t, p) for t, p, _ in _object_params()}
    assert ("registryhub_register_endpoint", "schema") in names
    assert ("codehub_record_check", "evidence") in names


# --- the invariant ---------------------------------------------------------------------------------

def test_no_parameter_claims_free_form_without_naming_its_slots():
    bad = []
    for tool, pn, spec in _object_params():
        desc = str(spec.get("description") or "")
        if _FREE.search(desc) and "`" not in desc:
            bad.append(f"{tool}.{pn}")
    assert not bad, (
        "these advertise an unstructured object while the framework may read keys of it — the "
        "shape that cost #730 a run and #193 an outage. Name the slots the framework reads, or "
        "drop the free-form claim: " + ", ".join(bad))


def test_the_two_fixed_ones_now_name_slots():
    for tool, pn, expect in (("registryhub_register_endpoint", "schema", "request"),
                             ("codehub_record_check", "evidence", "metadata")):
        spec = next(s for t, p, s in _object_params() if (t, p) == (tool, pn))
        text = str(spec.get("description") or "") + str(spec.get("properties") or "")
        assert expect in text, f"{tool}.{pn} no longer names {expect}"


def test_schema_publishes_its_slots_as_properties():
    spec = next(s for t, p, s in _object_params()
                if (t, p) == ("registryhub_register_endpoint", "schema"))
    assert set(spec.get("properties") or {}) >= {"request", "response_key"}


# --- the guard's own limits, stated ------------------------------------------------------------------

def test_the_free_form_pattern_is_narrow_on_purpose():
    """It matches a CLAIM of freedom, not opacity. A bare {"type": "object"} with no description
    is not flagged — most such params are genuinely free metadata, and flagging all 16 of them
    would cry wolf on correct decisions (#726's lesson)."""
    assert _FREE.search("Free-form mapping with check output")
    assert _FREE.search("arbitrary keys")
    assert not _FREE.search("Check output. These are the ones the framework READS")


def test_the_guard_is_not_vacuous(tmp_path, monkeypatch):
    """Verified by planting a violation, because I built this one and only THEN checked whether
    it could fire — it could not. The first sweep's `[a-z_]+` skipped any tool name with a digit,
    so the probe went unseen and the guard reported a clean pass. A guard whose non-vacuity is
    assumed is worth less than none."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        'class _P:\n'
        '    NAME = "probe_freeform_734"\n'
        '    PARAMETERS = {"type": "object", "properties": {\n'
        '        "blob": {"type": "object", "description": "Free-form mapping, anything."}}}\n'
        '    async def _run(self): pass\n', encoding="utf-8")
    monkeypatch.setattr(
        __import__(__name__.split(".")[-1] if "." in __name__ else __name__),
        "TOOLS_DIR", tmp_path, raising=False)
    bad = [f"{t}.{p}" for t, p, spec in _object_params()
           if _FREE.search(str(spec.get("description") or ""))
           and "`" not in str(spec.get("description") or "")]
    assert bad == ["probe_freeform_734.blob"], bad


def test_a_backtick_is_the_slot_marker_and_that_is_a_proxy():
    """Detecting "names a slot" by backticks is a proxy, not a parse. It is chosen because every
    published slot in this tree is written `like_this`, and a stricter check would need each
    tool to declare its read set — worth doing if a third instance appears."""
    assert "`" in "reads `summary` and `metadata`"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
