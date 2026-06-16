"""Phase 4 attempt-5 FIX D: Monitor-layer *_call gate invariant (structural
with name-allowlist backstop).

R1 round-5 wording downgrade (attempt-6 HARDENING B)
====================================================

The monitor invariant detector is **hybrid, not purely structural**.
The detector uses both AST signals (verb-substring + hub-anchored
receiver chain, Path/os/shutil/subprocess module calls, SQL writes,
git ops, explicit attribute assignment on hub objects) AND a retained
name-allowlist (``HUB_MUTATOR_METHODS``) for known mutators. Two
shipped mutators continue to depend on the name-allowlist backstop
because their method names contain no verb substring AND their
receiver chain alone is not enough to classify them:

  * ``send_message_call`` — ``send_message`` does not match any verb
    in ``MUTATION_VERB_SUBSTRINGS`` (no create/update/set/etc.). The
    name-allowlist entry for ``send_message`` is what keeps it
    classified as a hub mutator.
  * ``add_task_to_plan_call`` — ``add_task_to_plan`` likewise carries
    no verb substring. The legacy ``HUB_MUTATOR_METHODS`` entry is
    what flags it.

Verb-free hub-method names like ``amend`` / ``purge`` / ``rename_page``
(hypothetical and/or future hub methods on WorkHub / CodeHub) would
NOT be flagged by the current detector and remain a residual
**denylist-by-omission** failure mode — the exact failure mode this
test was written to kill. The shipped detector mitigates the worst of
that residual (the verb-bearing cases) but does not eliminate it.

The path to truly fail-closed is to INVERT the default: every
hub-anchored attribute call is treated as a mutator UNLESS its tail
method begins with a read prefix (``get_`` / ``list_`` / ``read_`` /
``is_`` / ``has_`` / ``find_`` / ``load_`` / ``fetch_`` / ``iter_``)
or appears in an explicit READ allowlist. That inversion is
**EXT scope per R1 round-5** — out of scope for the shipped
narrow-scope monitor-layer invariant.

Bypasser count after STRUCTURAL+ALLOWLIST hybrid (Round-4 FIX D)
================================================================

After replacing the hard-coded method-name allowlist with a STRUCTURAL
mutation detector, the mutator set GROWS from **51 → 54** (and the
bypasser set GROWS from **50 → 53**, the +3 reflecting the three
R1-named real mutators the old name-allowlist missed). R1's estimate
was "≥54" total mutators; we land at exactly 54 (mutators) / 53
(bypassers, since ``update_run_budget_call`` is the only properly
gated mutator). New entries the structural detector catches that the
old name-allowlist missed:

  * ``workhub_set_priority_call``                — uses ``reg.workhub.stores.tasks.update(...)``;
                                                   the old allowlist looked for the literal method
                                                   ``set_priority`` which CodeHub does not expose
                                                   (priority is set indirectly via store.update).
  * ``workhub_mark_intentionally_dead_call``     — calls ``reg.gate_registry.mark_path_intentionally_dead(...)``
                                                   (NOT ``mark_intentionally_dead`` — R1's exact catch).
  * ``registryhub_update_endpoint_schema_call``       — calls ``reg.registryhub.update_schema(...)``;
                                                   the old allowlist had ``update_endpoint_schema`` /
                                                   ``update_table_schema`` but not plain ``update_schema``.

The structural detector flags a ``*_call`` as a mutator if any of these
AST signals appears in its body:

  (a) attribute call whose method name contains one of the mutation
      VERB substrings: create, update, set, delete, remove, merge,
      force, kill, start, stop, register, claim, complete, fail,
      cancel, submit, record, deliver, spawn, publish_event, mark.
  (b) call to subprocess.*, os.system, os.rename, os.unlink, os.remove,
      os.makedirs, os.rmdir, os.replace, os.link, os.symlink.
  (c) call to Path-method write_text / write_bytes / mkdir / touch /
      unlink / rmdir / rename / replace / rmtree.
  (d) call to shutil.copy / copy2 / copyfile / copytree / move / rmtree
      / write.
  (e) call to git_ops.* or .git.* on add / commit / merge / force_merge
      / push.
  (f) explicit attribute-assignment on a hub/store object: e.g.
      ``reg.codehub.<attr> = ...`` / ``store.<attr> = ...``.
  (g) calls into INTERNAL_PERSIST_HELPERS like ``_save_registry`` /
      ``_save_user_gates`` / ``_atomic_write_text``.
  (h) SQL writes (.execute on INSERT/UPDATE/DELETE/REPLACE/DROP).

Exemptions (NOT classified as mutators):
  * pure-read GET-only handlers that only return data (no mutation
    signals fire).
  * mutation signals that appear ONLY inside ``if False:`` /
    ``if 0:`` / ``if __debug__:`` dead branches.

A self-test (``test_structural_detector_recall``) feeds the detector
5 KNOWN-MUTATOR function bodies and asserts ALL FIVE are flagged.

Why this test exists
====================

PHASE 3 already landed ``test_write_gate_invariant.py`` to close the
denylist-by-omission failure mode at the *tool* layer: every tool that
writes the filesystem must route through ``is_write_allowed`` (or
appear in an allowlist with a justified reason).

Reviewer 1's PHASE 4 structural concern: that invariant only covers
``env_generator/llm_generator/tools/**``. The SAME failure-mode lives
one layer up — in ``live_monitor_server.py`` ``*_call`` dispatch:

  * ~50 module-level helpers named ``<verb>_call`` are the actual
    endpoint handlers that ``do_GET`` / ``do_POST`` / ``do_DELETE``
    funnel HTTP requests into.
  * The only authentication touchpoint is ``_enforce_auth`` at the
    very top of each HTTP verb dispatcher. ``_enforce_auth`` is a
    NO-OP when ``ENVGEN_AUTH_TOKEN`` is unset (the production
    default — see ``auth_required()`` at line 4482-4484) AND, even
    when it fires, only validates session presence. There is no
    role gating layer.
  * As a result, every destructive ``*_call`` (delete_project_call,
    codehub_force_merge_pr_call, deliver_project_call(force=True),
    stop_run_call, upsert_knowledge_call / delete_knowledge_call,
    workhub_mark_intentionally_dead_call, set_project_status_call,
    update_user_gate_call, etc.) is reachable by any caller able to
    reach the server port.
  * The ONE handler that follows the recommended pattern is
    ``update_run_budget_call`` (line 3344): it checks
    ``body.get('_requester_role') != 'admin'`` for the privileged
    ``unlimited`` knob. Every other mutation handler lacks any role
    check.

PHASE 1 AUDIT C enumerated 30+ such handlers. This test makes the
audit a permanent structural invariant: any new ``*_call`` that
mutates state (writes files, kills processes, mutates hub state,
flips project lifecycle, mutates host-wide knowledge/skill DBs, etc.)
MUST either (a) carry an in-function role check, or (b) appear in
``MONITOR_ALLOWLIST`` with a one-line file:line justification — same
pattern as PHASE 3's ``EXPECTED_ALLOWLIST``.

How the invariant works
=======================

For every module-level ``def <name>_call(...)`` in
``live_monitor_server.py`` we ask, via Python's ``ast`` module:

  Q1. Does this function mutate state? Heuristics:
        * Path-method writes / deletes: ``write_text`` / ``write_bytes`` /
          ``unlink`` / ``rmdir`` / ``rmtree`` / ``mkdir`` / ``replace`` /
          ``rename`` / ``touch``.
        * ``open(P, "w"|"a"|"x")``.
        * ``shutil.copy*`` / ``shutil.move`` / ``shutil.rmtree``.
        * ``os.rename`` / ``os.replace`` / ``os.remove`` / ``os.unlink``
          / ``os.makedirs``.
        * Subprocess: ``subprocess.Popen`` / ``.run`` / ``.terminate`` /
          ``.kill``.
        * Hub mutation method calls — any ``.codehub.X``,
          ``.workhub.X``, ``.registryhub.X``, ``.eventhub.X``, ``.runhub.X``,
          ``.human_console.X``, ``.gate_registry.X``, ``.set_project_status``,
          ``.commit`` / ``.merge_pull_request`` /
          ``.force_merge_pull_request`` / ``.publish_event`` /
          ``.start_conversation`` / ``.send_message`` /
          ``.mark_resolved`` / ``.mark_read`` / ``.subscribe`` /
          ``.create_task`` / ``.complete_task`` / ``.fail_task`` /
          ``.set_priority`` / ``.create_plan`` / ``.add_task_to_plan`` /
          ``.create_page`` / ``.append_block`` / ``.update_block`` /
          ``.insert_block_after`` /
          ``.submit_visual_review`` / ``.mark_intentionally_dead`` /
          ``.record_decision`` / ``.comment`` / ``.open_pull_request`` /
          ``.submit_review`` / ``.record_check`` / ``.register_endpoint``
          / ``.register_table`` / ``.register_consumer`` /
          ``.register_mcp_server`` / ``.update_endpoint_schema`` /
          ``.deprecate_endpoint`` / ``.update_table_schema`` /
          ``.update_run_status`` / ``.record_run`` / ``.submit_visual_review``
          / ``.delete_*`` / ``.upsert_*``.
        * SQL writes: any ``.execute("...INSERT..."|"...UPDATE..."|
          "...DELETE...")`` and ``.commit()``.
        * Process control on a Popen handle (``handle["popen"]``):
          ``.terminate()`` / ``.kill()``.
        * Calls into validate_gate / set_project_status / save_registry
          family.

  Q2. Does the function (or one of its same-module helpers it calls)
      have an in-function role/auth check? Heuristics:
        * Reads ``body.get("_requester_role")`` or
          ``body["_requester_role"]``.
        * String-compares against ``"admin"`` / ``"maintainer"`` /
          ``"user"`` (and short-circuits / returns).
        * Calls a helper named ``_require_role`` / ``_enforce_role``
          / ``_check_role`` / ``_require_admin`` (these don't exist
          today but the test is forward-compatible).

      We deliberately do NOT count the top-level ``_enforce_auth`` as
      a role check — it's session-presence only, and short-circuits
      to True when ``ENVGEN_AUTH_TOKEN`` is unset.

  Q3. If Q1 says "mutates" and Q2 says "no role check", flag as
      bypassing — UNLESS the function name appears in
      ``MONITOR_ALLOWLIST`` with a justification.

Calibration anchors
===================

``update_run_budget_call`` is the canonical positive example: it
mutates state (writes ``run_budget.json``) AND carries an explicit
role check at line 3343-3345. The test asserts both that this
function is detected as mutating AND that it's detected as gated.

``list_skills_call`` / ``list_user_gates_call`` / ``read_skill_call``
are negative examples: they don't mutate, so they shouldn't even be
in the candidate set.

Failure mode
============

Structural — does NOT execute any handler. The failure message lists
each bypasser with its file:line and a sample of its mutation sites,
so the fix author can either (i) add a role check inside the call
(mirror update_run_budget_call:3344), or (ii) add a justified entry to
``MONITOR_ALLOWLIST``.

Source of initial allowlist entries
====================================

Every entry in ``MONITOR_ALLOWLIST`` below cites the corresponding
PHASE 1 AUDIT C finding and the recommended_action it carries
("gate_method_layer" / "allowlist_with_justification" /
"no_action_needed"). Where the audit recommended ``gate_method_layer``
the entry is NOT added — those handlers MUST fail the test until they
either gain a role check or are explicitly accepted. Today the
allowlist contains only the no-action-needed cases (auth login/logout)
plus the partially-gated ``update_run_budget_call`` (which is the
positive calibration anchor).
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR_FILE = (
    REPO_ROOT / "env_generator" / "llm_generator" / "live_monitor_server.py"
)

# --- Q1 heuristics: what counts as a state-mutating call ------------------

# Path-method writes (called on any expression, e.g. ``p.write_text(...)``).
PATH_WRITE_METHODS: Set[str] = {
    "write_text",
    "write_bytes",
    "touch",
    "unlink",
    "rmdir",
    "rmtree",
    "rename",
    "replace",
    "mkdir",
}

# shutil module-level write / delete functions.
SHUTIL_WRITE_FNS: Set[str] = {
    "copy", "copy2", "copyfile", "copytree", "move", "rmtree", "write",
}

# os module-level write / delete functions.
OS_WRITE_FNS: Set[str] = {
    "rename", "replace", "link", "symlink", "makedirs",
    "remove", "unlink", "rmdir",
}

# Subprocess / process control. spawning a new process is a privileged op,
# and calling .terminate()/.kill() on a Popen handle is a denial-of-service
# surface.
SUBPROCESS_SPAWNS: Set[str] = {"Popen", "run", "call", "check_call", "check_output"}
PROCESS_CONTROL_METHODS: Set[str] = {"terminate", "kill"}

# Hub-level mutator methods. Any attribute call whose tail attribute is in
# this set AND whose preceding chain mentions one of {codehub, workhub,
# registryhub, eventhub, runhub, human_console, gate_registry, reg} is treated
# as a hub mutation. We use "reg" because many *_call helpers do
# ``reg.codehub.X(...)`` — the attr-chain walker classifies on the tail
# attribute and confirms a hub-ish anchor in the chain.
HUB_ANCHORS: Set[str] = {
    "codehub",
    "workhub",
    "registryhub",
    "eventhub",
    "runhub",
    "human_console",
    "gate_registry",
    # Outer-most receiver in this file is typically ``reg`` (HubRegistry
    # object). Use it as a fall-back anchor so we catch ``reg.X(...)``
    # mutator calls like ``reg.set_project_status("completed")``.
    "reg",
}
HUB_MUTATOR_METHODS: Set[str] = {
    # CodeHub
    "commit",
    "commit_for_agent",
    "merge_pull_request",
    "force_merge_pull_request",
    "open_pull_request",
    "submit_review",
    "record_check",
    "record_commit",
    "resolve_conflict",
    "revert_commit",
    "create_release",
    # WorkHub
    "create_task",
    "set_priority",
    "claim_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "create_page",
    "append_block",
    "update_block",
    "insert_block_after",
    "submit_visual_review",
    "mark_intentionally_dead",
    "comment",
    "record_decision",
    # Tier A retirement (docs/plan_task_stage_review_2026_06_03.md):
    # "create_plan" and "add_task_to_plan" retired; both methods
    # gone from WorkHub. Their HTTP route handlers removed too.
    # RegistryHub
    "register_endpoint",
    "register_table",
    "register_consumer",
    "register_mcp_server",
    "update_endpoint_schema",
    "deprecate_endpoint",
    "update_table_schema",
    # EventHub
    "mark_read",
    "mark_all_read",
    "subscribe",
    "publish_event",
    # RunHub
    "record_run",
    "update_run_status",
    # HumanConsole / project-level
    "start_conversation",
    "send_message",
    "mark_resolved",
    "set_project_status",
    # User-gate registry
    "create_gate",
    "update_gate",
    "delete_gate",
    "validate_gate",
}

# SQL write keywords — detected inside string literals passed to .execute(...)
SQL_WRITE_KEYWORDS: Set[str] = {"INSERT", "UPDATE", "DELETE", "REPLACE", "DROP", "CREATE", "ALTER", "TRUNCATE"}

# Module-level helpers that themselves persist state (used by *_call funcs).
# Calling these counts as a mutation.
INTERNAL_PERSIST_HELPERS: Set[str] = {
    "_save_registry",
    "_save_user_gates",
    "_publish_global_event",
    "_atomic_write_text",
    "atomic_write_text",
    "_safe_reference_path",  # benign on its own, but writes are usually paired
}

# --- HYBRID detector: structural signals + name-allowlist backstop -------
#
# Round-4 R1 condition #3: the hard-coded ``HUB_MUTATOR_METHODS`` name
# allowlist has the same denylist-by-omission flaw the test exists to
# kill. R1 named three real mutators it misses (mark_path_intentionally_dead,
# update_schema, set_priority). We add a structural detector that
# flags ANY hub-anchored attribute call whose tail method contains one
# of the verb SUBSTRINGS below — i.e. classify on STRUCTURE (verb intent).
#
# We KEEP the legacy ``HUB_MUTATOR_METHODS`` name-allowlist as a backstop
# for known mutators whose names contain no verb substring
# (``send_message``, ``add_task_to_plan``). The detector is therefore
# HYBRID, not purely structural — see module docstring for the
# wording downgrade R1 round-5 required.
#
# TODO(R1 round-5 EXT): invert to truly fail-closed. Default-treat
# every hub-anchored attribute call as a mutator UNLESS the tail
# method begins with a read prefix (``get_`` / ``list_`` / ``read_`` /
# ``is_`` / ``has_`` / ``find_`` / ``load_`` / ``fetch_`` / ``iter_``)
# or appears in an explicit READ allowlist. The current hybrid still
# misses verb-free hub methods like ``amend`` / ``purge`` / ``rename_page``.
# This inversion is EXT scope and is not landed in the shipped
# narrow-scope invariant.

# Verb substrings that name-ify mutation. Any attribute call whose tail
# method's name contains ANY of these substrings AND whose receiver
# chain mentions a hub anchor (or "self" / "reg" / "stores") is treated
# as a mutator. "publish_event" is kept as a full token because no
# narrower substring exists.
MUTATION_VERB_SUBSTRINGS: Set[str] = {
    "create",
    "update",
    "set",        # set_priority, set_project_status, set_status, settings_set
    "delete",
    "remove",
    "merge",
    "force",      # force_merge_pull_request, force_kill
    "kill",
    "start",      # start_conversation, start_run
    "stop",       # stop_run
    "register",
    "claim",
    "complete",
    "fail",
    "cancel",
    "submit",     # submit_review, submit_visual_review
    "record",     # record_decision, record_commit, record_run
    "deliver",
    "spawn",
    "publish_event",
    "mark",       # mark_path_intentionally_dead, mark_read, mark_resolved
    "save",       # _save_registry, save_user_gates
    "write",      # write_text, write_bytes (already in PATH_WRITE_METHODS)
    "append",     # append_block (workhub mutation)
    "insert",     # insert_block_after
    "upsert",     # upsert_knowledge, upsert_skill
    "publish",    # publish_event, publish_global_event
    "subscribe",  # subscribe to event bus = mutation of subscription registry
    "open",       # open_pull_request
    "comment",    # codehub_comment, workhub_comment
    "resolve",    # mark_resolved, resolve_conflict
    "revert",     # revert_commit
    "deprecate",  # deprecate_endpoint
    "evaluate_gate",  # validate_gate writes; evaluate_gate sometimes side-effects (debatable)
    "_save",      # _save_registry, _save_user_gates
}

# Receiver chain anchors that indicate the call is on a hub/store/registry
# object — i.e. a stateful surface whose method calls are likely mutators.
# This generalizes HUB_ANCHORS by adding "self" (instance methods on the
# server) and "stores" (the per-hub store layer).
STRUCTURAL_RECEIVER_ANCHORS: Set[str] = HUB_ANCHORS | {
    "self",
    "stores",
    "store",
    "registry",
    "_registry",
    "mcp_registry",
}

# Git-operation tails. Calls on a chain containing ``git_ops`` or ``git``
# whose tail is one of these are mutators.
GIT_MUTATOR_TAILS: Set[str] = {
    "add", "commit", "merge", "force_merge", "push", "checkout",
}
GIT_RECEIVER_ANCHORS: Set[str] = {"git_ops", "git"}

# os.* mutator functions — extended beyond OS_WRITE_FNS to include
# system() (which executes a shell command).
OS_MUTATOR_FNS: Set[str] = OS_WRITE_FNS | {"system"}

# shutil mutator subset that R1 explicitly named.
SHUTIL_R1_MUTATORS: Set[str] = {"copy", "copy2", "copyfile", "copytree", "move", "rmtree"}

# --- Q2 heuristics: what counts as an in-function role check --------------

ROLE_LITERALS: Set[str] = {"admin", "maintainer", "user", "owner"}

# Forward-compatible helper names we'd accept if introduced later.
ROLE_CHECK_HELPERS: Set[str] = {
    "_require_role",
    "_enforce_role",
    "_check_role",
    "_require_admin",
    "_require_maintainer",
    "_assert_role",
}

# Body keys that carry the role/user identity.
REQUESTER_BODY_KEYS: Set[str] = {"_requester_role", "_requester_user", "_role", "role"}


# --- Allowlist: justified bypassers / calibration anchors -----------------
#
# Each entry MUST cite ``live_monitor_server.py:<line>`` and a one-line
# reason. PHASE 1 AUDIT C is the source of truth for what belongs here vs
# what must be gated.
MONITOR_ALLOWLIST: Dict[str, str] = {
    # ---- Authentication establishment (no role gating applicable) ----
    "auth_login_call": (
        "live_monitor_server.py:4487 — login mints a session; cannot itself "
        "require a role. EXEMPT in _enforce_auth at 4623."
    ),
    "auth_logout_call": (
        "live_monitor_server.py:4516 — logout consumes the session cookie; "
        "only the session holder can supply it."
    ),
    # ---- Positive calibration anchor (the ONE handler that already
    #      follows the recommended pattern) ----
    "update_run_budget_call": (
        "live_monitor_server.py:3344 — role check enforced for the "
        "privileged 'unlimited' knob (the only true privileged knob in this "
        "endpoint). Numeric caps editable by any authed user per the "
        "testing-tool stance. This is the template the other *_call "
        "siblings should mirror."
    ),
    # ---- (intentionally left otherwise empty on first land) ----
    # Per PHASE 1 AUDIT C, every other mutation *_call has
    # recommended_action == "gate_method_layer". Those handlers MUST fail
    # this test until they either gain a role check OR are explicitly
    # accepted here with a justification. This is the structural surface
    # Reviewer 1 said needs to be closed.
}


# --- Known deferred-to-EXT bypassers (R2 round-5 pin-count refinement) -----
#
# The 53 *_call handlers that mutate state, have no in-function role check,
# and are NOT in MONITOR_ALLOWLIST. These are the structural enumeration of
# Phase 0.2-EXT scope — each one needs a role check (mirror
# update_run_budget_call:3344) OR a justified MONITOR_ALLOWLIST entry.
#
# R2's refinement: by pinning this set explicitly, CI can RUN the invariant
# instead of --deselecting it. The invariant goes RED in either direction:
#   - NEW BYPASSER (regression): a 54th endpoint added without role check
#     and not in MONITOR_ALLOWLIST.
#   - CLOSED BYPASSER STILL PINNED (progress not reflected): Phase 0.2-EXT
#     closed one of these, but the pin wasn't updated. Edit this set to
#     remove the closed entry; the invariant now actively guards against
#     its regression.
#
# Phase 0.2-EXT goal: shrink this set to 0. Each removal moves a known
# bypass from "tolerated, documented" to "actively gated".
KNOWN_DEFERRED_TO_EXT: frozenset = frozenset({
    "registryhub_deprecate_endpoint_call",
    "registryhub_register_consumer_call",
    "registryhub_register_endpoint_call",
    "registryhub_register_mcp_server_call",
    "registryhub_register_table_call",
    "registryhub_update_endpoint_schema_call",
    "registryhub_update_table_schema_call",
    "codehub_force_merge_pr_call",
    "codehub_merge_pr_call",
    "codehub_open_pr_call",
    "codehub_record_check_call",
    "codehub_submit_review_call",
    "continue_run_call",
    "create_project_call",
    "create_user_gate_call",
    "delete_conversation_call",
    "delete_knowledge_call",
    "delete_project_call",
    "delete_reference_call",
    "delete_skill_call",
    "delete_user_gate_call",
    "deliver_project_call",
    "eventhub_mark_all_read_call",
    "eventhub_mark_read_call",
    "eventhub_subscribe_call",
    "runhub_record_run_call",
    "runhub_update_run_status_call",
    "send_message_call",
    "set_project_status_call",
    "start_conversation_call",
    "start_run_call",
    "stop_run_call",
    "update_user_gate_call",
    "upload_reference_call",
    "upsert_knowledge_call",
    "upsert_skill_call",
    # Tier A retirement (docs/plan_task_stage_review_2026_06_03.md):
    # ``workhub_add_task_to_plan_call`` + ``workhub_create_plan_call``
    # entries removed — the underlying handlers + routes are gone.
    "workhub_append_block_call",
    "workhub_cancel_task_call",
    "workhub_claim_task_call",
    "workhub_comment_call",
    "workhub_complete_task_call",
    "workhub_create_page_call",
    "workhub_create_task_call",
    "workhub_fail_task_call",
    "workhub_insert_block_after_call",
    "workhub_mark_intentionally_dead_call",
    "workhub_record_decision_call",
    "workhub_set_priority_call",
    "workhub_submit_visual_review_call",
    "workhub_update_block_call",
})


# ---------------------------------------------------------------------------
# AST data model
# ---------------------------------------------------------------------------


@dataclass
class MutationSite:
    """A single source location that mutates state."""

    line: int
    kind: str  # short tag, e.g. "write_text", "subprocess.Popen", "codehub.merge_pull_request"


@dataclass
class CallScan:
    """Per-function scan result for one ``*_call`` module-level helper."""

    func_name: str
    line: int
    mutation_sites: List[MutationSite] = field(default_factory=list)
    has_role_check: bool = False
    # diagnostics: what we matched as a role check, for the failure msg.
    role_check_evidence: Optional[str] = None

    @property
    def mutates_state(self) -> bool:
        return bool(self.mutation_sites)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _attr_chain(node: ast.AST) -> List[str]:
    """Flatten ``a.b.c`` to ``['a','b','c']``; non-attr/name -> []."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return parts


def _expr_text(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node).strip()
    except Exception:
        return ""


def _attr_contains_mutation_verb(attr: str) -> Optional[str]:
    """If ``attr`` contains any MUTATION_VERB_SUBSTRINGS, return the
    matched substring; else None. Substring match is intentional — see
    module docstring for the rationale.

    We exempt a small set of READ-shaped method names that happen to
    contain a mutation verb as a substring (e.g. ``get_settings`` would
    match "set" — exempt it).
    """
    # Exempt read-shaped methods that contain a mutation verb substring.
    READ_SHAPED_EXEMPT: Set[str] = {
        "get_settings",
        "list_settings",
        "get_diff",         # codehub_pr_diff_call calls get_diff
        "get_set",          # hypothetical
        "is_set",
        "is_create",
        "settings",
        "get_status",
        "get_state",
        "preset",           # contains "set" substring but is descriptive
    }
    if attr in READ_SHAPED_EXEMPT:
        return None
    # Read-prefixes that should never count as mutators.
    if attr.startswith(("get_", "list_", "read_", "is_", "has_", "find_", "load_", "fetch_", "iter_")):
        return None
    for verb in MUTATION_VERB_SUBSTRINGS:
        if verb in attr:
            return verb
    return None


def _classify_call_as_mutation(call: ast.Call) -> Optional[str]:
    """If ``call`` is a state-mutating call, return a short tag; else None.

    HYBRID detector (attempt-5 FIX D, wording downgraded R1 round-5):
    classifies on STRUCTURE (verb intent + hub-anchored receiver) AND
    falls back to a retained ``HUB_MUTATOR_METHODS`` name-allowlist
    for known verb-free mutators (``send_message``,
    ``add_task_to_plan``). The structural pass catches mutators the
    name-allowlist missed (mark_path_intentionally_dead,
    update_schema, set_priority via stores.tasks.update, etc.);
    the name-allowlist backstop keeps known verb-free mutators
    classified. Verb-free hub methods that are NOT in the
    name-allowlist (e.g. hypothetical ``amend`` / ``purge`` /
    ``rename_page``) remain a residual denylist-by-omission. The
    inversion that closes that residual is EXT scope — see module
    docstring's TODO.
    """
    func = call.func

    # --- Attribute-style calls: <expr>.<method>(...) ---
    if isinstance(func, ast.Attribute):
        attr = func.attr
        chain = _attr_chain(func)

        # shutil.X(...)
        if len(chain) >= 2 and chain[0] == "shutil" and attr in SHUTIL_WRITE_FNS:
            return f"shutil.{attr}"

        # os.X(...) — chain like ["os", "rename"]
        if (
            len(chain) >= 2
            and chain[0] == "os"
            and chain[-1] == attr
            and len(chain) == 2
            and attr in OS_MUTATOR_FNS
        ):
            return f"os.{attr}"

        # path.write_text / .mkdir / .unlink / .replace / .rename / .rmdir / .touch / .rmtree
        if attr in PATH_WRITE_METHODS:
            return attr

        # --- STRUCTURAL: hub-anchored call whose tail method NAME-ifies
        # mutation (verb substring), regardless of whether that name was
        # in the historical HUB_MUTATOR_METHODS allowlist. This is the
        # R1-FIX-D core change. Falls through to the legacy name-allowlist
        # check below as a backstop.
        if any(c in STRUCTURAL_RECEIVER_ANCHORS for c in chain[:-1]):
            verb = _attr_contains_mutation_verb(attr)
            if verb is not None:
                for c in chain[:-1]:
                    if c in STRUCTURAL_RECEIVER_ANCHORS:
                        return f"{c}.{attr}[verb:{verb}]"
                return f"hub.{attr}[verb:{verb}]"

        # Hub-level mutators (LEGACY name-allowlist path; kept as a
        # backstop for any method whose name does NOT contain a mutation
        # verb substring but is still known to mutate).
        if attr in HUB_MUTATOR_METHODS and any(c in HUB_ANCHORS for c in chain[:-1]):
            for c in chain[:-1]:
                if c in HUB_ANCHORS:
                    return f"{c}.{attr}"
            return f"hub.{attr}"

        # --- STRUCTURAL: git_ops.* / .git.* mutator tails ---
        if attr in GIT_MUTATOR_TAILS and any(c in GIT_RECEIVER_ANCHORS for c in chain[:-1]):
            return f"git.{attr}"

        # Process control on a Popen handle: x.terminate() / x.kill().
        if attr in PROCESS_CONTROL_METHODS:
            return f"process.{attr}"

        # subprocess.Popen / subprocess.run / subprocess.call (attribute form)
        if (
            len(chain) >= 2
            and chain[0] == "subprocess"
            and attr in SUBPROCESS_SPAWNS
        ):
            return f"subprocess.{attr}"

        # SQL writes: con.execute("INSERT/UPDATE/DELETE ...")
        if attr in {"execute", "executemany", "executescript"} and call.args:
            first = call.args[0]
            # Static SQL literal:
            sql_text = ""
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                sql_text = first.value
            # f-string with constant prefix:
            elif isinstance(first, ast.JoinedStr):
                for v in first.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        sql_text += v.value
            up = sql_text.upper()
            for kw in SQL_WRITE_KEYWORDS:
                if kw in up:
                    return f"sql.{kw.lower()}"
            # ``con.commit()`` is the matching commit call:
        if attr == "commit" and not call.args and not call.keywords:
            # only count as a mutation when the receiver is a connection-ish
            # name; ``reg.commit()`` would also match but reg has no commit
            # method in this file, so false positives are negligible.
            recv = chain[-2] if len(chain) >= 2 else ""
            if recv in {"con", "conn", "cur", "connection", "db"}:
                return "sql.commit"

        return None

    # --- Name-style calls: open(...), Popen(...), _save_registry(...) ---
    if isinstance(func, ast.Name):
        name = func.id

        if name == "open":
            mode: Optional[str] = None
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                mode = (
                    call.args[1].value
                    if isinstance(call.args[1].value, str)
                    else None
                )
            for kw in call.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        mode = kw.value.value
            if mode and any(c in mode for c in ("w", "a", "x")):
                return f"open({mode!r})"
            return None

        if name in PATH_WRITE_METHODS:
            return name

        if name in SUBPROCESS_SPAWNS and name == "Popen":
            return "Popen"

        if name in INTERNAL_PERSIST_HELPERS:
            return name

        return None

    return None


def _is_role_compare(node: ast.AST) -> Optional[str]:
    """If ``node`` is a Compare against a known role literal whose left
    side reads a role from the request, return a short evidence string.
    NOTE: this only confirms the SHAPE of the comparison — it does NOT
    confirm the comparison is used as a DENY gate (vs a grant-privilege
    branch). Use ``_role_check_evidence_in_func`` (below) to gate on the
    deny-shaped pattern.
    """
    if not isinstance(node, ast.Compare):
        return None
    left_text = _expr_text(node.left).replace(" ", "")
    anchors = (
        "_requester_role",
        "_requester_user",
        "_request_role()",
        "_request_username()",
    )
    if not any(a in left_text for a in anchors):
        return None
    for cmp in node.comparators:
        txt = _expr_text(cmp)
        if any(f"'{r}'" in txt or f'"{r}"' in txt for r in ROLE_LITERALS):
            return _expr_text(node)
    # tuple/list of role names
    return _expr_text(node)


def _is_role_helper_call(node: ast.AST) -> Optional[str]:
    """Detect calls to forward-compat helper functions like
    ``_require_role('admin')`` / ``_enforce_role('admin')``. These
    helpers don't exist today but the test is forward-compatible."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    helper_name = None
    if isinstance(func, ast.Name):
        helper_name = func.id
    elif isinstance(func, ast.Attribute):
        helper_name = func.attr
    if helper_name and helper_name in ROLE_CHECK_HELPERS:
        return _expr_text(node)
    return None


def _if_body_is_deny(if_body: List[ast.stmt]) -> bool:
    """Return True if the body of an ``if`` block short-circuits — i.e.
    is a ``return``/``raise`` (the deny-shape that
    ``update_run_budget_call:3344-3345`` uses: ``if role != 'admin':
    return {'error': ...}``).

    This is the critical refinement that distinguishes a DENY check
    (the deny-shape we want to count) from a GRANT-PRIVILEGE branch
    (the shape ``start_run_call:2342`` / ``continue_run_call:2489``
    use: ``if role == 'admin': run_env['UNLIMITED'] = '1'`` — which is
    NOT a gate, it's a feature flag).

    Conservative: only the FIRST statement of the if-body is checked.
    Any ``return``/``raise`` at the top of the block, regardless of
    what follows, is treated as a deny.
    """
    if not if_body:
        return False
    first = if_body[0]
    return isinstance(first, (ast.Return, ast.Raise))


def _is_in_dead_branch(node: ast.AST, func: ast.FunctionDef) -> bool:
    """Return True if ``node`` lives inside an ``if False:`` / ``if 0:`` /
    ``if __debug__ is False:`` branch that never executes. This lets us
    exempt obvious debug paths from mutator classification per R1's
    structural-detector exemption clause.

    Conservative: walks the func body and collects ranges of dead-branch
    statements. If the node's lineno falls inside any range, it's dead.
    """
    dead_ranges: List[tuple] = []
    for child in ast.walk(func):
        if not isinstance(child, ast.If):
            continue
        # Detect literal-False test:
        test = child.test
        is_dead = False
        if isinstance(test, ast.Constant) and test.value in (False, 0, None):
            is_dead = True
        elif (
            isinstance(test, ast.NameConstant) if hasattr(ast, "NameConstant") else False
        ):
            try:
                is_dead = test.value in (False, 0, None)
            except Exception:
                pass
        if is_dead and child.body:
            start = child.body[0].lineno
            end = getattr(child.body[-1], "end_lineno", child.body[-1].lineno)
            dead_ranges.append((start, end))
    ln = getattr(node, "lineno", 0)
    for s, e in dead_ranges:
        if s <= ln <= e:
            return True
    return False


def _attr_assignment_to_hub(node: ast.AST) -> Optional[str]:
    """If ``node`` is an ``Assign`` / ``AugAssign`` / ``AnnAssign`` whose
    target is an attribute on a hub/store/registry receiver, return a
    short tag; else None. Implements R1's "explicit body modification"
    structural signal.
    """
    targets: List[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    else:
        return None
    for t in targets:
        if isinstance(t, ast.Attribute):
            chain = _attr_chain(t)
            if any(c in STRUCTURAL_RECEIVER_ANCHORS for c in chain[:-1]):
                return f"assign.{chain[-1]}"
        # Subscript assignment on a hub anchor, e.g. ``self._cache[k] = v``.
        if isinstance(t, ast.Subscript) and isinstance(t.value, (ast.Attribute, ast.Name)):
            chain = _attr_chain(t.value) if isinstance(t.value, ast.Attribute) else [t.value.id]
            if any(c in STRUCTURAL_RECEIVER_ANCHORS for c in chain):
                return f"assign.{chain[-1]}[]"
    return None


def _scan_call_function(func: ast.FunctionDef) -> CallScan:
    """Scan one ``*_call`` function for mutation sites and role checks.

    HYBRID detector (attempt-5 FIX D, wording downgraded R1 round-5):
    classifies on structural signals (verb-intent method names on
    hub-anchored receivers, subprocess/os/shutil/Path/git ops,
    explicit attribute assignment on hub objects) AND retains a
    name-allowlist backstop for known verb-free mutators. Exempts
    nodes living inside ``if False:`` dead branches. See module
    docstring for the residual denylist-by-omission caveat.

    Role-check detection is DENY-shape aware (PHASE 4 SIBLING B FIX):
    we only count an ``if <role-compare>: <body>`` block as a gate
    when the body short-circuits with ``return`` or ``raise``. This
    rejects grant-privilege patterns like ``start_run_call:2342``
    (``if role == 'admin': run_env['UNLIMITED'] = '1'``), which AUDIT
    C explicitly says are NOT gates.
    """
    scan = CallScan(func_name=func.name, line=func.lineno)

    # First pass: mutation sites + role-helper calls (these gate on their
    # own; no need for surrounding If structure).
    for child in ast.walk(func):
        if isinstance(child, ast.Call):
            kind = _classify_call_as_mutation(child)
            if kind is not None and not _is_in_dead_branch(child, func):
                scan.mutation_sites.append(
                    MutationSite(line=getattr(child, "lineno", 0), kind=kind)
                )
            ev = _is_role_helper_call(child)
            if ev is not None and not scan.has_role_check:
                scan.has_role_check = True
                scan.role_check_evidence = ev
        # Explicit attribute assignment on hub/store/registry receivers
        # is a structural mutation signal per R1 FIX D.
        elif isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            tag = _attr_assignment_to_hub(child)
            if tag is not None and not _is_in_dead_branch(child, func):
                scan.mutation_sites.append(
                    MutationSite(line=getattr(child, "lineno", 0), kind=tag)
                )

    # Second pass: walk every ``If`` node and check whether its test is a
    # role-compare AND its body short-circuits. This is the deny-shape
    # required for a comparison to count as a gate.
    for child in ast.walk(func):
        if not isinstance(child, ast.If):
            continue
        ev = _is_role_compare(child.test)
        if ev is None:
            # Also accept a BoolOp/UnaryOp wrapping a role compare:
            # ``if not (role == 'admin'): ...`` or ``if role != 'admin' and X: ...``.
            for sub in ast.walk(child.test):
                if isinstance(sub, ast.Compare):
                    cand = _is_role_compare(sub)
                    if cand is not None:
                        ev = cand
                        break
        if ev is None:
            continue
        if _if_body_is_deny(child.body) and not scan.has_role_check:
            scan.has_role_check = True
            scan.role_check_evidence = f"if {ev}: <deny>"

    return scan


def scan_monitor_file() -> List[CallScan]:
    """Return one CallScan per module-level ``*_call`` def in the file."""
    source = MONITOR_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MONITOR_FILE))
    out: List[CallScan] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name.endswith("_call"):
                out.append(_scan_call_function(stmt))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMonitorCallGateInvariant(unittest.TestCase):
    """Structural invariant: every ``*_call`` in live_monitor_server.py that
    mutates state MUST carry an in-function role check OR appear in
    ``MONITOR_ALLOWLIST`` with a justification (PHASE 4 SIBLING B)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scans: List[CallScan] = scan_monitor_file()
        cls.mutators: List[CallScan] = [s for s in cls.scans if s.mutates_state]
        cls.bypassers: List[CallScan] = [
            s
            for s in cls.mutators
            if not s.has_role_check and s.func_name not in MONITOR_ALLOWLIST
        ]

    def test_monitor_file_is_discovered(self) -> None:
        """Sanity: the AST scan must find a non-trivial number of *_call helpers."""
        self.assertTrue(
            MONITOR_FILE.exists(),
            f"live_monitor_server.py missing at {MONITOR_FILE}",
        )
        self.assertGreater(
            len(self.scans),
            30,
            f"*_call scan found suspiciously few defs ({len(self.scans)}) — "
            "check MONITOR_FILE / ast walking",
        )

    def test_update_run_budget_call_is_calibrated_as_gated(self) -> None:
        """Calibration: ``update_run_budget_call`` is the ONE handler in the
        file that already follows the recommended pattern (role check on
        line 3344). The heuristic MUST detect both that it mutates AND
        that it has a role check. If this calibration ever fails the
        heuristic has drifted and the rest of the test is unreliable."""
        by_name = {s.func_name: s for s in self.scans}
        s = by_name.get("update_run_budget_call")
        self.assertIsNotNone(
            s, "update_run_budget_call not discovered — file structure changed?",
        )
        self.assertTrue(
            s.mutates_state,
            f"update_run_budget_call should be detected as mutating "
            f"(writes run_budget.json); got 0 mutation sites",
        )
        self.assertTrue(
            s.has_role_check,
            f"update_run_budget_call should be detected as GATED — "
            f"line 3344 explicitly compares body.get('_requester_role') "
            f"to 'admin'. Evidence: {s.role_check_evidence!r}",
        )

    def test_read_only_calls_are_not_flagged_as_mutating(self) -> None:
        """Negative calibration: pure read-only helpers must not appear in
        the candidate mutator set. ``list_skills_call`` / ``read_skill_call``
        / ``list_user_gates_call`` / ``list_references_call`` /
        ``list_code_branches_call`` only enumerate disk state, they don't
        modify it. If they show up as mutators the heuristic over-fires."""
        by_name = {s.func_name: s for s in self.scans}
        for read_only in (
            "list_skills_call",
            "read_skill_call",
            "list_user_gates_call",
            "list_references_call",
            "list_code_branches_call",
            "run_budget_call",
        ):
            s = by_name.get(read_only)
            if s is None:
                continue  # function may have been renamed/removed
            self.assertFalse(
                s.mutates_state,
                f"{read_only} flagged as mutating but is read-only. "
                f"Sites: {[m.kind for m in s.mutation_sites]}",
            )

    def test_no_mutating_call_bypasses_role_gate(self) -> None:
        """THE INVARIANT (R2 round-5 pin-count refinement).

        Every ``*_call`` whose body mutates state MUST carry an in-function
        role check (mirroring update_run_budget_call:3344), OR appear in
        ``MONITOR_ALLOWLIST`` with a one-line file:line justification.

        We deliberately do NOT count the top-level ``_enforce_auth`` as a
        gate: it short-circuits to True when ENVGEN_AUTH_TOKEN is unset
        (the production default) and only validates session presence
        when it does fire.

        R2 round-5 refinement: instead of failing on ANY bypasser
        (which would force CI to ``--deselect`` the whole test and go
        blind on the monitor layer entirely), this test PINS the
        currently-known bypasser set. A 54th endpoint added during
        Phase 1-4 work — or worse, a regression that re-introduces a
        previously-fixed bypass — RED's the test in CI immediately.

        Going GREEN requires EITHER:
          (a) close the bypass (add role check) AND remove the name
              from KNOWN_DEFERRED_TO_EXT, OR
          (b) add a MONITOR_ALLOWLIST entry with justification AND
              remove the name from KNOWN_DEFERRED_TO_EXT.

        Phase 0.2-EXT will go through KNOWN_DEFERRED_TO_EXT 53→0;
        as each entry leaves the set, that bypasser is closed for good.
        When the set empties, this test guards monitor layer the same
        way the tool-layer + method-layer invariants guard theirs."""
        actual = {s.func_name for s in self.bypassers}
        expected = set(KNOWN_DEFERRED_TO_EXT)

        new_bypassers = actual - expected
        closed_but_still_pinned = expected - actual

        if not new_bypassers and not closed_but_still_pinned:
            return  # GREEN — invariant holds (no drift in either direction)

        lines = ["", "Monitor-layer *_call gate invariant FAILED.", ""]

        if new_bypassers:
            lines.extend([
                "🔴 NEW BYPASSERS (regression — add role check OR add to "
                "MONITOR_ALLOWLIST with justification, NOT to KNOWN_DEFERRED_TO_EXT):",
                "",
            ])
            for s in sorted(self.bypassers, key=lambda x: x.line):
                if s.func_name not in new_bypassers:
                    continue
                lines.append(f"  {s.func_name} @ live_monitor_server.py:{s.line}")
                for m in s.mutation_sites[:5]:
                    lines.append(f"      - {m.kind} at line {m.line}")
                if len(s.mutation_sites) > 5:
                    lines.append(
                        f"      - ... and {len(s.mutation_sites) - 5} more sites"
                    )
            lines.append("")

        if closed_but_still_pinned:
            lines.extend([
                "🟢 BYPASSERS CLOSED — remove these from KNOWN_DEFERRED_TO_EXT "
                "(Phase 0.2-EXT progress; either role check was added or "
                "they were moved to MONITOR_ALLOWLIST):",
                "",
            ])
            for name in sorted(closed_but_still_pinned):
                lines.append(f"  {name}")
            lines.append("")

        lines.extend([
            "Fix:",
            "  - For NEW BYPASSERS: either (a) add an in-function role check "
            "mirroring update_run_budget_call:3344, or (b) add a MONITOR_ALLOWLIST "
            "entry citing live_monitor_server.py:<line> with a justification.",
            "  - For CLOSED BYPASSERS: edit KNOWN_DEFERRED_TO_EXT below to remove "
            "the entry. The closed bypasser stays closed — the invariant now "
            "guards against its regression.",
        ])
        self.fail("\n".join(lines))

    def test_allowlist_entries_have_justifications(self) -> None:
        """Every MONITOR_ALLOWLIST value must cite file:line and a reason."""
        for name, justification in MONITOR_ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                f"MONITOR_ALLOWLIST entry for {name!r} has no justification",
            )
            self.assertIn(
                "live_monitor_server.py:",
                justification,
                f"MONITOR_ALLOWLIST entry for {name!r} must cite "
                f"live_monitor_server.py:<line> (got: {justification!r})",
            )

    def test_allowlist_entries_correspond_to_real_functions(self) -> None:
        """An allowlist entry must name a function that actually exists.
        Otherwise allowlist drift silently hides bypassers that the entry
        was supposed to cover."""
        names = {s.func_name for s in self.scans}
        for entry in MONITOR_ALLOWLIST:
            self.assertIn(
                entry,
                names,
                f"MONITOR_ALLOWLIST entry {entry!r} does not match any "
                f"module-level *_call function in live_monitor_server.py",
            )

    # ------------------------------------------------------------------
    # R1 FIX D specifically-named cases — verify the structural detector
    # catches what the name-allowlist missed.
    # ------------------------------------------------------------------

    def test_structural_catches_mark_path_intentionally_dead(self) -> None:
        """R1 Round-4 condition #3: the OLD name-allowlist had
        ``mark_intentionally_dead`` but the real method on GateRegistry
        is ``mark_path_intentionally_dead`` (gate_registry.py:423).
        The structural detector MUST flag
        ``workhub_mark_path_intentionally_dead_call`` (the *_call wrapper)
        / ``workhub_mark_intentionally_dead_call`` as a mutator.

        NOTE: the current *_call function is named
        ``workhub_mark_intentionally_dead_call`` (legacy name). R1
        flagged this naming mismatch — the function NAME contains
        ``mark_intentionally_dead`` but its BODY calls
        ``mark_path_intentionally_dead``. The structural detector
        must catch the BODY call regardless of the function name."""
        by_name = {s.func_name: s for s in self.scans}
        s = by_name.get("workhub_mark_intentionally_dead_call")
        self.assertIsNotNone(
            s,
            "workhub_mark_intentionally_dead_call not discovered — "
            "file structure changed?",
        )
        self.assertTrue(
            s.mutates_state,
            "workhub_mark_intentionally_dead_call must be flagged as "
            "mutating — its body calls reg.gate_registry."
            "mark_path_intentionally_dead(...). The OLD name-allowlist "
            "missed this because it only had 'mark_intentionally_dead'. "
            f"Got mutation sites: {[m.kind for m in s.mutation_sites]}",
        )
        # Confirm the specific tag mentions the verb-substring match
        # so future grep-ability is preserved.
        kinds = " ".join(m.kind for m in s.mutation_sites)
        self.assertIn(
            "mark",
            kinds,
            f"Expected a 'mark' verb-tag in mutation sites; got {kinds!r}",
        )

    def test_structural_catches_update_schema(self) -> None:
        """R1 Round-4 condition #3: ``registryhub_update_endpoint_schema_call``
        calls ``reg.registryhub.update_schema(...)``. The OLD name-allowlist
        had ``update_endpoint_schema`` / ``update_table_schema`` but not
        plain ``update_schema`` — so this *_call slipped through. The
        structural detector MUST flag any ``*_update_schema_call`` as
        a mutator."""
        by_name = {s.func_name: s for s in self.scans}
        s = by_name.get("registryhub_update_endpoint_schema_call")
        self.assertIsNotNone(s)
        self.assertTrue(
            s.mutates_state,
            "registryhub_update_endpoint_schema_call must be flagged as "
            "mutating — its body calls reg.registryhub.update_schema(...). "
            "The OLD name-allowlist missed plain 'update_schema'. "
            f"Got mutation sites: {[m.kind for m in s.mutation_sites]}",
        )
        kinds = " ".join(m.kind for m in s.mutation_sites)
        self.assertIn(
            "update",
            kinds,
            f"Expected an 'update' verb-tag; got {kinds!r}",
        )

    def test_structural_catches_set_priority(self) -> None:
        """R1 Round-4 condition #3: ``workhub_set_priority_call`` mutates
        task metadata via ``reg.workhub.stores.tasks.update(...)``. The
        OLD name-allowlist had ``set_priority`` as a method name but
        WorkHub does NOT expose a literal ``set_priority`` method —
        priority is set indirectly via store.update. So the old
        detector missed this *_call entirely. The structural detector
        MUST flag any ``*_set_priority_call`` as a mutator."""
        by_name = {s.func_name: s for s in self.scans}
        s = by_name.get("workhub_set_priority_call")
        self.assertIsNotNone(s)
        self.assertTrue(
            s.mutates_state,
            "workhub_set_priority_call must be flagged as mutating — "
            "its body calls reg.workhub.stores.tasks.update(...). "
            f"Got mutation sites: {[m.kind for m in s.mutation_sites]}",
        )

    def test_structural_detector_recall(self) -> None:
        """SELF-TEST: feed the structural detector 5 KNOWN-MUTATOR
        function bodies and assert ALL FIVE are flagged. This is the
        detector-recall check R1 FIX D requires — it proves the
        detector recognizes the structural signals it claims to."""
        recall_cases = [
            # 1. Hub-anchored verb-method call (R1's update_schema miss).
            (
                "fake_update_schema_call",
                """
def fake_update_schema_call(reg, body):
    return reg.registryhub.update_schema(endpoint_id="x", request=body)
""",
            ),
            # 2. Hub-anchored mark_* (R1's mark_path_intentionally_dead miss).
            (
                "fake_mark_path_intentionally_dead_call",
                """
def fake_mark_path_intentionally_dead_call(reg, body):
    return reg.gate_registry.mark_path_intentionally_dead(
        path=body['path'], reason=body['reason'], agent='x',
    )
""",
            ),
            # 3. Path.write_text — direct file mutation.
            (
                "fake_write_call",
                """
from pathlib import Path
def fake_write_call(body):
    p = Path('/tmp/x')
    p.write_text(body['content'])
    return {'ok': True}
""",
            ),
            # 4. shutil.rmtree — destructive shutil op.
            (
                "fake_rmtree_call",
                """
import shutil
def fake_rmtree_call(name):
    shutil.rmtree('/tmp/' + name)
    return {'ok': True}
""",
            ),
            # 5. subprocess.Popen — process spawn.
            (
                "fake_spawn_call",
                """
import subprocess
def fake_spawn_call(body):
    subprocess.Popen(['echo', body['msg']])
    return {'ok': True}
""",
            ),
        ]
        misses: List[str] = []
        for name, src in recall_cases:
            tree = ast.parse(src)
            func = next(
                n for n in tree.body
                if isinstance(n, ast.FunctionDef)
            )
            scan = _scan_call_function(func)
            if not scan.mutates_state:
                misses.append(name)
        self.assertEqual(
            misses,
            [],
            f"Structural detector RECALL FAILED — the following "
            f"known-mutator bodies were NOT flagged: {misses}. "
            "Detector recall is the core invariant; if it can miss "
            "obvious mutators the test cannot be trusted.",
        )

    def test_bypasser_count_meets_r1_estimate(self) -> None:
        """R1 Round-4 FIX D estimated the structural detector should
        find ``≥54`` true mutators (vs the 51 the old name-allowlist
        reported). Legitimate drops since:
          * 2026-06-02: retirement of ``workhub_submit_design_review_call``
            (design approval moved to orchestrator-hosted kickoff).
          * 2026-06-03: retirement of ``workhub_create_plan_call`` +
            ``workhub_add_task_to_plan_call`` (Tier A — WorkHub stage
            layer + create_plan/add_task_to_plan retired per
            docs/plan_task_stage_review_2026_06_03.md).
        Floor is now ``≥51``. Any future regression that drops below
        is a REAL detector-recall loss signal."""
        self.assertGreaterEqual(
            len(self.mutators),
            51,
            f"R1 FIX D expected ≥51 structural mutators (post-Tier A "
            f"WorkHub stage retirement); got {len(self.mutators)}. The "
            f"detector may have lost recall.",
        )


# ---------------------------------------------------------------------------
# Diagnostics — printed manually via `python tests/test_monitor_call_gate_invariant.py`.
# ---------------------------------------------------------------------------


def _print_diagnostics() -> None:  # pragma: no cover - manual invocation
    scans = scan_monitor_file()
    mutators = [s for s in scans if s.mutates_state]
    gated = [s for s in mutators if s.has_role_check]
    allowlisted = [s for s in mutators if s.func_name in MONITOR_ALLOWLIST]
    bypassers = [
        s
        for s in mutators
        if not s.has_role_check and s.func_name not in MONITOR_ALLOWLIST
    ]
    print(f"# total *_call defs scanned:       {len(scans)}")
    print(f"# mutating *_call defs:            {len(mutators)}")
    print(f"# of those, GATED (role check):    {len(gated)}")
    print(f"# of those, ALLOWLISTED:           {len(allowlisted)}")
    print(f"# of those, BYPASSING:             {len(bypassers)}")
    print()
    print("BYPASSERS:")
    for s in sorted(bypassers, key=lambda x: x.line):
        sites = ", ".join(f"{m.kind}@L{m.line}" for m in s.mutation_sites[:3])
        print(f"  {s.func_name} @ L{s.line}  -> {sites}")
    print()
    print("GATED (sample of 8):")
    for s in gated[:8]:
        print(
            f"  {s.func_name} @ L{s.line}  "
            f"check: {s.role_check_evidence!r}"
        )


if __name__ == "__main__":  # pragma: no cover
    _print_diagnostics()
