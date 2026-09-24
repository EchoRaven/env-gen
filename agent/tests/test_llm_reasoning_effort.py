import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # agent/
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils.llm import build_openai_request_params  # noqa: E402


def test_gpt5_gets_reasoning_effort():
    p = build_openai_request_params(model_name="gpt-5.4", messages=[], reasoning_effort="high")
    assert p.get("reasoning_effort") == "high"


def test_non_gpt5_omits_reasoning_effort():
    p = build_openai_request_params(model_name="gpt-4.1", messages=[], reasoning_effort="high")
    assert "reasoning_effort" not in p


def test_gpt5_without_effort_omits_param():
    p = build_openai_request_params(model_name="gpt-5.4", messages=[], reasoning_effort=None)
    assert "reasoning_effort" not in p


def test_o3_omits_reasoning_effort():
    # Gate is gpt-5-only (the model we run); o-series is intentionally not widened here.
    p = build_openai_request_params(model_name="o3", messages=[], reasoning_effort="high")
    assert "reasoning_effort" not in p
