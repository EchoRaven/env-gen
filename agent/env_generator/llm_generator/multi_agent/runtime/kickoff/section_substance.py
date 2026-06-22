"""Substance check for kickoff section decisions — shared by the agent-side
corrective loop (messaging) and the facilitator's phase gate (facilitate).

gemini exhibits three authoring failure shapes: MALFORMED tool calls (dropped),
empty shells ({"ui_pages": []}), and null-placeholder skeletons
([null, null, ...]). All three must read as NOT AUTHORED — otherwise they
satisfy existence checks and starve the synthesis (live 2026-06-10: the
meeting finalized on five empty frontend decisions two seconds before the
corrective turn could land a real one)."""

from __future__ import annotations

from typing import Any, Mapping

_META_KEYS = ("section", "kind", "recorded_by", "agent", "recorded_at",
              "milestone_index", "round")

# The contract keys each section legitimately declares. ``data_model``/``tables``
# both appear because the backend nests tables under data_model. Used to tell a
# "submitted the wrong thing" payload (only non-contract keys, e.g. the
# framework-owned auth_model) apart from a truncated/empty one — see
# ``non_contract_keys``.
_RECOGNIZED_KEYS = {
    "frontend": ("ui_pages", "screens", "user_flows", "ui_components"),
    "backend": ("endpoints", "data_model", "tables"),
    "verifier": ("predicates",),
}

# AUXILIARY kickoff fields a section legitimately records via the generic
# workhub_add_meeting_decision tool — there is NO kickoff_declare_* tool for
# them. The frontend prompt's FINAL PROTOCOL step 4 instructs exactly this
# ("one small add_meeting_decision for the scalar fields: auth, done_def"), and
# the reconcile/synthesis READS them (run_kickoff: done_def floor +
# _pick_feature_inventory). They are NOT buildable substance (section_has_substance
# still ignores them, so they don't advance the phase) but they are NOT
# non-contract garbage either: a decision carrying ONLY these must be ACCEPTED,
# not rejected into an 18× resend loop (run bsb900gpt). Auth (auth/auth_model)
# is deliberately EXCLUDED — it is framework-owned and a real wrong-keys signal
# (youtube run #13). Prefix match absorbs the LLM's flattened variants
# (feature_inventory_auth / feature_inventory_tags).
_AUX_KICKOFF_KEYS = {
    "frontend": ("done_def", "feature_inventory", "reference_image_manifest", "task_tree"),
    "backend": ("done_def", "feature_inventory", "task_tree"),
    "verifier": ("done_def", "feature_inventory"),
}


def _is_aux_key(key: str, section: str) -> bool:
    return any(key == aux or key.startswith(aux)
               for aux in _AUX_KICKOFF_KEYS.get(section, ()))


def non_contract_keys(content: Any, section: str) -> list:
    """Return the sorted non-meta keys a decision carried that are NOT part of
    this section's kickoff contract — but ONLY when no recognized key is present
    at all.

    Distinguishes "the lane submitted the wrong thing" (e.g. ``{auth_model:
    'jwt'}`` — auth is framework-owned, not a section-contract field) from a
    truncated/empty payload of the right keys. youtube run #13: the backend
    re-submitted ``{auth_model: 'jwt'}`` 22× because the generic "no recognized
    content → SUBMIT IN PARTS" guidance implied truncation and told it to resend.
    Returns [] when ANY recognized key is present (then it's empty/partial, not
    wrong-keys) or when there is no real extra content."""
    if not isinstance(content, Mapping):
        return []
    recognized = set(_RECOGNIZED_KEYS.get(section, ()))
    present = {k for k in content if k not in _META_KEYS}
    if not present or (present & recognized):
        return []
    # A decision carrying ONLY legitimate auxiliary kickoff fields (done_def /
    # feature_inventory / ...) is the prompt-sanctioned "scalar fields" decision —
    # accept it (return []), don't reject it into a resend loop. Only keys that are
    # neither contract NOR aux (e.g. framework-owned auth / auth_model) are real
    # "wrong keys" — and the message then names exactly those.
    wrong = sorted(k for k in present if not _is_aux_key(k, section))
    return wrong


def real_items(seq: Any) -> int:
    """Count NON-EMPTY items — mappings OR non-empty strings.

    Null-placeholder skeletons ([null, ...]), empty mappings and blank strings
    count 0 (the malformed/empty shells this guard exists to reject). Plain
    strings count because a section legitimately submits list-of-strings content
    — e.g. the verifier's predicates as descriptions
    (['docker_up succeeds', 'validation:api_smoke passes']) — which previously
    read as 0 and was falsely rejected as "no substantive content"."""
    if not isinstance(seq, (list, tuple)):
        return 0
    return sum(1 for x in seq
               if (isinstance(x, Mapping) and x) or (isinstance(x, str) and x.strip()))


def section_has_substance(content: Any, section: str) -> bool:
    if not isinstance(content, Mapping):
        return False
    if content.get("deferred"):
        return False
    if section == "frontend":
        # ALL first-class frontend declarations count as substance — each has a
        # dedicated kickoff_declare_* tool and the section MERGES parts. Counting
        # only ui_pages/screens wrongly rejected a `user_flows`-only part submitted
        # via the generic workhub_add_meeting_decision tool (kickoff_declare_user_flow
        # bypasses this guard by calling the service directly), even though that IS
        # the "submit in parts" the guard's own error message demands. Empty shells
        # / null skeletons still read as no-substance (real_items() counts only
        # non-empty mappings).
        return bool(real_items(content.get("ui_pages"))
                    or real_items(content.get("screens"))
                    or real_items(content.get("user_flows"))
                    or real_items(content.get("ui_components")))
    if section == "backend":
        dm = content.get("data_model")
        return bool(real_items(content.get("endpoints"))
                    or (isinstance(dm, Mapping) and real_items(dm.get("tables"))))
    if section == "verifier":
        return bool(real_items(content.get("predicates")))
    return True


def decision_has_substance(decision: Any, section: str) -> bool:
    """Both decision shapes: {"section","content":{...}} and flat."""
    if not isinstance(decision, Mapping):
        return False
    if section_has_substance(decision.get("content"), section):
        return True
    flat = {k: v for k, v in decision.items() if k not in _META_KEYS}
    return section_has_substance(flat, section)


def decision_advances_phase(decision: Any, section: str) -> bool:
    """May this decision advance the kickoff phase for its section?
    YES for substantive content, YES for an explicit deferred stub (the
    terminal advance-anyway marker after corrective turns are exhausted),
    NO for empty shells / null skeletons (the author is still being
    corrected — the meeting must wait)."""
    if not isinstance(decision, Mapping):
        return False
    content = decision.get("content")
    if isinstance(content, Mapping) and content.get("deferred"):
        return True
    if decision.get("deferred"):
        return True
    return decision_has_substance(decision, section)
