r"""#1203ob: `#1202w7`'s evidence has a recorder, and the ledger exists in 0 of 106 runs.

`run_created_actor_rows_1202w7` counts how much of the delivered actor table the run wrote
itself, and `record_run_created_actor_rows_1202w7` lands it in an artifact "to be the evidence
a future cleanup decision is made on, exactly as #1202w4 is for #351". Both are referenced
only by their tests, and `logs/run_created_actor_rows_1202w7.jsonl` exists in 0 of the
corpus's 106 runs -- so that evidence has never been written.

WIRING IT LOOKS LIKE A ONE-LINER AND IS NOT, because the framework never holds both halves of
the measurement at once:

  * at GATE time the reading's own `live_row_counts_1039` cannot reach the database -- the
    stack is cycled around each validation and #1202dj measured 2728 of 2728 attempts failing
    -- so a direct wiring reads `{}` forever;
  * the #1202dj fallback snapshot IS available (61 runs carry
    `shared/seed_live_counts_1202dj.json` with real counts) but it is taken at
    `backend_health`, just after `down -v && up` + seed, when the actor table is FRESH.

MEASURED on that snapshot across the 61 runs that carry it: added share median 0%, max 47%
(r182 8 of 17, googlemaps-r16 5 of 11, r190 6 of 15), and ZERO runs at 50% or above. The 90%
and 97% in #1202w7's own comment came from stacks left RUNNING long after their run -- a state
the framework never observes. So wiring the recorder to `_live` would be a systematic
under-report of the very thing being counted, not a cheap win.

This file pins that reason. It is a ratchet on a PARKED decision, the practice #1203oa
established after #644's recorded range was found to describe 0 of 406 images.
"""
import json
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.seed_audit import (
    record_run_created_actor_rows_1202w7 as record,
    run_created_actor_rows_1202w7 as reading,
)


def _snapshot_readings(corpus):
    """(run, delivered, seeded, added, share) from each #1202dj snapshot, TTL ignored.

    The audit's own call applies a 1800s TTL, correctly -- a stale count must not drive a
    verdict. Reading the file directly is what lets the snapshot MOMENT be measured after the
    fact, which is the claim this file exists to pin.
    """
    out = []
    for f in sorted(corpus.glob("*/shared/seed_live_counts_1202dj.json")):
        run = f.parts[-3]
        try:
            counts = (json.loads(f.read_text(encoding="utf-8")) or {}).get("counts") or {}
        except Exception:
            continue
        delivered = int(counts.get("users") or 0)
        seeded = 0
        for name in ("seed_dataset.json", "seed_data.json"):
            p = corpus / run / "app" / "backend" / name
            if not p.is_file():
                continue
            try:
                rows = (json.loads(p.read_text(encoding="utf-8", errors="ignore"))
                        or {}).get("users")
            except Exception:
                continue
            if isinstance(rows, list):
                seeded = max(seeded, len(rows))
        if delivered <= 0 or seeded <= 0:
            continue
        added = max(0, delivered - seeded)
        out.append((run, delivered, seeded, added, added / delivered))
    return out


class TheRecorderIsStillUncalledByDesign(unittest.TestCase):
    def test_both_halves_exist_and_are_callable(self):
        """They are kept, not deleted: the arithmetic is right and only the MOMENT is
        missing, so a future delivery-time count can use them unchanged."""
        self.assertTrue(callable(reading))
        self.assertTrue(callable(record))

    def test_the_recorder_refuses_a_reading_that_is_not_one(self):
        """#1039's invariant: an empty result means NOT MEASURED and must not be landed as
        if it were a measurement."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(record(d, {}))
            self.assertFalse(record(d, None))
            self.assertFalse(record(d, {"delivered": 0}))
            self.assertFalse(record(None, {"delivered": 5}))
            self.assertFalse(list(Path(d).rglob("run_created_actor_rows_1202w7.jsonl")))

    def test_the_recorder_writes_when_given_a_real_reading(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(record(d, {"table": "users", "delivered": 17, "seeded": 9,
                                       "added_by_run": 8, "share": 0.4706}))
            led = Path(d) / "logs" / "run_created_actor_rows_1202w7.jsonl"
            self.assertTrue(led.is_file())
            rec = json.loads(led.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(rec["added_by_run"], 8)
            self.assertIn("at", rec)

    def test_the_reading_returns_nothing_without_a_live_database(self):
        """The gate-time reality #1202dj measured at 2728 of 2728: no container, no count.
        This is why a direct wiring would read {} forever."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(reading(d, timeout=1), {})


class TheSnapshotMomentIsWhyItIsNotWired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")
        cls.rows = _snapshot_readings(cls.corpus)
        if len(cls.rows) < 10:
            raise unittest.SkipTest("too few #1202dj snapshots on this disk")

    def test_the_ledger_was_never_written(self):
        """If this starts failing, someone wired it -- and the first thing to check is
        whether the moment problem below was solved or just ignored."""
        found = sorted(p.parts[-3] for p in
                       self.corpus.glob("*/logs/run_created_actor_rows_1202w7.jsonl"))
        self.assertEqual(found, [], "the #1202w7 ledger now exists in %s" % found)

    def test_the_snapshot_sees_a_freshly_seeded_table(self):
        """The measured reason: at `backend_health` the run's own users have not arrived.
        Median added-share ~0 and nothing at or above 50%."""
        import statistics
        shares = [r[4] for r in self.rows]
        self.assertLess(statistics.median(shares), 0.10,
                        "the snapshot now shows real accumulation (median %.2f), so the "
                        "moment problem may be gone and #1202w7 could be wired after all"
                        % statistics.median(shares))
        self.assertEqual([r[0] for r in self.rows if r[4] >= 0.50], [],
                         "a snapshot reached 50%% added share, which the 61-run measurement "
                         "never did")

    def test_it_is_not_vacuous_some_accumulation_is_visible(self):
        """Non-vacuity: if every share were exactly 0 the assertion above would hold for a
        trivial reason (e.g. the snapshot stopped carrying `users` at all)."""
        self.assertTrue([r for r in self.rows if r[3] > 0],
                        "no snapshot shows ANY added row, so this file is measuring nothing")

    def test_the_hand_measured_shares_are_not_reproducible_from_a_snapshot(self):
        """#1202w7 recorded 90% (r126) and 97% (netflix-r30) from long-lived stacks. The
        snapshot path cannot reach those numbers, which is the whole point."""
        self.assertLess(max(r[4] for r in self.rows), 0.90)


if __name__ == "__main__":
    unittest.main()
