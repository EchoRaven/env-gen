"""Visual review gate — production aggregator over the visual_review
pages held by ``GateRegistry``.

Scope after PR 3 of the hub-responsibility-split plan
(``docs/hub_responsibility_split_plan.md``, rank 3):
  * ``VisualReviewNotApprovedError`` — exception class used by
    ``DeliverProjectTool`` when delivery is refused.
  * ``list_unapproved_critical`` — the production visual-review
    gate; ``DeliverProjectTool.execute`` calls it immediately
    before delivery to refuse if any critical route lacks an
    approved visual review.

Removed in PR 3 (re-audit §7.3 confirmed dead):
  * ``is_visual_approved`` (single-page predicate delegate)
  * ``assert_visual_approved`` (single-page exception wrapper)
  * ``assert_critical_visuals_approved`` (multi-page exception
    wrapper — ``DeliverProjectTool`` calls
    ``list_unapproved_critical`` directly and never caught this).

The corresponding ``WorkHub.is_visual_approved`` predicate was
also removed; the gate state is checked by reading
``page.get("status") == "approved"`` on the page returned from
``GateRegistry.list_critical_visual_reviews()``.

This module accepts BOTH a ``GateRegistry`` and a ``WorkHub`` as
the ``source`` argument — both expose ``list_critical_visual_reviews``
during the PR 3 delegate window. After Phase E, every external
caller passes the GateRegistry directly; the WorkHub delegate is
removed.
"""

from __future__ import annotations


class VisualReviewNotApprovedError(RuntimeError):
    pass


def list_unapproved_critical(source) -> list:
    """Return all visual_review pages with critical=True and
    status != 'approved'. ``source`` is either a ``GateRegistry``
    or a ``WorkHub`` — both expose ``list_critical_visual_reviews``."""
    if source is None or not hasattr(source, "list_critical_visual_reviews"):
        return []
    out = []
    for page in source.list_critical_visual_reviews():
        if page.get("status") != "approved":
            out.append(page)
    return out


__all__ = [
    "VisualReviewNotApprovedError",
    "list_unapproved_critical",
]
