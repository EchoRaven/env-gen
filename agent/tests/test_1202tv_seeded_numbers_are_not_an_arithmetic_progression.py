r"""#1202tv: every numeric seed column shipped a perfect arithmetic progression.

`_seed_number` chose a value per column by NAME and then computed it linearly in the row
index -- `(i + 1) * 137 % 4000 + 120`, `(i + 1) * 53 % 600 + 30`, `(i * 7 + 3) % 40`. A seed
is five or six rows, so the modulo never wrapped and the output was an exact arithmetic
sequence every time.

MEASURED in a delivered environment (tiktok-r107), not inferred:

    users.followers      [257, 394, 531, 668, 805]        step 137
    users.likes          [257, 394, 531, 668, 805]        step 137   <- the SAME sequence
    live_rooms.viewers   [257, 394, 531, 668, 805, 942]   step 137   <- and again
    sounds.video_count   [3, 10, 17, 24, 31, 38]          step 7

Three unrelated columns carrying one identical sequence, and one subtraction exposes all of
it. This is dimension 6 (numeric / ID regularity) of the realism rubric the pipeline is now
held to, and it matters beyond aesthetics: an agent that concludes the environment is
synthetic behaves differently, which corrupts the signal such environments exist to measure.

`zlib.crc32` and not `hash()`: str hashing is salted per process, and the generated loader
replays the whole table when the seed fingerprint changes, so a render that differed between
processes would wipe and reload on every boot. Same constraint #1202rw worked under.

TWO THINGS DELIBERATELY NOT CHANGED, because scattering them would be the worse error:
  * `position` / `rank` / `order` / `index` stay `i + 1` -- a rank column IS sequential in a
    real table, and a scattered one would contradict the list order it describes.
  * every band stays where it was (#74: `unread_count = 1773` was the bug that put the bands
    there in the first place).

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _seed_number, _seed_spread_1202tv, render_seed_data,
)

SEQUENTIAL_BY_DESIGN = ("position", "rank", "order", "index", "priority", "page", "sort", "step")


def _cols(*names):
    return {"columns": [{"name": "id", "type": "integer", "primary_key": True}]
            + [{"name": n, "type": "integer"} for n in names]}


def _seed_of(tables):
    tree = ast.parse(render_seed_data(tables, {}))
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SEED":
            return ast.literal_eval(n.value)
    raise AssertionError("_SEED is gone")


def _is_progression(vals):
    if len(vals) < 3 or len(set(vals)) < 3:
        return False
    steps = {vals[i + 1] - vals[i] for i in range(len(vals) - 1)}
    return len(steps) == 1


def test_no_numeric_column_is_an_arithmetic_progression():
    """The bug, stated as the property: r107's four columns were all exactly this."""
    seed = _seed_of({"users": _cols("followers", "likes", "score", "viewers"),
                     "videos": _cols("views", "duration", "video_count", "price"),
                     "items": _cols("unread_count", "total", "quantity")})
    bad = []
    for table, rows in seed.items():
        if not isinstance(rows, list) or len(rows) < 3:
            continue
        for col in rows[0]:
            vals = [r.get(col) for r in rows]
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
                continue
            if _is_progression(vals):
                bad.append(f"{table}.{col} = {vals}")
    assert bad == [], "these seed an arithmetic progression: %s" % bad


def test_two_columns_of_the_same_shape_do_not_share_a_sequence():
    """r107's sharpest form: followers, likes and viewers were byte-identical lists."""
    seed = _seed_of({"users": _cols("followers", "likes", "views", "subscribers")})
    rows = seed["users"]
    series = {c: tuple(r.get(c) for r in rows) for c in ("followers", "likes", "views",
                                                         "subscribers")}
    assert len(set(series.values())) == len(series), series


def test_a_rank_column_stays_sequential():
    """The discriminator. Scattering this would be a worse tell than leaving it."""
    seed = _seed_of({"charts": _cols("rank", "position", "sort_order")})
    for col in ("rank", "position", "sort_order"):
        vals = [r.get(col) for r in seed["charts"]]
        assert vals == list(range(1, len(vals) + 1)), (col, vals)


def test_the_bands_are_unchanged():
    """#74: the bands exist because one formula gave `unread_count = 1773`. Keep them."""
    for i in range(24):
        assert 1 <= _seed_number("rating", i) <= 5
        assert 2018 <= _seed_number("year", i) <= 2024
        assert 120 <= _seed_number("follower_count", i) <= 4100
        assert 0 <= _seed_number("score", i) <= 99
        assert 3 <= _seed_number("unread_count", i) <= 39
        assert 30 <= _seed_number("duration_seconds", i) <= 630
        assert _seed_number("price", i) % 10 == 9        # retail shape, not a round amount


def test_the_spread_is_stable_across_processes():
    """★ The constraint that rules out `hash()`.

    The generated loader replays the WHOLE table when the seed fingerprint changes, so a
    render that differed per process would TRUNCATE and reload on every boot -- taking the
    test users' data with it. Asserted by rendering in subprocesses under different
    PYTHONHASHSEED values and comparing bytes, because that is the only way a salted hash
    shows up at all.
    """
    script = (
        "import sys,hashlib;sys.path.insert(0,%r);sys.path.insert(0,%r);"
        "from multi_agent.runtime.backend_skeleton import render_seed_data;"
        "C=lambda *n:{'columns':[{'name':'id','type':'integer','primary_key':True}]"
        "+[{'name':x,'type':'integer'} for x in n]};"
        "print(hashlib.sha256(render_seed_data({'u':C('followers','likes'),"
        "'v':C('views','price')},{}).encode()).hexdigest())" % (str(ROOT), str(LLM_DIR)))
    digests = set()
    for seed_env in ("0", "1", "12345"):
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                             env={"PYTHONHASHSEED": seed_env, "PATH": "/usr/bin:/bin"},
                             timeout=120)
        assert out.returncode == 0, out.stderr[-600:]
        digests.add(out.stdout.strip())
    assert len(digests) == 1, f"render differs across PYTHONHASHSEED: {digests}"


def test_the_spread_helper_stays_inside_its_band():
    for i in range(200):
        v = _seed_spread_1202tv("anycol", i, 7, 11)
        assert 7 <= v <= 11, v
    assert len({_seed_spread_1202tv("c", i, 0, 999) for i in range(40)}) > 25, "too clustered"
