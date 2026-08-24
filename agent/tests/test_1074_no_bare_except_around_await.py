"""#1074 — a bare `except:` around an `await` swallows cancellation.

`CancelledError` is a BaseException, so `except:` catches it while
`except Exception:` does not. A cancellation is delivered ONCE — swallow it and
the request is lost, and the coroutine runs on as if it had merely failed.

Swept the package: of 11 bare handlers, exactly one wrapped an `await` —
BrowserClickTool's retry path, around
`page.evaluate("...scrollIntoView...")`. Cancelling that tool mid-scroll (a step
timeout, a lane being torn down) was caught there and dropped, and the step
carried on to its click.

The other ten are around synchronous bodies, where CancelledError cannot be
delivered because there is no await point inside — `json.loads`, a path
normalisation, a line count. They are poor style and not this bug; changing them
would be churn, so this test draws the line exactly where the hazard is.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bare_handlers_wrapping_await():
    out = []
    for f in LLM_DIR.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            if not any(h.type is None for h in n.handlers):
                continue
            body = ast.Module(body=n.body, type_ignores=[])
            if any(isinstance(x, ast.Await) for x in ast.walk(body)):
                out.append(f"{f.relative_to(LLM_DIR)}:{n.lineno}")
    return sorted(out)


class CancellationMustPropagate(unittest.TestCase):

    def test_no_bare_handler_wraps_an_await(self):
        found = _bare_handlers_wrapping_await()
        self.assertEqual(found, [], (
            "a bare `except:` around an `await` catches CancelledError and loses the "
            f"cancellation — use `except Exception:`: {found}"))

    def test_the_locator_is_not_vacuous(self):
        """A ratchet that matches nothing passes forever."""
        src = "async def f():\n    try:\n        await g()\n    except:\n        pass\n"
        tree = ast.parse(src)
        hits = [n for n in ast.walk(tree)
                if isinstance(n, ast.Try) and any(h.type is None for h in n.handlers)
                and any(isinstance(x, ast.Await)
                        for x in ast.walk(ast.Module(body=n.body, type_ignores=[])))]
        self.assertEqual(len(hits), 1, "the detector must see the shape it forbids")


class TheFixedSiteStillSwallowsOrdinaryFailure(unittest.TestCase):
    """The scroll is best-effort; only BaseException should now get through."""

    def test_the_handler_is_except_exception(self):
        p = LLM_DIR / "tools" / "browser" / "interaction.py"
        src = p.read_text(encoding="utf-8")
        i = src.index("scrollIntoView")
        j = src.find("\n        #", i)
        window = src[i:j if j != -1 else i + 1200]
        self.assertIn("except Exception:", window)
        self.assertIn("#1074", window)


if __name__ == "__main__":
    unittest.main()
