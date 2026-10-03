r"""#1203b3: the framework hands the lane the identity its own rule forbids rendering.

#1202ri told the design ANALYST that a value belonging to whoever was signed in when the
reference screenshot was taken is DATA, not chrome, and belongs in `data_slots`, never `copy`.
#1202rj added the served-file backstop and its comment says why: "a prompt rule is not
enforcement".

NEITHER governs the stage that WRITES the text. `_DECOMPOSE_PROMPT` -- one vision call per
reference screen, before the analyst and before any lane -- asks for "notable state the data
shows", and the data in the screenshot is the operator's own account. The resulting `state`
string is interpolated verbatim into the analyst's compact skeleton
(`design_prep._skeleton_for_prompt_816`) AND into the lane's "MEASURED SPEC" prompt block
(`visual_fidelity`), so the framework feeds forward the very value it will later block on.

MEASURED, 183 runs with a design/ tree, 100 affected:
    component_specs/*.json   state 126x / 86 runs,  role 16x / 14 runs,  name 0x
    design_system.json       state 123x / 94 runs,  copy 26x / 26 runs,  route 11x / 6 runs
`copy` is the field #1202ri governs EXPLICITLY and it carries the handle in 26 runs. One spec
holds a whole address, `haibot2@illinois.edu`.

r144 is the end-to-end proof: the spec said "Own profile view for user haibotong7", the lane
rendered it, #1202rj declined delivery, and frontend carried THREE in_progress tasks about a
page whose source it had already cleaned -- while nothing named the spec that re-injects it.

Over the whole corpus the scrub cleans 142 of 142 affected components and touches 0 of the
other 32,581.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.material_prep as MP  # noqa: E402

_SLOT = MP._IDENTITY_SLOT_1203B3


def _ident(monkeypatch, tokens=("haibotong", "EchoRaven", "haibot2")):
    """Patch the RESOLVER and clear the per-process cache, so each test states its own
    environment. Patching only the resolver would be read through a cache another test filled."""
    import multi_agent.runtime.deliverability as D
    monkeypatch.setattr(D, "_operator_identity_1202rj", lambda: list(tokens), raising=True)
    monkeypatch.setattr(MP, "_OPERATOR_TOKENS_1203B3", None, raising=False)


def test_the_handle_leaves_the_state_field(monkeypatch):
    """★ The exact string r144 shipped."""
    _ident(monkeypatch)
    c = [{"name": "profile_header",
          "state": "Own profile view for user haibotong7 with no bio and zero activity counts."}]
    hits = MP._scrub_operator_identity_1203b3(c)
    assert "haibotong" not in c[0]["state"], c[0]["state"]
    assert hits == ["profile_header.state: haibotong7"], hits


def test_the_shape_the_field_exists_to_describe_survives(monkeypatch):
    """★ Not a silent strip: `state` is there to say what state the screen is in, and that
    sentence still says it. A scrub that deleted the clause would trade a leak for a blind spot."""
    _ident(monkeypatch)
    c = [{"name": "profile_header",
          "state": "Own profile view for user haibotong7 with no bio and zero activity counts."}]
    MP._scrub_operator_identity_1203b3(c)
    assert c[0]["state"] == (
        "Own profile view for user %s with no bio and zero activity counts." % _SLOT)


def test_a_trailing_digit_goes_with_it(monkeypatch):
    """r127's leak was `haibotong7` -- the OS user with a digit on the end. A scrub that
    stopped at the token would leave a bare `7` where a handle had been."""
    _ident(monkeypatch)
    c = [{"name": "t", "state": "shows 'haibotong7'"}]
    MP._scrub_operator_identity_1203b3(c)
    assert c[0]["state"] == "shows '%s'" % _SLOT, c[0]["state"]


def test_a_whole_address_goes_with_it(monkeypatch):
    """Measured in the corpus. The local part is the token; the domain must not dangle."""
    _ident(monkeypatch)
    c = [{"name": "t", "state": "Contains the value 'haibot2@illinois.edu'."}]
    MP._scrub_operator_identity_1203b3(c)
    assert c[0]["state"] == "Contains the value '%s'." % _SLOT, c[0]["state"]


def test_every_occurrence_in_one_string(monkeypatch):
    """A real spec row: `'haibotong7 | haibotong7'`. Replacing only the first is the shape of
    a loop that advances past its own substitution incorrectly."""
    _ident(monkeypatch)
    c = [{"name": "title_bar", "state": "'haibotong7 | haibotong7'"}]
    hits = MP._scrub_operator_identity_1203b3(c)
    assert c[0]["state"] == "'%s | %s'" % (_SLOT, _SLOT)
    assert len(hits) == 2, hits


def test_role_is_scrubbed_too(monkeypatch):
    """16 occurrences across 14 runs are in `role`, which reaches the same two prompts."""
    _ident(monkeypatch)
    c = [{"name": "h", "role": "Username heading 'haibotong7' + handle"}]
    MP._scrub_operator_identity_1203b3(c)
    assert "haibotong" not in c[0]["role"]


def test_the_analyst_fields_are_scrubbed_when_asked(monkeypatch):
    """`copy` (26 runs) and `build_notes` (2) are the analyst's, written one stage later, and
    `data_slots` is a LIST -- #1202ri's own destination, which must not be allowed to carry
    the value it exists to replace."""
    _ident(monkeypatch)
    c = [{"name": "h", "copy": "haibotong7", "build_notes": "the handle haibotong7 sits here",
          "data_slots": ["signed-in user handle", "haibotong7"]}]
    MP._scrub_operator_identity_1203b3(c, extra=("copy", "build_notes", "data_slots"))
    assert c[0]["copy"] == _SLOT
    assert "haibotong" not in c[0]["build_notes"]
    assert c[0]["data_slots"] == ["signed-in user handle", _SLOT], c[0]["data_slots"]


def test_the_component_id_is_never_rewritten(monkeypatch):
    """★ `name` is the key BOTH the analyst merge (#815, a miss is a silent `continue`) and
    the lane join on. The corpus shows it never carries the identity, so touching it could
    only break the join."""
    _ident(monkeypatch)
    c = [{"name": "haibotong_header", "state": "clean"}]
    MP._scrub_operator_identity_1203b3(c)
    assert c[0]["name"] == "haibotong_header"


def test_a_seeded_persona_survives(monkeypatch):
    """★ #1202rj's stated principle, which this inherits: narrow to THIS build account, never
    "names that look personal". A seeded persona is supposed to have a name."""
    _ident(monkeypatch)
    c = [{"name": "card", "state": "shows creator 'maya_rivers' with 1.2M followers"}]
    assert MP._scrub_operator_identity_1203b3(c) == []
    assert c[0]["state"] == "shows creator 'maya_rivers' with 1.2M followers"


def test_a_clean_spec_is_untouched(monkeypatch):
    """0 of the corpus's other 32,581 components change."""
    _ident(monkeypatch)
    c = [{"name": "feed", "role": "vertical video feed", "state": "mostly UNREAD -> blue-dominant"}]
    import copy as _c
    before = _c.deepcopy(c)
    assert MP._scrub_operator_identity_1203b3(c) == []
    assert c == before


def test_an_unresolvable_identity_changes_nothing(monkeypatch):
    """`_operator_identity_1202rj` returns [] when the build environment says nothing. The
    scrub must then be a no-op rather than guess."""
    _ident(monkeypatch, tokens=())
    c = [{"name": "t", "state": "shows 'haibotong7'"}]
    assert MP._scrub_operator_identity_1203b3(c) == []
    assert c[0]["state"] == "shows 'haibotong7'"


def test_a_short_token_is_ignored(monkeypatch):
    """The resolver's own floor is 4 characters; a 3-character OS user would match half the
    English language."""
    _ident(monkeypatch, tokens=("abc",))
    c = [{"name": "t", "state": "the abcdef row"}]
    assert MP._scrub_operator_identity_1203b3(c) == []


def test_a_resolver_fault_is_not_a_crash(monkeypatch):
    """This runs before any lane; an exception here costs the whole visual pipeline."""
    import multi_agent.runtime.deliverability as D

    def _boom():
        raise RuntimeError("git gone")
    monkeypatch.setattr(D, "_operator_identity_1202rj", _boom, raising=True)
    monkeypatch.setattr(MP, "_OPERATOR_TOKENS_1203B3", None, raising=False)
    c = [{"name": "t", "state": "shows 'haibotong7'"}]
    assert MP._scrub_operator_identity_1203b3(c) == []


def test_non_dict_rows_do_not_break_it(monkeypatch):
    _ident(monkeypatch)
    c = ["not a dict", {"name": "t", "state": "haibotong7"}, None]
    MP._scrub_operator_identity_1203b3(c)
    assert c[1]["state"] == _SLOT


def test_the_decompose_prompt_states_the_rule():
    """★ Enforcement is the backstop; the prompt is where the value stops being produced.
    #1202ri's wording, in the field that actually asks for the data."""
    p = MP._DECOMPOSE_PROMPT
    assert "signed in" in p, "the rule does not say whose values these are"
    # `data_slots` is the ANALYST's schema field and does not exist at this stage, so the rule
    # has to say the same thing in this stage's own terms: describe the slot, not its content.
    assert "Name the slot" in p and "never what you can read" in p, p[-700:]
    assert "accident of capture" in p, "nothing says WHY the values must not be written"
    for word in ("handle", "display name", "email", "count", "timestamp", "caption"):
        assert word in p, "the rule names no concrete example: %r" % word


def test_the_writer_calls_the_scrub():
    """★ I have tested a helper and not its caller repeatedly. Three properties: the call
    exists inside `decompose_reference`, it is fed the list that is RETURNED to the caller,
    and it is not behind a branch that a normal screen can skip."""
    import ast
    import inspect

    src = inspect.getsource(MP.decompose_reference)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_scrub_operator_identity_1203b3"]
    assert len(calls) == 1, "called %d time(s) in decompose_reference" % len(calls)

    # the argument is the same name the return statement carries
    arg = calls[0].args[0] if calls[0].args else None
    assert isinstance(arg, ast.Name), ast.dump(calls[0])[:160]
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    returned = set()
    for r in returns:
        for n in ast.walk(r):
            if isinstance(n, ast.Name):
                returned.add(n.id)
    assert arg.id in returned, "%r is scrubbed but never returned (returns %s)" % (
        arg.id, sorted(returned))

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            raise AssertionError("the scrub sits behind a branch: %s" % ast.dump(node.test)[:140])


def test_what_was_scrubbed_is_reported_to_the_caller():
    """★ The user's standing rule: no fallback that hides a failure. The vision model named a
    value it was asked not to, and `decompose_reference`'s result must carry that fact rather
    than quietly fixing it."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(MP.decompose_reference).lstrip())
    keys = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys |= {k.value for k in n.keys if isinstance(k, ast.Constant)}
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            keys.add(n.slice.value)
    assert any("1203b3" in str(k) for k in keys), (
        "the result names no scrub key, so a run cannot be asked whether it happened: %s"
        % sorted(str(k) for k in keys))


def test_the_analyst_fields_are_in_the_join_scrub_list():
    """★ `copy` is the field #1202ri governs EXPLICITLY and it carries the identity in 26 runs.
    The default key set is `role`/`state` -- the vision model's fields -- so the analyst's own
    three only get scrubbed if this call names them. Checked as the ARGUMENT, because an import
    of the helper satisfies a substring search while scrubbing nothing (my own mutation showed
    exactly that)."""
    import ast
    import inspect
    import multi_agent.runtime.design_prep as DP

    tree = ast.parse(inspect.getsource(DP))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_scrub_operator_identity_1203b3"]
    assert calls, "the analyst's own fields reach design_system.json unscrubbed"
    extra = [k for k in calls[0].keywords if k.arg == "extra"]
    assert extra, "the call passes no `extra`, so copy/build_notes/data_slots are skipped"
    named = {e.value for e in extra[0].value.elts if isinstance(e, ast.Constant)}
    assert {"copy", "build_notes", "data_slots"} <= named, named


def test_the_sink_does_not_rebuild_the_record_away():
    """★ #1202vp's shape, one module over: `precompute_component_specs` builds `payload` by
    hand from three keys, so a key added to what `decompose_reference` RETURNS is dropped at
    the write unless it is carried. Without this the scrub happens and no artifact says so."""
    import ast
    import inspect
    import multi_agent.runtime.reference_materials as RM

    tree = ast.parse(inspect.getsource(RM.precompute_component_specs).lstrip())
    subs = {n.slice.value for n in ast.walk(tree)
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)}
    assert "identity_scrubbed_1203b3" in subs, (
        "the payload never gains the key, so the record dies at the write: %s" % sorted(subs))
    reads = {n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "get"
             and n.args and isinstance(n.args[0], ast.Constant)}
    assert "identity_scrubbed_1203b3" in reads, sorted(reads)


def test_the_operator_is_told_it_is_not_an_app_defect():
    """r144's debugger shape: a correctly-diagnosed finding filed against someone who cannot
    fix it. The reference was captured from the build account — nothing about the generated
    app is wrong, so the log must say so (same reasoning as #1202z6)."""
    import inspect
    import multi_agent.runtime.reference_materials as RM

    src = inspect.getsource(RM.precompute_component_specs)
    assert "1203b3" in src
    assert "not a defect of the app" in src, src[-900:]


def test_the_analyst_join_is_fed_the_component_being_merged():
    """★ Tested the helper, not the caller — repeatedly. The merge loop rebinds `c` per
    component, so the scrub must take THAT name, inside the loop, not the screen or a copy."""
    import ast
    import inspect
    import multi_agent.runtime.design_prep as DP

    src = inspect.getsource(DP)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_scrub_operator_identity_1203b3"]
    assert len(calls) == 1, "called %d time(s) in design_prep" % len(calls)
    arg = calls[0].args[0]
    assert isinstance(arg, ast.List) and len(arg.elts) == 1, ast.dump(arg)[:140]
    assert getattr(arg.elts[0], "id", "") == "c", ast.dump(arg)[:140]
    # and it is inside the per-component loop, after the field copy
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and any(x is calls[0] for x in ast.walk(n))]
    assert loops, "the scrub is outside every loop — it would run once per screen"


def test_the_identity_is_resolved_once_per_process(monkeypatch):
    """★ `_operator_identity_1202rj` shells out to `git config` TWICE per call, and the analyst
    join calls the scrub once per COMPONENT — a few hundred times per run. The build account
    cannot change inside one process, so this must be resolved once."""
    import multi_agent.runtime.deliverability as D
    calls = []

    def _count():
        calls.append(1)
        return ["haibotong"]
    monkeypatch.setattr(D, "_operator_identity_1202rj", _count, raising=True)
    monkeypatch.setattr(MP, "_OPERATOR_TOKENS_1203B3", None, raising=False)
    for _ in range(50):
        MP._scrub_operator_identity_1203b3([{"name": "t", "state": "haibotong7"}])
    assert len(calls) == 1, "resolved %d times for 50 components" % len(calls)


def test_an_empty_resolution_is_not_re_probed(monkeypatch):
    """The cache holds the LIST, not a truthiness sentinel: an environment that legitimately
    resolves to [] must not pay a subprocess pair on every component either."""
    import multi_agent.runtime.deliverability as D
    calls = []

    def _empty():
        calls.append(1)
        return []
    monkeypatch.setattr(D, "_operator_identity_1202rj", _empty, raising=True)
    monkeypatch.setattr(MP, "_OPERATOR_TOKENS_1203B3", None, raising=False)
    for _ in range(20):
        MP._scrub_operator_identity_1203b3([{"name": "t", "state": "haibotong7"}])
    assert len(calls) == 1, "resolved %d times" % len(calls)
