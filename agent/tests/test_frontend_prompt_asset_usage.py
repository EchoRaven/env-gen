"""FIX #185 — the frontend prompt's REAL-ASSETS guidance covered only icon/logo/image usage and
the typography line said "use ONE font family" generically. So even after #183/#184 staged real
fonts + videos into design_system.assets[], the lane wasn't guided to USE them (@font-face the
fonts, <video> the media) → it would fall back to generic fonts + placeholder video, wasting the
staging. This extends the prompt to guide real font (@font-face) + video/audio usage. Guard test:
the guidance is present + the template still renders. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
          / "frontend_agent.j2")


def test_prompt_guides_real_font_usage():
    text = PROMPT.read_text(encoding="utf-8").lower()
    assert "@font-face" in text
    assert "type:font" in text
    # must say don't fall back to a generic font when brand fonts are staged
    assert "generic" in text and "font" in text


def test_prompt_guides_real_video_usage():
    text = PROMPT.read_text(encoding="utf-8").lower()
    assert "type:video" in text
    assert "<video" in text


def test_frontend_prompt_template_still_renders():
    # the additive edit must not break Jinja parsing.
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(PROMPT.parent)))
    assert env.get_template("frontend_agent.j2") is not None
