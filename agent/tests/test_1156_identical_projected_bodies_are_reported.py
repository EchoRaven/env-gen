"""#1156: two endpoints that project a byte-identical body are a contract gap.

netflix-local-r13 DELIVERED and then answered the same 60 rows for /api/titles,
/api/titles/trending and /api/titles/top10.  #1155 fixes top10 -- a `top10_rank`
column exists to rank by.  `trending` has NO backing column, so there is nothing
to project and inventing an ordering would be a guess: the CONTRACT is what is
incomplete, and only the lane can close it.

Detected structurally rather than from a word list -- enumerating "ranked
sounding" segments (trending / popular / featured) would be guessing at English.
Reported, never enforced: a duplicate list is a quality defect, not a broken app,
and a false blocker costs a whole run (#566j).
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
from env_generator.llm_generator.multi_agent.runtime import route_projector as rp

SRC = Path(rp.__file__).read_text(encoding="utf-8")


def _detector_body():
    """Anchor on the ticket, stop at the return it precedes (#943)."""
    i = SRC.index("# #1156: TWO ENDPOINTS")
    return SRC[i:SRC.index('return {"projected"', i)]


def test_the_detector_ignores_the_path_bearing_lines():
    """The decorator and def line carry the path and the index, so every handler
    differs there -- comparing them would find nothing, ever."""
    b = _detector_body()
    assert "_ls[2:]" in b, "must drop @app.<verb>(path) and def <name>(...)"


def test_it_only_compares_db_reading_handlers():
    b = _detector_body()
    assert '"db.query(" not in _body' in b


def test_it_uses_no_word_list():
    """A list of ranked-sounding segments would be guessing at English."""
    for word in ("trending", "popular", "featured", "recommended"):
        assert ('"%s"' % word) not in _detector_body()


def test_the_result_carries_the_finding():
    b = _detector_body()
    assert "_dupes_1156" in b
    i = SRC.index('return {"projected"', SRC.index("# #1156: TWO ENDPOINTS"))
    assert "identical_bodies_1156" in SRC[i:SRC.index("\n\n", i)]


def test_the_detector_cannot_break_the_projection():
    b = _detector_body()
    assert "except Exception" in b and "_dupes_1156 = []" in b


def test_the_caller_makes_it_visible_without_blocking():
    h = Path(hp.__file__).read_text(encoding="utf-8")
    i = h.index("#1156 name the endpoints") if "#1156 name the endpoints" in h \
        else h.index("# #1156: name the endpoints")
    seg = h[i:h.index("except Exception", i)]
    assert "identical_bodies_1156" in seg
    assert "_logger.warning" in seg
    # never a gate check
    assert "failed_checks" not in seg
