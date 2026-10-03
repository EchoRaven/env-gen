"""Seed data LLM tools (Cutover 21)."""

from __future__ import annotations

from typing import Any, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.seed_audit import audit_seed_data


def _project_dir_1202q(hub_registry):
    """The project root, so the seed audit can do its LIVE row count. (#1202q)

    Both agent-facing seed tools called `audit_seed_data(hub_registry)` with no project_dir,
    and without one the live path cannot even find the compose file — so an agent asking
    "audit the seeds" always got the fallback filter instead, which is
    `status == "defined"` and, per this module's own comment, "examines 0 tables in 145 of
    147 runs" and "skips 1729 of 1745 corpus tables".

    Measured across r22-r26 and r30: the live row count has succeeded ZERO times in any run,
    while `SEED AUDIT EXAMINED 0 OF N TABLES` fires 40-156 times per run. r26 shipped on that
    silence: its seed declares 8 `continue_watching` rows and its delivered database holds 1,
    because the child rows reference `profile_id: 1` while the parents were inserted with
    fresh ids (26-30). Nothing looked, so nothing said so.

    `HubRegistry.base_dir` is that root. Best-effort: an audit must not raise.
    """
    try:
        return getattr(hub_registry, "base_dir", None)
    except Exception:
        return None


class _SeedToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterSeedDataTool(_SeedToolBase):
    NAME = "register_seed_data"
    DESCRIPTION = ("Backend agent (or its database_worker spawn) records "
                    "that a table has been seeded. row_count must be the "
                    "actual row count after seeding. sample_excerpt "
                    "provides 1-3 representative rows for placeholder-"
                    "quality detection.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "row_count": {"type": "integer", "minimum": 0},
                    "sample_excerpt": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "1-3 representative seeded rows",
                    },
                },
                "required": ["table_name", "row_count", "sample_excerpt"],
            }, required=["table_name", "row_count", "sample_excerpt"])

    async def execute(self, *, table_name: str, row_count: int,
                       sample_excerpt: list, **_kw) -> ToolResult:
        record = self.hub_registry.schema_hub.register_seed_data(
            table_name=table_name, row_count=row_count,
            sample_excerpt=sample_excerpt,
            agent=getattr(self, "_agent_id", ""))
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"record": record})


def _unmapped_dataset_text_1203c2(project_dir) -> dict:
    """Content fields the staged dataset carries that NO model column can hold. #1203c2

    The framework stages `seed_dataset.json` from its real-content corpus; the lane declares the
    columns. When the dataset's text field has no column of that name the text is silently
    dropped — r145's 35 video `caption`s never reached `videos.title/description`, every video
    shipped wordless, and `primary_dataless` (HARD, never escapes) held the run.

    Returns `{entity: [field, ...]}` for TEXT-BEARING fields only, so a dataset's `likes` or
    `author_id` is not reported as lost: those are either counts the projector derives or
    relations the loader resolves, and naming them would bury the one field that matters
    (#1202vx). Compares against the DELIVERED `models.py`, which is what actually holds rows.
    Never raises — an unreadable tree reports nothing, which is the pre-#1203c2 behaviour.
    """
    _TEXT = ("caption", "text", "body", "bio", "summary", "excerpt", "headline",
             "overview", "blurb", "quote", "message", "content")
    try:
        import ast as _a1203c2
        import json as _j1203c2
        from pathlib import Path as _P1203c2
        be = _P1203c2(str(project_dir)) / "app" / "backend"
        ds = _j1203c2.loads((be / "seed_dataset.json").read_text(encoding="utf-8"))
        if not isinstance(ds, dict):
            return {}
        cols = set()
        tree = _a1203c2.parse((be / "models.py").read_text(encoding="utf-8", errors="replace"))
        for node in _a1203c2.walk(tree):
            if not isinstance(node, _a1203c2.ClassDef):
                continue
            for st in node.body:
                if isinstance(st, _a1203c2.Assign) and isinstance(st.value, _a1203c2.Call):
                    fn = getattr(st.value.func, "id", "") or getattr(st.value.func, "attr", "")
                    if fn == "Column":
                        cols.add(getattr(st.targets[0], "id", ""))
        if not cols:
            return {}        # no models parsed -> no claim
        out = {}
        for entity, rows in ds.items():
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                continue
            lost = sorted(k for k in rows[0]
                          if k in _TEXT and k not in cols
                          and any(str(r.get(k) or "").strip() for r in rows[:20]
                                  if isinstance(r, dict)))
            if lost:
                out[str(entity)] = lost
        return out
    except Exception:
        return {}


class SeedAuditCheckTool(_SeedToolBase):
    NAME = "seed_audit_check"
    DESCRIPTION = ("Audit seed data coverage across all registered tables. "
                    "Returns flagged tables with reasons (missing_seed | "
                    "low_row_count | placeholder_content) and details.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry, _project_dir_1202q(self.hub_registry))
        _data1203c1 = report.to_dict()
        if not report.measured:
            # #1203c1: SAY IT WHERE THE AGENT READS. `is_clean: true` sits first in this
            # payload and `measured: false` after it; r145's orchestrator agent read the
            # affirmative one and cancelled the seed-remediation task that would have put the
            # dataset's 35 real captions into `videos.title/description`. The run then held to
            # the end on `primary_dataless`, which never escape-releases. The framework already
            # logs this in words -- the log is the orchestrator's, and the agent reads results.
            _data1203c1["not_checked_1203c1"] = (
                "NOT CHECKED: this audit inspected %d of %d table(s), so `is_clean` carries NO "
                "information here -- it means nothing was looked at, not that nothing is wrong. "
                "This audit only inspects tables still marked `defined`, and almost every run "
                "has none. Do NOT cancel or close seed remediation on this verdict, and do not "
                "report the seed as verified: count rows in the live database instead."
                % (report.examined, report.candidates))
        # #1203c4: `self.hub_registry`, not `self`. The resolver reads `base_dir` off the
        # HUB (its two older call sites in this file both pass `self.hub_registry`); a tool
        # has no `base_dir`, so #1203c2 resolved None, read nothing and never fired once --
        # confirmed on r146, where 19 recorded `seed_audit_check` results carry no such key
        # while the helper called with that run's directory returns {'comments': ['text']}.
        _lost1203c2 = _unmapped_dataset_text_1203c2(
            _project_dir_1202q(self.hub_registry))
        if _lost1203c2:
            # #1203c2: said where the agent reads it. The framework's own seed audit states
            # that "Extra live columns are not reported", so without this the dataset's text
            # is dropped in silence -- 7 of 140 runs, always `caption`, and in r145 it cost the
            # run: wordless videos -> no seed text on `/` -> `primary_dataless`, which never
            # escape-releases. Not repaired here: which column the product means is the lane's
            # to decide, and mapping `caption` onto `description` would be a guess.
            _data1203c1["dataset_text_without_column_1203c2"] = {
                "unmapped": _lost1203c2,
                "note": ("the staged `seed_dataset.json` carries TEXT in field(s) that no "
                         "model Column can hold, so that text is dropped on load and the rows "
                         "arrive with empty columns. Add a column of that name, or rename the "
                         "loader's target to a column you already declare -- do not leave the "
                         "rows wordless: a page rendering content with no text reads as an "
                         "empty shell to the browser walk and holds delivery."),
            }
        return ToolResult.ok(data=_data1203c1)


class ListSeedIssuesTool(_SeedToolBase):
    NAME = "list_seed_issues"
    DESCRIPTION = ("List current seed issues with table+reason pairs. "
                    "Convenience over seed_audit_check for the orchestrator's "
                    "deliver-readiness checklist.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry, _project_dir_1202q(self.hub_registry))
        issues = [
            {"table": f["table"], "reason": f["reason"], "detail": f["detail"]}
            for f in report.flagged_tables
        ]
        # #1202z5: `count: 0` from an audit that INSPECTED NOTHING reads exactly like
        # `count: 0` from one that checked every table, and this is the tool whose own
        # description offers it "for the orchestrator's deliver-readiness checklist".
        #
        # `SeedReport.measured` exists for this — "False when the audit inspected nothing —
        # `is_clean` then carries no information" — and #1023d already put it in `to_dict()`
        # with the note that "a consumer reading is_clean must be able to see whether
        # anything was read". This sibling rebuilt the payload by hand and dropped it.
        # Measured: the audit inspects ZERO tables at some point in 42 of the 158 run logs,
        # including r140 at 03:21 with 11 tables registered — 23 minutes after its M1 was
        # released. So the blind state is not hypothetical.
        #
        # The tool is called 0 times across the 50 runs carrying stage-tool counts (against
        # 2999 `seed_audit_check` calls), so this changes no live behaviour today. It is
        # fixed rather than deleted precisely because it is DEAD: a tool that nobody calls
        # costs a schema, but a tool that would LIE the day somebody calls it costs a wrong
        # delivery decision — and the whole point of #956/#1023d is that "no issues" and
        # "nothing examined" must never look the same.
        return ToolResult.ok(data={
            "issues": issues, "count": len(issues),
            "measured": report.measured, "examined": report.examined,
            "candidates": report.candidates,
        })


_SEED_TOOLS = [RegisterSeedDataTool, SeedAuditCheckTool, ListSeedIssuesTool]


def create_seed_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _SEED_TOOLS]


__all__ = ["RegisterSeedDataTool", "SeedAuditCheckTool", "ListSeedIssuesTool",
            "create_seed_tools"]
