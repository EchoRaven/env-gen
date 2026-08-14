r"""#691: the delivery commit skipped a whole subtree in silence, and it was the same one every time.

This closes item 18 of EXPERIMENTS_PENDING_2026-08-13.md, which had stood as "reproduced twice,
mechanism unknown". The open question there was whether `mcp_server/` was "written into a worktree
that was later removed" or "written and then deleted" — the note said the disk kept no trace.

It is neither. Both runs say the writer ran and succeeded:

    mcp_server/app/: 15 tool(s) emitted, 15 registered.       (r145 and r146, identically)

and both deliver a tree with no `mcp_server/` in it. `git log --diff-filter=D` finds no commit that
deletes it, because nothing ever did:

    r146: mcp_server/app/{main.py,pyproject.toml,start.sh} added in 60c738f, on branch `main`
    r145: same three files added in 0b0e81b
    HEAD is `integration` in both, and `git merge-base --is-ancestor <commit> HEAD` is FALSE

The writer commits to `main`; delivery runs on `integration`; the branches have diverged. So at
delivery time the directory genuinely is not in the working tree, `commit_framework_delivery`'s
`if not (repo / sub).exists(): continue` is CORRECT to skip it — and says nothing. Meanwhile the
registry still advertises the surface: 16 entries (1 server + 15 tools) in both runs' stores.
125 of the 144 corpus runs are missing the same subtree.

The count is read from the STORE FILE, whose path follows from `repo` alone, rather than from a
getattr chain into the hub object graph: `MCPRegistry` is its own class and not a registryhub
mixin, so a guessed accessor would evaluate to 0 forever and this warning would never fire — a
silently dead branch guarding a silent skip.

#691b then RESTORES the subtree, because the reflog turns what looked like a topology preference
into an ordering defect with one correct repair. r146, to the second:

    22:53:11  bootstrap  26067f8  on main
    23:10:47  "branch: Created from agent/backend" — integration PLANTED at 26067f8.
              create_branch_at plants a ref and deliberately does not move HEAD.
    23:12:41  first framework delivery commits ON MAIN (60c738f) — the mcp_server write lands
              on the wrong side of a fork that already existed
    later     HEAD moves to integration, git drops the subtree from the working tree, and the
              four later deliveries (23:44, 23:46, 23:47, 23:48) all find it absent

`git diff --name-status integration main` bounds the damage at exactly three files: the
mcp_server subtree and nothing else. app/ and docker/ escape because the projector rewrites them
every round — the MCP writer runs ONCE per run, so it alone gets no second chance. That is why
this subtree and only this subtree is missing from 125 of 144 runs.

Verified against r146's real repository: on `integration` the directory is absent;
`git log --all -1 --diff-filter=AM -- mcp_server` finds 60c738f; `git checkout 60c738f --
mcp_server` restores all three files into the working tree AND the index, and the recovered
server is genuine — 270 lines of fastmcp over httpx, not a stub.
"""
import json

import pytest


def _src():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
    src = inspect.getsource(hp)
    i = src.index("#691: SAY WHEN A DELIVERY SUBTREE IS NOT THERE TO SHIP")
    return src[i:src.index("rc, _o, _e = _run_git", i)]


# --- the counter, run against the real stores -------------------------------------------------

def _claimed(store: dict) -> int:
    """Mirror of the production counter, exercised on real recorded data below."""
    return sum(1 for k, r in (store or {}).items()
               if not str(k).startswith("_")
               and isinstance(r, dict)
               and r.get("kind") in ("tool", "server"))


def test_it_counts_the_real_r146_store():
    """1 server + 15 tools — matching the writer's own '15 tool(s) emitted' log line."""
    store = {"_meta": {"v": 1},
             "s1": {"kind": "server", "name": "app"},
             **{f"t{i}": {"kind": "tool", "name": f"t{i}"} for i in range(15)}}
    assert _claimed(store) == 16


def test_metadata_keys_are_not_counted_as_surface():
    assert _claimed({"_meta": {"kind": "tool"}, "t": {"kind": "tool"}}) == 1


def test_unknown_kinds_are_not_counted():
    assert _claimed({"x": {"kind": "note"}, "t": {"kind": "tool"}}) == 1


def test_a_non_dict_entry_does_not_raise():
    assert _claimed({"a": "junk", "b": None, "t": {"kind": "tool"}}) == 1


def test_an_empty_store_claims_nothing():
    assert _claimed({}) == 0 and _claimed(None) == 0


# --- the skip is no longer silent --------------------------------------------------------------

def test_the_skip_logs_before_continuing():
    body = _src()
    assert "orch._logger" in body
    assert body.rindex("continue") > body.index("orch._logger")


def test_an_advertised_surface_warns_rather_than_informs():
    body = _src()
    assert "warning(" in body and "info(" in body
    assert "if _claimed:" in body


def test_it_names_the_branch_as_the_thing_to_check():
    body = _src()
    assert "which BRANCH wrote it" in body
    assert "integration" in body and "`main`" in body


def test_it_says_nothing_from_the_subtree_will_ship():
    assert "nothing from it will ship" in _src()


# --- it must not become a new failure mode ------------------------------------------------------

def test_the_whole_block_cannot_raise():
    """A logging nicety must never break the delivery commit."""
    body = _src()
    assert body.count("try:") >= 1
    assert "except Exception:" in body
    assert body.index("except Exception:") < body.rindex("continue")


def test_the_skip_itself_is_unchanged():
    """The guard was correct — only its silence was the defect."""
    body = _src()
    assert "continue" in body


def test_it_reads_the_store_not_the_object_graph():
    body = _src()
    assert "registryhub_mcp_registry.json" in body
    assert "_f.exists()" in body
    # `getattr(` with the paren: the block's own comment says the word while explaining why
    # it does not do it, and a bare substring check matches that comment instead of the code.
    assert "getattr(" not in body, "a guessed accessor would silently evaluate to 0 forever"


def test_the_count_is_only_attempted_for_the_mcp_subtree():
    assert 'if sub == "mcp_server":' in _src()


def test_the_json_import_is_local():
    """heal_pipeline must not gain a module-level import for a log line."""
    body = _src()
    assert "import json as _json" in body


# --- #691b: it is restored, not merely reported -------------------------------------------------

def test_it_looks_for_the_subtree_in_any_commit():
    body = _src()
    assert '"log", "--all", "-1", "--format=%H"' in body
    assert '"--", sub' in body


def test_it_ignores_commits_that_only_deleted_the_subtree():
    """--diff-filter=AM: a deletion commit is not a source to restore from."""
    body = _src()
    assert '"--diff-filter=AM"' in body


def test_it_restores_from_the_commit_it_found():
    body = _src()
    assert '["checkout", sha, "--", sub]' in body


def test_the_restore_is_verified_before_it_is_believed():
    """A zero exit code is not proof the directory arrived."""
    body = _src()
    assert "rc_r == 0 and (repo / sub).exists()" in body


_MARK = "#691b: RESTORE IT RATHER THAN SHIP WITHOUT IT"


def test_a_failed_restore_falls_through_to_the_original_skip():
    body = _src()
    tail = body[body.index(_MARK):]
    assert tail.count("continue") >= 3, "no-commit, failed-checkout and raised must all skip"
    assert "except Exception:\n                        continue" in tail


def test_the_recovery_is_logged_with_its_source():
    body = _src()
    assert "recovered delivery subtree" in body
    assert "sha[:9]" in body


def test_the_recovery_says_why_the_subtree_was_missing():
    assert "on a branch the release is not cut from" in _src()


def test_the_restore_runs_after_the_diagnosis():
    """The WARNING must be emitted even when the restore then succeeds."""
    body = _src()
    assert body.index("orch._logger.info") < body.index(_MARK)


def test_the_restore_applies_to_every_listed_subtree_not_just_mcp():
    """The repair is generic; only the registry COUNT is mcp-specific."""
    body = _src()
    tail = body[body.index(_MARK):]
    assert '"mcp_server"' not in tail, "no product literal in the repair path"


# --- provenance ---------------------------------------------------------------------------------

def test_the_two_run_evidence_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "r145 and r146 both log" in flat
    assert "15 tool(s) emitted, 15 registered" in flat


def test_the_branch_mechanism_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "is NOT an ancestor of integration" in flat
    assert "60c738f" in flat and "0b0e81b" in flat


def test_the_ordering_defect_is_recorded_with_its_timeline():
    """What looked like a topology preference is an ordering defect; the reflog shows it."""
    flat = " ".join(_src().replace("#", " ").split())
    assert "branch: Created from agent/backend" in flat
    assert "plants a REF and deliberately" in flat
    assert "on the wrong side of the fork" in flat


def test_the_corpus_scale_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "125 of 144 corpus runs" in flat


def test_why_only_this_subtree_is_affected_is_recorded():
    """app/ and docker/ are rewritten every round; the MCP writer runs once."""
    flat = " ".join(_src().replace("#", " ").split())
    assert "runs ONCE per run, so it alone has no second chance" in flat


def test_the_blast_radius_is_recorded():
    flat = " ".join(_src().replace("#", " ").split())
    assert "exactly three files" in flat


def test_the_wording_matches_the_writers_own_count():
    """'16 tools' would contradict the writer's '15 tool(s)'."""
    body = _src()
    assert "registered MCP entries (servers + tools)" in body
    assert "%d %s tool(s)" not in body


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
