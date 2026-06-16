"""Human-chat support for agents.

Two responsibilities:

1. ``build_directive_block`` — produce the "Active human directives"
   block injected into the agent's system prompt every step, so the
   agent always knows what the human last said.
2. ``format_transcript_for_compression`` — flatten transcript entries
   into the plain text passed to the compressor LLM.

Storage stays in EventHub (canonical). This module only shapes data.
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Sequence


def build_directive_block(
    threads: Sequence[dict],
    transcripts: Mapping[str, List[dict]],
    max_raw_turns: int = 3,
) -> str:
    """Render the Active-human-directives block for system prompt injection.

    ``threads`` should already be filtered to the threads the agent
    cares about (typically the single most-recently-active one — the
    caller decides). ``transcripts[tid]`` should be the output of
    ``EventHub.get_thread_transcript(tid)``. Returns empty string when
    there's nothing to inject so the caller can splice unconditionally.
    """
    if not threads:
        return ""

    # ``list[-0:]`` returns the FULL list (Python slice gotcha), not the
    # empty list a caller intuitively expects. Special-case it so passing
    # ``max_raw_turns=0`` (or a negative value) actually suppresses the
    # raw-turn section instead of dumping the whole transcript.
    keep = int(max_raw_turns) if max_raw_turns and int(max_raw_turns) > 0 else 0

    lines: List[str] = ["=== Active human directives ==="]
    any_content = False
    for thread in threads:
        tid = thread.get("thread_id")
        summary = (thread.get("summary") or "").strip()
        if summary:
            lines.append(f"[thread {tid}] Summary: {summary}")
            any_content = True
        all_turns = list(transcripts.get(tid) or [])
        recent = all_turns[-keep:] if keep > 0 else []
        if recent:
            lines.append("Recent turns:")
            for entry in recent:
                speaker = entry.get("speaker", "?")
                text = (entry.get("text") or "").strip().replace("\n", " ")
                if len(text) > 280:
                    text = text[:277] + "…"
                lines.append(f"  - [{speaker}] {text}")
            any_content = True

    if not any_content:
        return ""

    lines.append("")  # trailing blank for clean splice
    return "\n".join(lines)


def format_transcript_for_compression(entries: Iterable[dict]) -> str:
    """Flatten transcript entries into the text fed to the summarizer LLM."""
    ordered = sorted(entries, key=lambda e: e.get("ts", 0))
    parts: List[str] = []
    for entry in ordered:
        speaker = entry.get("speaker", "?")
        text = (entry.get("text") or "").strip()
        parts.append(f"[{speaker}]: {text}")
    return "\n".join(parts)


async def compress_thread_if_needed(
    *,
    agent,
    thread_id: str,
    token_limit: int = 4000,
    keep_last_n: int = 10,
) -> bool:
    """Summarize older turns when a thread exceeds the token budget.

    Returns ``True`` if a new summary was written, ``False`` otherwise.
    Reuses the agent's own ``_generate_text`` (single-turn LLM call) so
    the LLM client/config stays in one place.

    Behaviour:

    * No-op if ``estimate_thread_tokens(thread_id) < token_limit``.
    * No-op if the transcript has ``<= keep_last_n`` entries — there's
      nothing to split off into the summary.
    * Otherwise: feed the older entries to ``agent._generate_text``,
      persist the result onto ``thread.summary``, mark
      ``summary_until_ts`` to the last older entry's ``ts``.
    """
    eh = agent._hubs.eventhub
    tokens = eh.estimate_thread_tokens(thread_id)
    if tokens < token_limit:
        return False

    transcript = eh.get_thread_transcript(thread_id)
    if len(transcript) <= keep_last_n:
        # Too few turns to bother splitting — let it grow.
        return False

    older = transcript[:-keep_last_n]
    if not older:
        return False
    cutoff_ts = older[-1].get("ts", 0)
    body = format_transcript_for_compression(older)

    system = (
        "You compress chat transcripts between a human user and a "
        "software agent into a single short paragraph: what the user "
        "asked for, what the agent committed to, what remains open. "
        "No greetings, no filler — just the durable facts."
    )
    summary = await agent._generate_text(system=system, user=body)
    summary = (summary or "").strip()
    if not summary:
        return False

    eh.update_thread_summary(
        thread_id=thread_id,
        summary=summary,
        summary_until_ts=cutoff_ts,
    )
    return True
