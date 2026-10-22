#!/usr/bin/env python3
"""Pilot gates: a small human-reviewed pilot BEFORE the money is spent at scale. Two gates, `accounts` and `people`.

  python3 -I bin/pilot_run.py accounts start <run> [--size 15] [--from-existing]   pull the account pilot (10 to 20, Apollo credits
                                                                                   like a small limit pull), or draw it from accounts already pulled
  python3 -I bin/pilot_run.py people start <run> [--size 15]                        draw the people pilot (after /iv-people and /iv-tier, no credits)
  python3 -I bin/pilot_run.py <gate> request-review <run>      finalize qualify (accounts) / rebuild people, push the pilot columns, ask for the review
  python3 -I bin/pilot_run.py <gate> pull-review <run>         read pilot_review and pilot_note from the sheet (chat marks are kept)
  python3 -I bin/pilot_run.py <gate> record <run> --id ID | --match TEXT --review approve|reject [--note "why"] [--simulated]
  python3 -I bin/pilot_run.py <gate> list <run>                the pilot rows with ids and marks
  python3 -I bin/pilot_run.py <gate> summary <run> [--json]    patterns in the rejections, AI versus human (for Claude to explain and to propose changes)
  python3 -I bin/pilot_run.py <gate> approve <run> --note "what the user said" [--simulated]   the EXPLICIT approval that opens the next step
  python3 -I bin/pilot_run.py <gate> skip <run> --note "why"   skip the gate (a recorded user decision)
  python3 -I bin/pilot_run.py <gate> status <run>
  options: --no-sheet

Accounts gate: after approval the full pull (accounts_pull.py) is allowed and approved pilot accounts get is_seed = yes.
People gate: after approval enrichment (enrich_verify.py) is allowed; rejected pilot people are never enriched.
--simulated labels reviews and approvals nobody gave (tests): TEST runs only, never counts for a real run.
<run> is a folder path, a folder name under runs, or the idea slug (newest match).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import apollo  # noqa: E402
import pilot as pm  # noqa: E402
import people as peoplemod  # noqa: E402
import schema  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import read_csv  # noqa: E402


def rows_for_list(run, kind):
    g = pm.Gate(run, kind)
    rv = g.reviews()
    ids = g.ids()
    if kind == pm.ACCOUNTS:
        by = {r["org_id"]: r for r in read_csv(run.accounts_csv)}
        from util import read_jsonl
        res = {r.get("org_id"): r for r in read_jsonl(run.qdir / "results.jsonl")}
        return [(i, by.get(i, {}).get("name", ""), by.get(i, {}).get("domain", ""), res.get(i, {}).get("flag", ""),
                 (rv.get(i) or {}).get("review", ""), (rv.get(i) or {}).get("note", "")) for i in ids]
    by = {r["person_id"]: r for r in peoplemod.load_table(run)}
    return [(i, by.get(i, {}).get("company", ""), by.get(i, {}).get("title", ""), by.get(i, {}).get("tier", ""),
             (rv.get(i) or {}).get("review", ""), (rv.get(i) or {}).get("note", "")) for i in ids]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gate", choices=list(pm.KINDS))
    ap.add_argument("cmd", choices=["start", "request-review", "pull-review", "record", "list", "summary", "approve", "skip", "status"])
    ap.add_argument("run")
    ap.add_argument("--size", type=int)
    ap.add_argument("--from-existing", action="store_true")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--match")
    ap.add_argument("--review")
    ap.add_argument("--note", default="")
    ap.add_argument("--simulated", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        kind = a.gate
        g = pm.Gate(run, kind)
        brief = run.brief()
        push = not a.no_sheet and bool(run.sheet_id())
        if a.cmd == "start":
            with run.lock():
                if kind == pm.ACCOUNTS:
                    ids = pm.start_accounts(run, brief, a.size, from_existing=a.from_existing, push=push)
                    if push:
                        print("sheet:", pm.sync_accounts_sheet(run))
                else:
                    ids = pm.start_people(run, brief, a.size)
                    if push:
                        print("sheet:", peoplemod.sync(run, brief, push=True)[1])
                print("%s pilot of %d drawn. Next: qualify it (accounts) and ask the user to review." % (kind, len(ids))
                      if kind == pm.ACCOUNTS else "people pilot of %d drawn. Next: request-review." % len(ids))
                run.log("pilot", "%s_started" % kind, "pilot of %d %s%s" % (len(ids), kind, " (from existing accounts)" if a.from_existing else ""),
                        {"size": len(ids)})
        elif a.cmd == "request-review":
            with run.lock():
                rep = pm.request_review(run, kind, push=push)
                print(json.dumps(rep, default=str))
                run.log("pilot", "%s_review_requested" % kind, "pilot columns pushed, waiting for the user's review", {"size": len(g.ids())})
        elif a.cmd == "pull-review":
            if not run.sheet_id():
                sys.exit("error: this run has no sheet; record marks with `record`")
            rep = g.pull_from_sheet()
            print(rep)
            if rep["changed"]:
                run.log("pilot", "%s_review_pulled" % kind, "%d marks read from the sheet" % rep["changed"], g.counts())
            if rep["invalid"]:
                print("These rows have a pilot_review that is not approve or reject (fix them in the sheet):", ", ".join(rep["invalid"]))
            print(g.counts())
        elif a.cmd == "record":
            ids = list(a.id)
            if a.match:
                needle = a.match.lower()
                hits = [r[0] for r in rows_for_list(run, kind) if needle in " ".join(str(x) for x in r[:3]).lower()]
                if len(hits) != 1:
                    sys.exit("error: --match %r matches %d pilot rows, need exactly 1 (use --id)" % (a.match, len(hits)))
                ids = hits
            if not ids or a.review is None:
                sys.exit("error: give --id (or --match) and --review approve|reject")
            n = sum(1 for i in ids if g.record(i, a.review, a.note, "chat", a.simulated))
            run.log("pilot", "%s_review_recorded" % kind, "%d marks recorded in chat%s" % (n, " (SIMULATED)" if a.simulated else ""), g.counts())
            print("recorded %d. %s" % (n, g.counts()))
            if push:
                if kind == pm.ACCOUNTS:
                    print("sheet:", pm.sync_accounts_sheet(run))
                else:
                    print("sheet:", peoplemod.sync(run, brief, push=True)[1])
        elif a.cmd == "list":
            for r in rows_for_list(run, kind):
                print(" | ".join(str(x) for x in r))
        elif a.cmd == "summary":
            if run.sheet_id() and not a.no_sheet:
                try:
                    g.pull_from_sheet()
                except Exception as e:  # the summary must work from the local marks too
                    print("(could not read the sheet: %s)" % e)
            s = pm.accounts_summary(run) if kind == pm.ACCOUNTS else pm.people_summary(run)
            print(json.dumps(s, indent=2, default=str) if a.json else
                  (pm.format_accounts_summary(s) if kind == pm.ACCOUNTS else pm.format_people_summary(s)))
        elif a.cmd == "approve":
            with run.lock():
                if run.sheet_id() and not a.no_sheet:
                    try:
                        g.pull_from_sheet()
                    except Exception as e:
                        print("(could not read the sheet, using the marks recorded locally: %s)" % e)
                ap_ = g.approve(a.note, a.simulated)
                print("approved:", json.dumps(ap_))
                run.log("pilot", "%s_approved" % kind, "%d approve, %d reject%s. %s" % (
                    ap_["counts"]["approve"], ap_["counts"]["reject"], " SIMULATED" if ap_["simulated"] else "", a.note), ap_["counts"])
                if kind == pm.ACCOUNTS:
                    import qualify as qmod
                    print("qualify finalize:", qmod.Qualify(run).finalize(push=push))
                    print("seeds written:", len(pm.write_seeds(run, ap_)), "(pilot/seeds.csv, column is_seed)")
                    if push:
                        print("sheet:", pm.sync_accounts_sheet(run))
                else:
                    print("people:", len(peoplemod.sync(run, brief, push=push)[0]), "rows rebuilt (rejected pilot people will not be enriched)")
        elif a.cmd == "skip":
            g.skip(a.note)
            run.log("pilot", "%s_skipped" % kind, a.note)
            print("%s pilot gate skipped (recorded)." % kind)
        elif a.cmd == "status":
            st = pm.accounts_state(run) if kind == pm.ACCOUNTS else pm.people_state(run)
            print(json.dumps(dict(st, next=pm.next_action(run, kind)["instruction"]), indent=2, default=str))
        if a.cmd != "list" and a.cmd != "summary":
            print(run.write_summary())
    except (RunError, pm.PilotError, apollo.ApolloError, peoplemod.PeopleError, RuntimeError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
