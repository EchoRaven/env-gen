r"""#1202at: the projector/lane tug-of-war must reach the one agent that can end it.

#951 already DETECTS the loop and says so plainly — *"that this repeats is waste either
way"* — and then clobbers anyway and tells nobody. r32:

    20:27:00 [E] SCAFFOLD LOOP (projection): GenresPage has now been replaced 3 times
                 this run — the lane rewrites it and the projector overwrites it
    23:18:10 [E] SCAFFOLD LOOP: LoginPage has now been overwritten 3 times this run

The lane cannot see that its work is discarded, so it rewrites the page and loses it
again. #939's own docstring settles what is and is not in question here: which page
SHOULD win is #914's decision, but "that nineteen rounds of lane work were written and
discarded is not a question — it is waste, whatever the answer."

The exit is a fact only the framework holds: #914/#1020 KEEPS a lane page that imports
`../components/` and REPLACES one that does not. So the lane can keep every line by
moving the body into a component. Telling it that is the whole fix — no policy change,
no judge weakened, and the projection still wins for the stubs it was built for.
"""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    scaffold_loop_pages_1202at, scaffold_pages_from_contract)

_UI_PAGES = [{"component": "GenresPage", "route": "/genres", "name": "Genres"}]


def _design():
    """A tmp tree has no design file, so without this the projector produces no candidate
    and never reaches the clobber branch — every assertion below would pass vacuously,
    which is exactly what the first version of this test did (the same trap #902 records)."""
    return {"screens": [
        {"name": "genres", "route": "/genres", "kind": "page",
         "components": [{"id": "row1-carousel", "role": "first content row of 5 title cards"},
                        {"id": "row2-carousel", "role": "second content row of 5 title cards"}]},
    ]}

# A lane page the projector will actually take: it must be LONGER than the projection
# (`_ex_n > _cd_n`, the gate that made the first fixture miss this branch entirely) and it
# must NOT import `../components/`, which is the shape #914/#1020 defers to. r32's real
# case was 138 lane lines replaced by a 66-line projection.
# #1202pj: a lane page with behaviour (a fetch, a relative import) is now deferred to, not
# clobbered, so the loop this test drives is the one that remains: a static page.
_LANE_PAGE = """export default function GenresPage() {
  return (
    <ul className="genres">
      <li key="1">Genre row 1</li>
      <li key="2">Genre row 2</li>
      <li key="3">Genre row 3</li>
      <li key="4">Genre row 4</li>
      <li key="5">Genre row 5</li>
      <li key="6">Genre row 6</li>
      <li key="7">Genre row 7</li>
      <li key="8">Genre row 8</li>
      <li key="9">Genre row 9</li>
      <li key="10">Genre row 10</li>
      <li key="11">Genre row 11</li>
      <li key="12">Genre row 12</li>
      <li key="13">Genre row 13</li>
      <li key="14">Genre row 14</li>
      <li key="15">Genre row 15</li>
      <li key="16">Genre row 16</li>
      <li key="17">Genre row 17</li>
      <li key="18">Genre row 18</li>
      <li key="19">Genre row 19</li>
      <li key="20">Genre row 20</li>
      <li key="21">Genre row 21</li>
      <li key="22">Genre row 22</li>
      <li key="23">Genre row 23</li>
      <li key="24">Genre row 24</li>
      <li key="25">Genre row 25</li>
      <li key="26">Genre row 26</li>
      <li key="27">Genre row 27</li>
      <li key="28">Genre row 28</li>
      <li key="29">Genre row 29</li>
      <li key="30">Genre row 30</li>
      <li key="31">Genre row 31</li>
      <li key="32">Genre row 32</li>
      <li key="33">Genre row 33</li>
      <li key="34">Genre row 34</li>
      <li key="35">Genre row 35</li>
      <li key="36">Genre row 36</li>
      <li key="37">Genre row 37</li>
      <li key="38">Genre row 38</li>
      <li key="39">Genre row 39</li>
      <li key="40">Genre row 40</li>
      <li key="41">Genre row 41</li>
      <li key="42">Genre row 42</li>
      <li key="43">Genre row 43</li>
      <li key="44">Genre row 44</li>
      <li key="45">Genre row 45</li>
      <li key="46">Genre row 46</li>
      <li key="47">Genre row 47</li>
      <li key="48">Genre row 48</li>
      <li key="49">Genre row 49</li>
      <li key="50">Genre row 50</li>
      <li key="51">Genre row 51</li>
      <li key="52">Genre row 52</li>
      <li key="53">Genre row 53</li>
      <li key="54">Genre row 54</li>
      <li key="55">Genre row 55</li>
      <li key="56">Genre row 56</li>
      <li key="57">Genre row 57</li>
      <li key="58">Genre row 58</li>
      <li key="59">Genre row 59</li>
      <li key="60">Genre row 60</li>
      <li key="61">Genre row 61</li>
      <li key="62">Genre row 62</li>
      <li key="63">Genre row 63</li>
      <li key="64">Genre row 64</li>
      <li key="65">Genre row 65</li>
      <li key="66">Genre row 66</li>
      <li key="67">Genre row 67</li>
      <li key="68">Genre row 68</li>
      <li key="69">Genre row 69</li>
      <li key="70">Genre row 70</li>
      <li key="71">Genre row 71</li>
      <li key="72">Genre row 72</li>
      <li key="73">Genre row 73</li>
      <li key="74">Genre row 74</li>
      <li key="75">Genre row 75</li>
      <li key="76">Genre row 76</li>
      <li key="77">Genre row 77</li>
      <li key="78">Genre row 78</li>
      <li key="79">Genre row 79</li>
      <li key="80">Genre row 80</li>
      <li key="81">Genre row 81</li>
      <li key="82">Genre row 82</li>
      <li key="83">Genre row 83</li>
      <li key="84">Genre row 84</li>
      <li key="85">Genre row 85</li>
      <li key="86">Genre row 86</li>
      <li key="87">Genre row 87</li>
      <li key="88">Genre row 88</li>
      <li key="89">Genre row 89</li>
      <li key="90">Genre row 90</li>
      <li key="91">Genre row 91</li>
      <li key="92">Genre row 92</li>
      <li key="93">Genre row 93</li>
      <li key="94">Genre row 94</li>
      <li key="95">Genre row 95</li>
      <li key="96">Genre row 96</li>
      <li key="97">Genre row 97</li>
      <li key="98">Genre row 98</li>
      <li key="99">Genre row 99</li>
      <li key="100">Genre row 100</li>
      <li key="101">Genre row 101</li>
      <li key="102">Genre row 102</li>
      <li key="103">Genre row 103</li>
      <li key="104">Genre row 104</li>
      <li key="105">Genre row 105</li>
      <li key="106">Genre row 106</li>
      <li key="107">Genre row 107</li>
      <li key="108">Genre row 108</li>
      <li key="109">Genre row 109</li>
      <li key="110">Genre row 110</li>
      <li key="111">Genre row 111</li>
      <li key="112">Genre row 112</li>
      <li key="113">Genre row 113</li>
      <li key="114">Genre row 114</li>
      <li key="115">Genre row 115</li>
      <li key="116">Genre row 116</li>
      <li key="117">Genre row 117</li>
      <li key="118">Genre row 118</li>
      <li key="119">Genre row 119</li>
      <li key="120">Genre row 120</li>
      <li key="121">Genre row 121</li>
      <li key="122">Genre row 122</li>
      <li key="123">Genre row 123</li>
      <li key="124">Genre row 124</li>
      <li key="125">Genre row 125</li>
      <li key="126">Genre row 126</li>
      <li key="127">Genre row 127</li>
      <li key="128">Genre row 128</li>
      <li key="129">Genre row 129</li>
      <li key="130">Genre row 130</li>
      <li key="131">Genre row 131</li>
      <li key="132">Genre row 132</li>
      <li key="133">Genre row 133</li>
      <li key="134">Genre row 134</li>
      <li key="135">Genre row 135</li>
      <li key="136">Genre row 136</li>
      <li key="137">Genre row 137</li>
      <li key="138">Genre row 138</li>
      <li key="139">Genre row 139</li>
      <li key="140">Genre row 140</li>
      <li key="141">Genre row 141</li>
      <li key="142">Genre row 142</li>
      <li key="143">Genre row 143</li>
      <li key="144">Genre row 144</li>
      <li key="145">Genre row 145</li>
      <li key="146">Genre row 146</li>
      <li key="147">Genre row 147</li>
      <li key="148">Genre row 148</li>
      <li key="149">Genre row 149</li>
      <li key="150">Genre row 150</li>
      <li key="151">Genre row 151</li>
      <li key="152">Genre row 152</li>
      <li key="153">Genre row 153</li>
      <li key="154">Genre row 154</li>
      <li key="155">Genre row 155</li>
      <li key="156">Genre row 156</li>
      <li key="157">Genre row 157</li>
      <li key="158">Genre row 158</li>
      <li key="159">Genre row 159</li>
      <li key="160">Genre row 160</li>
      <li key="161">Genre row 161</li>
      <li key="162">Genre row 162</li>
      <li key="163">Genre row 163</li>
      <li key="164">Genre row 164</li>
      <li key="165">Genre row 165</li>
      <li key="166">Genre row 166</li>
      <li key="167">Genre row 167</li>
      <li key="168">Genre row 168</li>
      <li key="169">Genre row 169</li>
      <li key="170">Genre row 170</li>
      <li key="171">Genre row 171</li>
      <li key="172">Genre row 172</li>
      <li key="173">Genre row 173</li>
      <li key="174">Genre row 174</li>
      <li key="175">Genre row 175</li>
      <li key="176">Genre row 176</li>
      <li key="177">Genre row 177</li>
      <li key="178">Genre row 178</li>
      <li key="179">Genre row 179</li>
      <li key="180">Genre row 180</li>
      <li key="181">Genre row 181</li>
      <li key="182">Genre row 182</li>
      <li key="183">Genre row 183</li>
      <li key="184">Genre row 184</li>
      <li key="185">Genre row 185</li>
      <li key="186">Genre row 186</li>
      <li key="187">Genre row 187</li>
      <li key="188">Genre row 188</li>
      <li key="189">Genre row 189</li>
      <li key="190">Genre row 190</li>
      <li key="191">Genre row 191</li>
      <li key="192">Genre row 192</li>
      <li key="193">Genre row 193</li>
      <li key="194">Genre row 194</li>
      <li key="195">Genre row 195</li>
      <li key="196">Genre row 196</li>
      <li key="197">Genre row 197</li>
      <li key="198">Genre row 198</li>
      <li key="199">Genre row 199</li>
    </ul>
  );
}
"""


def _tree():
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True, exist_ok=True)
    return fe


def _drive(fe, rounds, lane_page=None):
    orig = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: _design()
    try:
        for _ in range(rounds):
            if lane_page is not None:
                (fe / "src" / "pages" / "GenresPage.jsx").write_text(lane_page, encoding="utf-8")
            scaffold_pages_from_contract(fe, _UI_PAGES)
    finally:
        fs._load_design_for_projection = orig


def test_nothing_is_reported_when_there_is_no_loop():
    fe = _tree()
    _drive(fe, 1)
    assert scaffold_loop_pages_1202at(fe) == {}


def test_a_page_clobbered_three_times_is_recorded_for_the_lane():
    """Drive the real projector, re-authoring the page between passes like the lane does."""
    fe = _tree()
    _drive(fe, 4, lane_page=_LANE_PAGE)   # the lane re-authors it before every pass

    looping = scaffold_loop_pages_1202at(fe)
    assert "GenresPage" in looping, (
        "the projector clobbered a re-authored lane page four times and recorded nothing "
        "for the lane, which is the state #951 already logs and #1202at exists to end")
    assert looping["GenresPage"] >= 3


def test_both_loop_branches_record_for_the_lane():
    """#1202bp: there are TWO scaffold-loop counters and #1202at only had one.

    r32 showed `SCAFFOLD LOOP (projection)`, so that is the branch I instrumented. r33
    hit the other one — `SCAFFOLD LOOP:` on LoginPage and SignupPage, four times each,
    with the projection branch at zero — so the lane lost its auth pages four times and
    no task was filed. Same loop, same waste, same exit; only the counter differs.
    """
    src = Path(fs.__file__).read_text(encoding="utf-8")
    assert src.count("_SCAFFOLD_LOOP_PAGES_1202AT.setdefault") == 2, (
        "one of the two scaffold-loop branches records nothing, so a lane losing pages "
        "on that branch is never told")
    # each recording site must sit under its own loop verdict
    proj = src.index("SCAFFOLD LOOP (projection)")
    auth = src.index('"SCAFFOLD LOOP: %s has now been overwritten')
    # Bounded by a LANDMARK, not a byte count (#943): each verdict runs to the
    # `except Exception` that closes its own guarded block.
    for name, start in (("projection", proj), ("auth", auth)):
        end = src.index("except Exception", start)
        assert "_SCAFFOLD_LOOP_PAGES_1202AT" in src[start:end], (
            f"the {name} loop verdict records nothing for the lane, so a lane losing "
            "pages on that branch is never told")


def test_the_scaffolder_tells_the_lane_how_to_keep_its_work():
    """The advice must be the actionable one, not just 'you are looping'."""
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    src = Path(scaffolder.__file__).read_text(encoding="utf-8")
    i = src.index("scaffold_loop_pages_1202at")
    tail = src[i:src.index("except Exception as _t1202at", i)]
    assert 'assignee="frontend"' in tail, "the task does not reach the lane that writes pages"
    # #1202gq: assert the ADVICE the task carries, not where its words are spelled. The text
    # moved into `_loop_page_advice_1202gq` so an AUTH page can be told the rule that actually
    # governs it (#1197: wired/drivable/persists) instead of the component rule, which does not
    # apply to it. Pinning the literal at the call site here would have made that fix illegal —
    # #782's failure mode, quoted in `_imports_own_components`. The guarantee is unchanged: an
    # ordinary looping page is still told the one thing that keeps it.
    from env_generator.llm_generator.multi_agent.runtime.scaffolder import (
        _loop_page_advice_1202gq)
    advice = _loop_page_advice_1202gq(["GenresPage"], {})
    assert "../components/" in advice, "the lane is not told the one thing that keeps its page"
    assert "GenresPage" in advice, "the advice does not name the page it is about"
