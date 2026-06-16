# Cutover 21 Baseline (Seed Data Sufficiency)

## Test counts
- regressions: 7 OK
- discover: 788 OK

## Gap this cutover closes
Generated apps ship with placeholder seeds (user1/user2/lorem ipsum) or empty
tables. Frontend renders "No items" / "Loading..." against empty DB; RunHub
probes pass but the user sees nothing. No mechanical enforcement of "足够 data".

## Approach
- Database agent self-reports via register_seed_data(table, row_count, sample_excerpt)
- runtime/seed_audit.py validates: registered, row_count >= min_rows, placeholder_score < 0.5
- DeliverProjectTool refuses if any table fails, unless mark_intentionally_dead allowlisted
- force_deliver orchestrator-only bypass (Cutover 19/20 pattern; new event type seed_audit_bypass)

## Threshold defaults
- min_seed_rows: 5 (per table; override via metadata.min_seed_rows or 0 to opt out)
- placeholder_score floor: 0.5 (multiple placeholder markers required to fail)
