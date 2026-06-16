# Cutover 14 Baseline (Design Review Stage)

## Test counts
- regressions: 7 OK
- discover: 534 OK

## Gap this cutover closes
Today nothing checks the *design* before backend/database/frontend start
implementing. Cutover 13 caught rubber-stamp PR reviews, but a wrong design
still makes it to three parallel implementations. This cutover adds a
mandatory architect-reviewer hop with >=3-challenge requirement, and a
structural gate that blocks downstream agents from starting on un-approved
designs.

## Existing surfaces we extend
- WorkHub.create_page(kind=, ...) and list_pages(kind=, status=) exist
- Page schema has kind + status fields
- HubTool framework + agent profile pattern reusable from Cutovers 10-13
- 11 existing profiles; adding 12th (architect_reviewer)

## Lifecycle
draft -> under_review -> approved | needs_revision
