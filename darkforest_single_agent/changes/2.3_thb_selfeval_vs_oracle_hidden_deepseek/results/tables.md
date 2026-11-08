### Job 1 (selfval, oracle observable): official validation per iteration

| Iter | Passed | Checks OK | Chain OK | Endpoints 2xx | validate calls | wall (min) | Hidden API | Hidden UI | Visual | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | True | 14/14 | 8/8 | 11/15 | 4 | 12.8 | 49/49 | 4/5 | None | hidden errors: visual_capture |
| 2 | True | 14/14 | 8/8 | 11/15 | 2 | 5.6 |  |  |  |  |
| 3 | True | 14/14 | 8/8 | 11/15 | 2 | 1.5 |  |  |  |  |
| 4 | True | 14/14 | 8/8 | 11/15 | 1 | 1.2 | 49/49 | 4/5 | None | hidden errors: visual_capture |
| 5 | True | 14/14 | 8/8 | 11/15 | 2 | 1.6 |  |  |  |  |
| 6 | True | 14/14 | 8/8 | 11/15 | 1 | 0.8 |  |  |  |  |
| 7 | True | 14/14 | 8/8 | 11/15 | 1 | 0.8 |  |  |  |  |
| 8 | True | 14/14 | 8/8 | 11/15 | 1 | 0.9 | 49/49 | 4/5 | None | hidden errors: visual_capture |
| 9 | True | 14/14 | 8/8 | 11/15 | 2 | 1.3 |  |  |  |  |
| 10 | True | 14/14 | 8/8 | 14/15 | 1 | 0.7 |  |  |  |  |
| 11 | True | 14/14 | 8/8 | 14/15 | 2 | 1.5 |  |  |  |  |
| 12 | True | 14/14 | 8/8 | 15/15 | 1 | 0.6 | 47/49 | 4/5 | None | hidden errors: visual_capture |
| 13 | True | 14/14 | 8/8 | 15/15 | 1 | 0.8 |  |  |  |  |
| 14 | True | 14/14 | 8/8 | 15/15 | 1 | 1.1 |  |  |  |  |
| 15 | True | 14/14 | 8/8 | 15/15 | 1 | 1.0 |  |  |  |  |
| 16 | True | 14/14 | 8/8 | 15/15 | 1 | 1.3 | 47/49 | 4/5 | None | hidden errors: visual_capture |
| 17 | True | 14/14 | 8/8 | 15/15 | 2 | 1.3 |  |  |  |  |
| 18 | True | 14/14 | 8/8 | 15/15 | 2 | 1.5 |  |  |  |  |
| 19 | True | 14/14 | 8/8 | 15/15 | 1 | 0.8 |  |  |  |  |
| 20 | True | 14/14 | 8/8 | 15/15 | 1 | 0.7 | 47/49 | 4/5 | None | hidden errors: visual_capture |

### Job 2 (oracle hidden): dev evaluation (shown to the agent) and hidden evaluation per iteration

| Iter | Dev passed | Checks OK | Chain OK | Endpoints 2xx | wall (min) | Hidden API | Hidden UI | Visual (screens) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | False | 13/14 | 5/8 | 11/15 | 25.5 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 2 | True | 14/14 | 7/8 | 11/15 | 4.2 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 3 | True | 14/14 | 8/8 | 11/15 | 3.8 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 4 | True | 14/14 | 8/8 | 11/15 | 3.7 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 5 | True | 14/14 | 8/8 | 11/15 | 2.6 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 6 | True | 14/14 | 8/8 | 11/15 | 1.7 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 7 | True | 14/14 | 8/8 | 11/15 | 2.9 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 8 | True | 14/14 | 8/8 | 11/15 | 6.8 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 9 | True | 14/14 | 8/8 | 11/15 | 1.9 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 10 | True | 14/14 | 8/8 | 11/15 | 2.2 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 11 | True | 14/14 | 8/8 | 11/15 | 2.5 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 12 | True | 14/14 | 8/8 | 11/15 | 2.4 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 13 | True | 14/14 | 8/8 | 11/15 | 1.4 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 14 | True | 14/14 | 8/8 | 11/15 | 0.1 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 15 | True | 14/14 | 8/8 | 11/15 | 2.1 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 16 | True | 14/14 | 8/8 | 11/15 | 0.8 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 17 | True | 14/14 | 8/8 | 11/15 | 0.5 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 18 | True | 14/14 | 8/8 | 11/15 | 0.5 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 19 | True | 14/14 | 8/8 | 11/15 | 0.3 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |
| 20 | True | 14/14 | 8/8 | 11/15 | 0.1 | 49/49 | 4/5 | — | hidden errors: visual_capture; static: fabricated_field_fallback |

Totals (agent wall hours, final cumulative output tokens are in status.json): selfval 0.63 h, hidden 1.1 h
