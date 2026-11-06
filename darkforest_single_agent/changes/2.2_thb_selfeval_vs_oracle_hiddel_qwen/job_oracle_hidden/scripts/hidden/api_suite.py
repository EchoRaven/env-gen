#!/usr/bin/env python3
"""H1, hidden: black-box API checks of a running Netflix build against DESCRIPTION.txt and docs/spec.md.

usage: api_suite.py <backend_url> <frontend_url> <out.json>

The agent never sees this file or its results. It is written from the task text, not from any submission, and it
uses data unlike the dev evaluator's: its own accounts (no `chain-*@example.com`), real title ids read from the
catalog, two profiles per account and a second account. Conventions the task leaves open are tolerated, as in
env-gen's north-star oracle (`agent/tests/north_star/_conventions.py`, whose helpers are imported). Behaviour is
not tolerated.
- Envelopes `{items}` / `{data}` / bare list, and ids wrapped in `{item}`.
- 401 or 403 for "rejected".
- How a profile is selected. The spec says only "list / create / select", so the suite probes the usual
  conventions and uses the first that actually isolates two profiles.

Each check has a category; the score is the pass fraction per category and overall.
"""
import base64, json, random, sys, urllib.parse

import requests

sys.path.insert(0, "/home/user/project/shabi_forest/benchmarks/env-gen/agent/tests/north_star")
from _conventions import _id_of, items_of  # noqa: E402  (frozen env-gen helpers)

DATASET = "/home/user/project/shabi_forest/benchmarks/env-gen/design_inputs/netflix/dataset/titles.json"
SERIES = ("series", "tv", "show", "tv_show", "tvshow")
CONVENTIONS = [("header", "X-Profile-Id"), ("header", "Profile-Id"), ("header", "X-Profile"),
               ("query", "profile_id"), ("query", "profileId"), ("query", "profile"),
               ("select", "/api/profiles/{id}/select")]


class Suite:
    def __init__(self, be, fe):
        self.be, self.fe, self.checks, self.conv = be.rstrip("/"), fe.rstrip("/"), [], None
        self.n = random.randint(10 ** 6, 10 ** 7)

    # ------------------------------------------------------------------ plumbing
    def check(self, cat, name, ok, detail=""):
        self.checks.append({"category": cat, "name": name, "ok": bool(ok), "detail": str(detail)[:300]})

    def req(self, method, path, tok=None, prof=None, body=None, raw=None, timeout=20):
        headers, params = {"Content-Type": "application/json"}, {}
        if prof is not None and self.conv:
            kind, key = self.conv
            if kind == "header":
                headers[key] = str(prof)
            elif kind == "query":
                params[key] = str(prof)
            elif kind == "select":
                tok = prof  # a profile-scoped token stands in for the account token
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            r = requests.request(method, self.be + path, headers=headers, params=params, timeout=timeout,
                                 data=raw if raw is not None else (json.dumps(body) if body is not None else None))
            try:
                js = r.json()
            except Exception:
                js = None
            return r, js
        except Exception as e:
            return None, {"_error": repr(e)}

    def code(self, r):
        return r.status_code if r is not None else 0

    def register(self, tag):
        email, pw = f"h{tag}{self.n}@hidden-check.test", f"Pw-{tag}-{self.n}!"
        r, js = self.req("POST", "/auth/register", body={"email": email, "password": pw, "name": f"Hidden {tag}"})
        return email, pw, (js or {}).get("access_token") if isinstance(js, dict) else None, self.code(r)

    def login(self, email, pw):
        r, js = self.req("POST", "/auth/login", body={"email": email, "password": pw})
        return (js or {}).get("access_token") if isinstance(js, dict) else None, self.code(r)

    def new_profile(self, tok, name, kids=False):
        r, js = self.req("POST", "/api/profiles", tok, body={"name": name, "avatar": "blue", "is_kids": kids})
        return _id_of(js) if self.code(r) in (200, 201) else None

    def scoped(self, tok, pid):
        """What to pass as `prof` for profile pid under the detected convention."""
        if self.conv and self.conv[0] == "select":
            r, js = self.req("POST", self.conv[1].format(id=pid), tok)
            return (js or {}).get("access_token") if isinstance(js, dict) else None
        return pid

    @staticmethod
    def has_title(items, tid, name):
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("title") if isinstance(it.get("title"), dict) else {}
            if (it.get("title_id") == tid or t.get("id") == tid or it.get("id") == tid and it.get("name") == name
                    or it.get("name") == name or t.get("name") == name or it.get("title") == name):
                return True
        return False

    def my_list(self, tok, prof):
        r, js = self.req("GET", "/api/my-list", tok, prof)
        return items_of(js) if self.code(r) == 200 else None

    def add(self, tok, prof, tid):
        return self.req("POST", "/api/my-list", tok, prof, body={"title_id": tid})

    def remove(self, tok, prof, tid, row_id=None):
        for x in [tid] + ([row_id] if row_id not in (None, tid) else []):
            r, _ = self.req("DELETE", f"/api/my-list/{x}", tok, prof)
            if self.code(r) in (200, 202, 204):
                return True
        return False

    def media_ok(self, url, kind):
        if not url:
            return False, "no url"
        full = url if url.startswith("http") else self.fe + ("" if url.startswith("/") else "/") + url
        try:
            r = requests.get(full, headers={"Range": "bytes=0-2047"}, timeout=20)
            ct = r.headers.get("content-type", "")
            return r.status_code in (200, 206) and (kind in ct or "octet-stream" in ct), f"{r.status_code} {ct} {full[-60:]}"
        except Exception as e:
            return False, repr(e)[:120]

    # ------------------------------------------------------------------ the suite
    def run(self):
        ds = json.load(open(DATASET))
        ds = ds if isinstance(ds, list) else ds.get("titles") or next(iter(ds.values()))
        ds_names = {d.get("name") for d in ds}

        # auth
        ea, pa, ta, c = self.register("a")
        self.check("auth", "register returns an access token", ta, c)
        eb, pb, tb, c = self.register("b")
        r, _ = self.req("POST", "/auth/register", body={"email": ea, "password": "Other-1!", "name": "dup"})
        self.check("auth", "duplicate email is rejected (4xx)", 400 <= self.code(r) < 500, self.code(r))
        tok, c = self.login(ea, pa)
        self.check("auth", "login with the right password returns a token", tok, c)
        ta = tok or ta
        _, c = self.login(ea, pa + "x")
        self.check("auth", "wrong password is rejected (401/403)", c in (401, 403), c)
        _, c = self.login(f"nobody{self.n}@hidden-check.test", pa)
        self.check("auth", "unknown email is rejected (4xx)", 400 <= c < 500, c)
        if ta and ta.count(".") == 2:
            h, p, s = ta.split(".")
            claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
            claims = {k: (("1" if isinstance(v, str) else 1) if k in ("sub", "user_id", "uid", "id") else v)
                      for k, v in claims.items()}
            forged = h + "." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + "." + s
            r, _ = self.req("GET", "/api/profiles", forged)
            self.check("auth", "a token with an edited payload is rejected", self.code(r) in (401, 403), self.code(r))
        else:
            self.check("auth", "a token with an edited payload is rejected", False, "token is not a JWT")
        r, _ = self.req("GET", "/api/profiles", "not-a-token")
        self.check("auth", "a garbage token is rejected", self.code(r) in (401, 403), self.code(r))
        for path in ["/api/titles", "/api/genres", "/api/search?q=a", "/api/my-list", "/api/profiles",
                     "/api/continue-watching", "/api/titles/trending", "/api/titles/top10"]:
            r, _ = self.req("GET", path)
            self.check("auth", f"no token: GET {path.split('?')[0]} is rejected", self.code(r) in (401, 403), self.code(r))
        if not ta:
            return self.finish("no account token; later categories cannot run")

        # catalog
        best = []
        for q in ["?limit=200", "?per_page=200", "?page_size=200", "?limit=100", ""]:
            r, js = self.req("GET", "/api/titles" + q, ta)
            if self.code(r) == 200 and len(items_of(js)) > len(best):
                best, first = items_of(js), js
        total = (first.get("total") if isinstance(first, dict) else None) if best else None
        if best and isinstance(total, int) and total > len(best):
            for off in range(len(best), min(total, 1000), len(best)):
                r, js = self.req("GET", f"/api/titles?limit={len(best)}&offset={off}", ta)
                best += items_of(js) if self.code(r) == 200 else []
        titles = [t for t in best if isinstance(t, dict)]
        names = {t.get("name") or t.get("title") for t in titles}
        cover = len(names & ds_names)
        self.check("catalog", "the catalog lists the dataset's titles (>=95%)", cover >= 0.95 * len(ds_names),
                   f"{cover}/{len(ds_names)} dataset names; {len(titles)} listed")
        fields = [("name", "title"), ("kind", "type"), ("year", "release_year"), ("synopsis", "description", "overview"),
                  ("poster", "poster_url"), ("backdrop", "backdrop_url"), ("maturity_rating", "maturity")]
        full = sum(all(any(t.get(a) not in (None, "") for a in alts) for alts in fields) for t in titles)
        self.check("catalog", "titles carry the data-model fields (>=95%)", titles and full >= 0.95 * len(titles),
                   f"{full}/{len(titles)}")
        if not titles:
            return self.finish("empty catalog")
        sample = random.Random(self.n).sample(titles, min(5, len(titles)))
        img = [self.media_ok(t.get("poster") or t.get("poster_url"), "image") for t in sample]
        img += [self.media_ok(t.get("backdrop") or t.get("backdrop_url"), "image") for t in sample]
        self.check("catalog", "poster and backdrop images load", all(o for o, _ in img), [d for o, d in img if not o][:2])
        vids = [self.media_ok(t.get("video_url") or t.get("video"), "video") for t in sample[:3]]
        self.check("catalog", "trailer clips (video_url) load", all(o for o, _ in vids), [d for o, d in vids if not o][:2])
        movie = next((t for t in titles if str(t.get("kind")).lower() == "movie"), titles[0])
        series = next((t for t in titles if str(t.get("kind") or t.get("type")).lower() in SERIES), None)
        mid, mname = _id_of(movie), movie.get("name") or movie.get("title")
        r, js = self.req("GET", f"/api/titles/{mid}", ta)
        d = js.get("item", js) if isinstance(js, dict) else {}
        self.check("catalog", "title detail matches the listing", self.code(r) == 200 and (d.get("name") or d.get("title")) == mname,
                   self.code(r))
        r, _ = self.req("GET", "/api/titles/987654321", ta)
        self.check("catalog", "a missing title id is 404", self.code(r) == 404, self.code(r))
        if series:
            r, js = self.req("GET", f"/api/titles/{_id_of(series)}/episodes", ta)
            eps = items_of(js) if self.code(r) == 200 else []
            ok = eps and all(any(e.get(k) is not None for k in ("season", "season_number")) and
                             any(e.get(k) is not None for k in ("number", "episode_number", "episode")) for e in eps)
            self.check("catalog", "a series has episodes with season and number", ok, f"{len(eps)} episodes")
        else:
            self.check("catalog", "a series has episodes with season and number", False, "no series in the catalog")
        r, js = self.req("GET", "/api/titles/trending", ta)
        tr = items_of(js) if self.code(r) == 200 else []
        self.check("catalog", "trending is non-empty and drawn from the catalog",
                   tr and all((t.get("name") or t.get("title")) in names for t in tr if isinstance(t, dict)), len(tr))
        r, js = self.req("GET", "/api/titles/top10", ta)
        top = [t for t in (items_of(js) if self.code(r) == 200 else []) if isinstance(t, dict)]
        groups = {}
        for t in top:
            groups.setdefault(str(t.get("kind") or "all").lower(), []).append(t.get("top10_rank") or t.get("rank"))
        ok = bool(top) and all(sorted(v) == list(range(1, len(v) + 1)) and 5 <= len(v) <= 10 for v in groups.values()) \
            or (top and sorted(t.get("top10_rank") or t.get("rank") or 0 for t in top) == list(range(1, len(top) + 1)))
        self.check("catalog", "top 10 is ranked 1..n (per kind or overall)", ok, {k: v for k, v in groups.items()})
        r, js = self.req("GET", "/api/genres", ta)
        genres = [g for g in (items_of(js) if self.code(r) == 200 else []) if isinstance(g, dict)]
        gnames = [g.get("name") for g in genres]
        self.check("catalog", "genres are listed (>=5, unique names)", len(gnames) >= 5 and len(set(gnames)) == len(gnames),
                   len(gnames))
        good, tried = 0, 0
        for g in genres[:3]:
            r, js = self.req("GET", f"/api/genres/{_id_of(g)}/titles", ta)
            gt = [t for t in (items_of(js) if self.code(r) == 200 else []) if isinstance(t, dict)]
            tried += 1
            if gt and sum(str(g.get("name")).lower() in json.dumps(t).lower() for t in gt) >= 0.8 * len(gt):
                good += 1
        self.check("catalog", "genre pages list titles of that genre", tried and good == tried, f"{good}/{tried} genres")
        word = sorted(str(mname).split(), key=len)[-1]
        found = None
        for key in ("q", "query", "term"):
            r, js = self.req("GET", f"/api/search?{key}={urllib.parse.quote(word)}", ta)
            if self.code(r) == 200 and self.has_title(items_of(js), mid, mname):
                found = key
                break
        self.check("catalog", "search by a word of a title's name finds it", found, word)
        key = found or "q"
        if gnames:
            gname = gnames[0]
            r, js = self.req("GET", f"/api/search?{key}={urllib.parse.quote(gname)}", ta)
            res = [t for t in items_of(js) if isinstance(t, dict)] if self.code(r) == 200 else []
            self.check("catalog", "search by genre name returns that genre's titles",
                       res and sum(gname.lower() in json.dumps(t).lower() for t in res) >= 0.8 * len(res), f"{gname}: {len(res)}")
        r, js = self.req("GET", f"/api/search?{key}=zzqx{self.n}", ta)
        self.check("catalog", "search for nonsense is empty", self.code(r) == 200 and not items_of(js), self.code(r))
        r, js = self.req("GET", f"/api/search?{key}=" + urllib.parse.quote("' OR '1'='1"), ta)
        self.check("catalog", "search with SQL metacharacters neither errors nor dumps the catalog",
                   self.code(r) < 500 and len(items_of(js)) < len(titles), f"{self.code(r)}, {len(items_of(js))}")

        # profiles: detect how a profile is selected
        for conv in CONVENTIONS:
            self.conv = conv
            e, p, t, _ = self.register("c" + str(CONVENTIONS.index(conv)))
            p1, p2 = (self.new_profile(t, "One"), self.new_profile(t, "Two")) if t else (None, None)
            if not (p1 and p2):
                break
            s1, s2 = self.scoped(t, p1), self.scoped(t, p2)
            r, _ = self.add(t, s1, mid)
            l1, l2 = self.my_list(t, s1), self.my_list(t, s2)
            if self.code(r) in (200, 201) and l1 is not None and l2 is not None and \
                    self.has_title(l1, mid, mname) and not self.has_title(l2, mid, mname):
                break
            self.conv = None
        self.check("profiles", "creating a profile returns its id", p1, p1)
        r, js = self.req("GET", "/api/profiles", t if p1 else ta)
        self.check("profiles", "created profiles are listed", p1 and any(_id_of(x) == p1 for x in items_of(js)), self.code(r))
        self.check("profiles", "some profile-selection convention isolates two profiles", self.conv, self.conv)
        if not self.conv:
            # Black-box, an ignored selector and an unscoped read look the same: two profiles see one list.
            # Either way the spec's per-profile privacy does not hold, so it is recorded as that failure.
            for name in ("My List is private to the profile", "another account cannot read this profile's My List",
                         "a rating is private to the profile"):
                self.check("privacy", name, False, "no profile-selection convention isolates two profiles")
            return self.finish("no profile convention isolates profiles; per-profile checks recorded as failed")

        # privacy and writes, on account A's two fresh profiles
        a1, a2 = self.new_profile(ta, "A one"), self.new_profile(ta, "A two")
        s1, s2 = self.scoped(ta, a1), self.scoped(ta, a2)
        r, js = self.add(ta, s1, mid)
        row = _id_of(js.get("item", js)) if isinstance(js, dict) else None
        l1, l2 = self.my_list(ta, s1) or [], self.my_list(ta, s2) or []
        self.check("writes", "adding to My List persists", self.code(r) in (200, 201) and self.has_title(l1, mid, mname), self.code(r))
        self.check("privacy", "My List is private to the profile", not self.has_title(l2, mid, mname), len(l2))
        self.add(ta, s1, mid)
        l1 = self.my_list(ta, s1) or []
        self.check("writes", "adding the same title twice does not duplicate it",
                   sum(self.has_title([x], mid, mname) for x in l1) == 1, len(l1))
        if self.conv[0] != "select":
            r, js = self.req("GET", "/api/my-list", tb, a1)
            leak = self.code(r) == 200 and self.has_title(items_of(js), mid, mname)
            self.check("privacy", "another account cannot read this profile's My List", not leak, self.code(r))
            r, _ = self.add(tb, a1, movie.get("id"))
            l1b = self.my_list(ta, s1) or []
            self.check("privacy", "another account cannot write this profile's My List",
                       self.code(r) in (401, 403, 404) or len(l1b) == len(l1), self.code(r))
        r, js = self.req("GET", "/api/profiles", tb)
        self.check("privacy", "another account does not see these profiles",
                   self.code(r) == 200 and not any(_id_of(x) in (a1, a2) for x in items_of(js)), self.code(r))
        r, js = self.req("GET", "/api/continue-watching", ta, s2)
        self.check("privacy", "a fresh profile's Continue Watching is empty", self.code(r) == 200 and not items_of(js), self.code(r))
        before1 = self.req("GET", f"/api/titles/{mid}", ta, s1)[1]
        before2 = self.req("GET", f"/api/titles/{mid}", ta, s2)[1]
        rated = None
        for body in ({"value": 2}, {"value": 1}, {"value": "up"}, {"rating": 2}, {"thumbs": "up"}):
            r, _ = self.req("POST", f"/api/titles/{mid}/rating", ta, s1, body=body)
            if self.code(r) in (200, 201, 204):
                rated = body
                break
        after1 = self.req("GET", f"/api/titles/{mid}", ta, s1)[1]
        after2 = self.req("GET", f"/api/titles/{mid}", ta, s2)[1]
        self.check("writes", "a rating is accepted and shows on the title for that profile",
                   rated and json.dumps(after1, sort_keys=True) != json.dumps(before1, sort_keys=True), rated)
        self.check("privacy", "a rating is private to the profile",
                   rated and json.dumps(after2, sort_keys=True) == json.dumps(before2, sort_keys=True), rated)
        if rated:
            k = next(iter(rated))  # the spec names three values (down / up / love) but not their encoding
            changed, other = False, None
            for v in (-1, 1, 3, 0, "down", "love"):
                if v == rated[k]:
                    continue
                r, _ = self.req("POST", f"/api/titles/{mid}/rating", ta, s1, body={k: v})
                if self.code(r) in (200, 201, 204):
                    other = {k: v}
                    again = self.req("GET", f"/api/titles/{mid}", ta, s1)[1]
                    changed = json.dumps(again, sort_keys=True) != json.dumps(after1, sort_keys=True)
                    break
            self.check("writes", "re-rating with another value changes it", changed, other)
        ok = self.remove(ta, s1, mid, row)
        l1 = self.my_list(ta, s1) or []
        self.check("writes", "removing from My List works", ok and not self.has_title(l1, mid, mname), ok)

        # input validation
        r, js = self.add(ta, s1, 987654321)
        self.check("validation", "adding a nonexistent title is a 4xx", 400 <= self.code(r) < 500, self.code(r))
        r, _ = self.req("POST", "/api/my-list", ta, s1, body={})
        self.check("validation", "adding with an empty body is a 4xx", 400 <= self.code(r) < 500, self.code(r))
        r, _ = self.req("POST", "/api/my-list", ta, s1, raw="{not json")
        self.check("validation", "a malformed JSON body is a 4xx, not a 5xx", 400 <= self.code(r) < 500, self.code(r))
        r, _ = self.req("POST", "/api/titles/987654321/rating", ta, s1, body=rated or {"value": 1})
        self.check("validation", "rating a nonexistent title is a 4xx", 400 <= self.code(r) < 500, self.code(r))
        r, _ = self.req("POST", "/api/profiles", ta, body={})
        self.check("validation", "creating a profile without a name is a 4xx", 400 <= self.code(r) < 500, self.code(r))
        return self.finish("")

    def finish(self, note):
        cats = {}
        for c in self.checks:
            cats.setdefault(c["category"], []).append(c["ok"])
        return {"checks": self.checks, "convention": self.conv, "note": note,
                "by_category": {k: {"passed": sum(v), "total": len(v)} for k, v in cats.items()},
                "passed": sum(c["ok"] for c in self.checks), "total": len(self.checks)}


if __name__ == "__main__":
    res = Suite(sys.argv[1], sys.argv[2]).run()
    json.dump(res, open(sys.argv[3], "w"), indent=1)
    for c in res["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + f"[{c['category']}] {c['name']}" + ("" if c["ok"] else f"  ({c['detail']})"))
    print(f"{res['passed']}/{res['total']}  convention={res['convention']}  {res['note']}")
