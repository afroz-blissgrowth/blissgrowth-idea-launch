#!/usr/bin/env python3
"""Create or update the permanent "Idea Launch | Sheets Bridge" workflow on the Blissgrowth n8n and activate it.
Only touches the workflow with exactly that name. Needs BLISSGROWTH_N8N_API_KEY / _INSTANCE_URL in <repo>/.env."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)
import n8n  # noqa: E402
import build_sheets_bridge as b  # noqa: E402

NAME = "Idea Launch | Sheets Bridge"


api = n8n.api


def main():
    wf = b.build()
    existing, cursor = [], ""
    while True:  # page through every workflow, or a miss would create a duplicate bridge on the same webhook path
        st, lst = api("GET", "/workflows?limit=250" + ("&cursor=" + cursor if cursor else ""))
        if st != 200:
            sys.exit("could not list workflows (%s): %s" % (st, str(lst)[:200]))
        existing += [w for w in lst.get("data", []) if w["name"] == NAME]
        cursor = lst.get("nextCursor") or ""
        if not cursor:
            break
    if len(existing) > 1:
        sys.exit("more than one workflow named %s, resolve by hand" % NAME)
    if existing:
        wid = existing[0]["id"]
        print("backup:", n8n.backup_workflow(wid, "before-deploy"))  # always back up the live workflow first
        st, r = api("PUT", "/workflows/%s" % wid, wf)
        print("update", st, r.get("id") or r)
    else:
        st, r = api("POST", "/workflows", wf)
        print("create", st, r.get("id") or r)
        wid = r.get("id")
    if not wid:
        sys.exit("deploy failed")
    st, r = api("POST", "/workflows/%s/activate" % wid)
    print("activate", st, r.get("active"), r.get("message", ""))
    print("workflow id:", wid)


if __name__ == "__main__":
    main()
