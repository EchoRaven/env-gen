r"""#1203fe: #1203f1 kept ONE transcript per verb, so a second failure erased the first.

Found by reading what #1203f1 produced on a live run rather than by re-reading its code.

r156 failed `build` twice, at 22:08:31 and 22:41:37. Both log lines point at
`compose_build_failure_1203f1.log`, and the file holds only the 22:41 run. A pointer to a
file whose contents have since been replaced is the shape this whole series removed, rebuilt
inside the patch that removed it.

It cost a diagnosis, not just tidiness. The surviving transcript ends in

    archive/tar: missed writing 12934618 bytes
    Can't close tar writer: archive/tar: missed writing 12934618 bytes
    Error response from daemon: Error processing tar file(exit status 1): unexpected EOF

and the same byte count on BOTH lines says the receiving end went away rather than that a
file shrank under the tar writer. Separating a progressive cause (space filling across the
run) from a one-off (the daemon dropping one stream) needs the FIRST failure to compare
against, and for r156 that transcript is gone. The cause of r156 losing its second milestone
is therefore recorded as undiagnosed, which is the honest state and the reason for this fix.

Second flaw, same site: the verb went into the name raw, so `up -d --remove-orphans` produced
`compose_up -d --remove-orphans_failure_1203f1.log` -- a filename with spaces that an ordinary
`compose_*_failure_1203f1.log` glob does not match, which is how I failed to find it at first.

The first failure keeps the plain name, so every existing reader and #1203f1's own tests are
unaffected; later ones take an attempt number and sort in the order they happened.
"""
import ast
import inspect
import os
import sys
import tempfile
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import validation_runner as VR  # noqa: E402


def _d():
    return Path(tempfile.mkdtemp())


class TestTheNameIsSafe:
    def test_a_verb_with_spaces_and_dashes_becomes_one_token(self):
        p = VR._transcript_path_1203fe(_d(), "up -d --remove-orphans")
        assert " " not in p.name, p.name
        assert p.name.startswith("compose_up"), p.name
        assert p.name.endswith("_failure_1203f1.log"), p.name

    def test_a_plain_verb_keeps_the_name_1203f1_used(self):
        """Existing readers and #1203f1's tests look for exactly this."""
        p = VR._transcript_path_1203fe(_d(), "build")
        assert p.name == "compose_build_failure_1203f1.log", p.name

    def test_a_missing_verb_falls_back_to_cmd(self):
        for verb in (None, "", "   ", "///"):
            p = VR._transcript_path_1203fe(_d(), verb)
            assert p.name == "compose_cmd_failure_1203f1.log", (verb, p.name)

    def test_an_absurd_verb_cannot_produce_an_unbounded_name(self):
        p = VR._transcript_path_1203fe(_d(), "x" * 500)
        assert len(p.name) < 80, len(p.name)


class TestEveryFailureIsKept:
    def test_the_second_failure_does_not_overwrite_the_first(self):
        d = _d()
        first = VR._transcript_path_1203fe(d, "build")
        first.write_text("cause-of-22:08", encoding="utf-8")
        second = VR._transcript_path_1203fe(d, "build")
        assert second != first, second
        second.write_text("cause-of-22:41", encoding="utf-8")
        assert first.read_text(encoding="utf-8") == "cause-of-22:08", "the first was erased"
        assert second.read_text(encoding="utf-8") == "cause-of-22:41"

    def test_the_names_sort_in_the_order_the_failures_happened(self):
        d = _d()
        names = []
        for i in range(4):
            p = VR._transcript_path_1203fe(d, "build")
            p.write_text("failure-%d" % i, encoding="utf-8")
            names.append(p.name)
        assert names == sorted(names), names
        assert len(set(names)) == 4, names

    def test_different_verbs_do_not_share_a_counter(self):
        d = _d()
        VR._transcript_path_1203fe(d, "build").write_text("b1", encoding="utf-8")
        VR._transcript_path_1203fe(d, "build").write_text("b2", encoding="utf-8")
        up = VR._transcript_path_1203fe(d, "up")
        assert up.name == "compose_up_failure_1203f1.log", up.name


class TestTheCallerUsesIt:
    """A helper nothing calls is the defect it was written to fix (#1203e7's lesson, and
    the three-way check from `feedback_i_tested_the_helper_not_its_caller`)."""

    def _save_block(self):
        src = inspect.getsource(VR)
        i = src.index("_saved_1203f1 = ")
        j = src.index("transcript tail:", i)
        return src[i:j]

    def test_the_save_site_calls_the_helper(self):
        assert "_transcript_path_1203fe(" in self._save_block(), \
            "the transcript path is being built some other way"

    def test_the_save_site_no_longer_builds_the_name_itself(self):
        block = "\n".join(ln for ln in self._save_block().split("\n")
                          if not ln.lstrip().startswith("#"))
        assert "compose_%s_failure" not in block, \
            "the old inline name construction is still there, so one of the two paths is dead"

    def test_the_write_uses_what_the_helper_returned(self):
        """Position matters: computing the path and then writing somewhere else is the same
        bug with extra steps."""
        block = self._save_block()
        assert block.index("_transcript_path_1203fe(") < block.index(".write_text("), block
