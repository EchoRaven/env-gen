r"""#1202sc: `1` and `'1'` are the same row, and #807b treated them as different id spaces.

`#1202ry` fixed the refusals caused by a dataset carrying NO ids. This is the other half of
the same guard's arithmetic. r103, r125 and r55 declare a TEXT primary key, so `#808` aligns
the DATASET's ids to text ('1', '2', '3'); nothing aligns the LANE's dependent FK values,
which stay integers. `#807b` then compared `1 not in {'1','2',...}`, found every dependent row
orphaned, and refused a swap where the two sources agreed on every id.

Postgres coerces on insert, so those rows resolve to the same records once seeded. The
difference was never in the data -- only in the JSON types the two sources happened to write.

4 corpus runs are in this state after #1202ry, worth 67 real rows. Small, and the fix is
nearly free: compare the ids as text. The 18 runs whose lane really does key on slugs
('v_demo_first' against '1') are still refused, which is #807b doing its job.

THESE TESTS RUN THE EMITTED CODE. The guard lives inside a string template that becomes the
app's own seed_data.py, so a test that re-implements it proves only that I can write the same
thing twice -- and `#1202ry` shipped exactly such a mirror. The helper below lifts the block
out of the rendered module and executes it, so what is asserted is what ships.
"""
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_seed_data


def emitted_807b_guard():
    """The `#807b` refusal block, lifted out of the module the framework actually emits."""
    lines = render_seed_data({"users": [{"id": 1}]}).splitlines()
    starts = [n for n, l in enumerate(lines) if l.strip() == "_refused = set()"]
    assert len(starts) == 1, "the #807b block moved or was duplicated; re-anchor this helper"
    begin = starts[0]
    loops = [n for n, l in enumerate(lines)
             if l.strip().startswith("for _t, _rows in real.items():") and n > begin]
    assert len(loops) >= 2, "the block no longer ends at the second real.items() loop"
    return textwrap.dedent("\n".join(lines[begin:loops[1]]))


def refuses(real, base):
    ns = {"real": real, "base": base}
    exec(compile(emitted_807b_guard(), "<807b>", "exec"), ns)  # noqa: S102 - the point
    return ns["_refused"]


# --- the same ids, written two ways ---------------------------------------------------

def test_a_text_key_and_an_integer_fk_are_the_same_row():
    """r103/r125: models declare `videos.id TEXT`, #808 writes '1', the lane's likes say 1."""
    assert refuses({"videos": [{"id": "1"}, {"id": "2"}]},
                   {"likes": [{"video_id": 1}, {"video_id": 2}]}) == set()


def test_and_the_other_way_round():
    """r55: the dataset's ids are integers and the lane's fk values are strings."""
    assert refuses({"videos": [{"id": 1}, {"id": 2}]},
                   {"likes": [{"video_id": "1"}, {"video_id": "2"}]}) == set()


# --- and a conflict that is real ------------------------------------------------------

def test_a_lane_keyed_on_slugs_is_still_refused():
    """r145's case, and r112's: 'movie-hollowfield' is not 1 however you spell it."""
    assert refuses({"titles": [{"id": "1"}, {"id": "2"}]},
                   {"episodes": [{"title_id": "movie-hollowfield"},
                                 {"title_id": "movie-atlas"}]}) == {"titles"}


def test_a_minority_of_stale_links_is_not_a_conflict():
    """#807b judges on the MAJORITY -- a few unresolved rows are genuinely stale links."""
    assert refuses({"videos": [{"id": i} for i in range(1, 6)]},
                   {"likes": [{"video_id": 1}, {"video_id": 2},
                              {"video_id": 999}]}) == set()


def test_a_table_with_no_dependents_is_never_refused():
    assert refuses({"videos": [{"id": 1}]}, {"unrelated": [{"x": 1}]}) == set()


def test_a_null_fk_is_not_an_orphan():
    assert refuses({"videos": [{"id": 1}]},
                   {"likes": [{"video_id": None}, {"video_id": 1}]}) == set()


# --- the shape of the block itself ----------------------------------------------------

def test_the_guard_compares_ids_as_text():
    """The one line this fix turns on. If it reverts, every test above still needs to fail --
    but this says which line to look at."""
    block = emitted_807b_guard()
    assert "_new_ids = {str(_r.get('id'))" in block
    assert "if str(_d.get(_fk)) not in _new_ids:" in block


def test_the_emitted_module_still_compiles():
    import ast

    ast.parse(render_seed_data({"users": [{"id": 1, "name": "a"}],
                                "comments": [{"id": 1, "user_id": 1}]}))
