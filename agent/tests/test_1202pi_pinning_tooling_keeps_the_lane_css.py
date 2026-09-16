"""#1202pi: pinning the build tooling adds the Tailwind directives; it does not erase the lane's CSS.

`pin_frontend_build_tooling` replaced `src/index.css` with the three-line baseline whenever the file
lacked `@tailwind`. r121: 14,314 bytes of hand-written TikTok CSS became 59 bytes; the next visual
capture fell 0.44 -> 0.165 and recovered to 0.715 only after the lane restored it (19 wipes in 4 runs).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import pin_frontend_build_tooling  # noqa: E402


def _frontend(tmp_path, css):
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "main.jsx").write_text("import './index.css';\n")
    if css is not None:
        (fe / "src" / "index.css").write_text(css)
    return fe


def test_r121_the_lanes_stylesheet_survives(tmp_path):
    lane_css = ".fyp-rail { display: grid; gap: 12px; }\n.video-card { border-radius: 8px; }\n"
    fe = _frontend(tmp_path, lane_css)
    pin_frontend_build_tooling(fe)
    out = (fe / "src" / "index.css").read_text()
    assert "@tailwind base;" in out
    assert lane_css.strip() in out, out


def test_a_missing_stylesheet_gets_the_baseline(tmp_path):
    fe = _frontend(tmp_path, None)
    pin_frontend_build_tooling(fe)
    assert (fe / "src" / "index.css").read_text().startswith("@tailwind base;")


def test_a_stylesheet_that_already_has_the_directives_is_untouched(tmp_path):
    css = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n.x{color:red}\n"
    fe = _frontend(tmp_path, css)
    pin_frontend_build_tooling(fe)
    assert (fe / "src" / "index.css").read_text() == css
