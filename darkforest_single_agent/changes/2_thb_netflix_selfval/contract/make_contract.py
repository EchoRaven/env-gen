#!/usr/bin/env python3
"""Freeze the Netflix contract (netflix.json) from the frozen task text, benchmarks/env-gen/design_inputs/netflix/DESCRIPTION.txt.

In env-gen's own pipeline the contract is registered by the team under test at kickoff. Here it is fixed in advance,
so the agent cannot shape its own exam. Everything comes from DESCRIPTION.txt:
- endpoints: the 17 listed "METHOD /path" lines, all expected to be implemented;
- auth: /auth/* is public, every /api/* endpoint requires a token (the task is a login-gated streaming app);
- request bodies: only for the two collection writes the default CRUD chain exercises, taken from the data model
  (profiles: name, avatar, is_kids; my_list: title_id). Owner columns and ids are left to the server.
The tables are recorded for reference but are not given to the validator (see README: no synthetic
"missing write path" chain).
"""
import json, os, re

DESC = "/home/user/project/shabi_forest/benchmarks/env-gen/design_inputs/netflix/DESCRIPTION.txt"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netflix.json")
REQUEST = {"POST /api/profiles": {"name": "str", "avatar": "str", "is_kids": "bool"},
           "POST /api/my-list": {"title_id": "int"}}


def main():
    text = open(DESC).read()
    endpoints = {}
    for m, p in re.findall(r"^- (GET|POST|PUT|PATCH|DELETE) (\S+)\s*$", text, re.M):
        key = f"{m} {p}"
        rec = {"method": m, "path": p, "status": "implemented",
               "metadata": {"auth_required": not p.startswith("/auth/")}}
        if key in REQUEST:
            rec["schema"] = {"request": REQUEST[key]}
        endpoints[key] = rec
    tables = {name: {"name": name, "columns": [c.strip() for c in cols.split(",")]}
              for name, cols in re.findall(r"^- table: (\w+): (.+)$", text, re.M)}
    screens = re.search(r"^Screens: (.+?)\.\s*$", text, re.M | re.S).group(1)
    out = {"source": DESC, "endpoints": endpoints, "tables": tables,
           "screens": [s.strip() for s in screens.replace("\n", " ").split(",")]}
    assert len(endpoints) == 17 and len(tables) == 9 and len(out["screens"]) == 13, (len(endpoints), len(tables))
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{OUT}: {len(endpoints)} endpoints, {len(tables)} tables, {len(out['screens'])} screens")


if __name__ == "__main__":
    main()
