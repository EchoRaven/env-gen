r"""#1202bs: #1197 demanded `name=` from React code that uses controlled inputs.

Found live in netflix-r34. The lane did exactly what #1202at's task tells it to do —

    import LoginForm from '../components/LoginPage';
    export default function LoginPage(){ return <LoginForm />; }

— with the component rendering ordinary controlled inputs:

    <input className="field" value={email}    onChange={e=>...} />
    <input className="field" type="password" value={password} onChange={...} />

#1197's bundle followed the import correctly (2 lines in, 213 out) and three of its four
signals passed: the page calls the auth endpoint, it submits, it persists a token. Only
`_INPUT_NAME_1197` failed, because `name=` is the HTML-form idiom and a controlled input
replaces it with a state binding. So a working, componentised login form was judged "not
drivable" and overwritten — eight times in r34 and climbing, twelve in r33, and the
framework's own docstring records r26 at 87 and r154 at 19.

Two of my own fixes were contradicting each other: #1202at tells the lane to
componentise, and this predicate refused to recognise the result.

Drivable now means what a test user needs: something it can find and change.
"""
import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import _INPUT_NAME_1197 as PAT  # noqa: E402


class ControlledInputIsDrivableTests(unittest.TestCase):
    def test_the_r34_component_is_drivable(self):
        self.assertTrue(PAT.search(
            '<input className="field" value={email} onChange={e=>setEmail(e.target.value)} />'))

    def test_either_attribute_order_works(self):
        """onChange first is just as common as value first."""
        self.assertTrue(PAT.search(
            '<input onChange={e=>setP(e.target.value)} value={password} type="password" />'))

    def test_the_html_form_idiom_still_counts(self):
        """`name=` was never wrong — it was only insufficient."""
        self.assertTrue(PAT.search('<input name="email" type="email" />'))

    def test_selector_targets_count(self):
        for attr in ('placeholder="Email"', 'aria-label="Email"', 'data-testid="email"'):
            with self.subTest(attr=attr):
                self.assertTrue(PAT.search(f'<input className="f" {attr} />'))

    def test_a_page_with_no_control_is_not_drivable(self):
        for src in ("", "export default function P(){return <div>hi</div>}",
                    '<form onSubmit={go}><button type="submit">Go</button></form>'):
            with self.subTest(src=src[:30]):
                self.assertFalse(PAT.search(src))

    def test_a_bare_input_is_not_drivable(self):
        """Nothing to target and nothing bound — the case the original guard was for."""
        self.assertFalse(PAT.search('<input className="field" />'))


if __name__ == "__main__":
    unittest.main()
