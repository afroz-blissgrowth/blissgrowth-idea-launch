#!/usr/bin/env python3
"""Company signals: Apollo organization enrichment (headcounts) for the accounts, by domain. COSTS CREDITS.

  python3 -I bin/signals_run.py plan <run> [--scope pilot]            estimate only, nothing is called
  python3 -I bin/signals_run.py run <run> [--scope pilot] [--limit N]  enrich accounts not enriched yet (1 credit per matched company)
  python3 -I bin/signals_run.py table <run> [--scope pilot]           per account: headcounts and the result of each signal rule
  python3 -I bin/signals_run.py sync <run> [--scope pilot]            push the headcount columns to "2 Accounts" again (no Apollo call)
  options: --no-sheet  --force (enrich although the brief has no numeric signal)

Endpoint: POST organizations/bulk_enrich (10 domains per call) -> estimated_num_employees and departmental_head_count.
Each domain is enriched once (run cache signals/enrich.jsonl plus a shared cross-run cache). Credits are logged in
apollo-usage.jsonl and the Run Log. Order of use: on the PILOT accounts first (--scope pilot), then the rest after the
pilot gate is approved. Hard signal rules drop companies in /iv-qualify; this script only fetches data.
<run> is a folder path, a folder name under runs, or the idea slug (newest match).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import apollo  # noqa: E402
import signals as smod  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "run", "table", "sync", "status"])
    ap.add_argument("run")
    ap.add_argument("--scope", choices=["pilot"], default=None)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        brief = run.brief()
        sg = smod.Signals(run)
        if not run.accounts_csv.exists():
            sys.exit("error: accounts.csv does not exist yet (pull the pilot or the accounts first)")
        if a.scope is None and a.cmd in ("plan", "run"):
            import pilot
            if pilot.scope_ids(run) is not None:  # the accounts pilot is open: spend only on the pilot before the review
                a.scope = "pilot"
                print("the accounts pilot gate is open: enriching the PILOT accounts only (the rest after the approval)")
        rows = sg.scope_rows(a.scope)
        if a.cmd == "plan":
            print(json.dumps(sg.estimate(rows), indent=2))
        elif a.cmd in ("status",):
            print(json.dumps(sg.summary(rows), indent=2))
        elif a.cmd == "table":
            recs = sg.records()
            print("%-30s | %-9s | %6s | %5s | %5s | %5s | %s" % ("Company", "Status", "Emp", "Eng", "Ops", "Sales", "Signal rules"))
            for r in rows:
                v = sg.values(r, recs)
                ev = smod.evaluate(brief.get("signals"), recs.get(r.get("domain") or ""))
                print("%-30s | %-9s | %6s | %5s | %5s | %5s | %s" % ((r["name"] or r["domain"])[:30], v["signals_status"],
                      v["employees"], v.get("engineering", ""), v.get("operations", ""), v.get("sales", ""),
                      "; ".join("%s %s" % (e["name"], e["result"]) for e in ev)))
        elif a.cmd == "sync":
            print(sg.push_to_sheet(rows, brief))
        else:
            if not smod.needs_apollo(brief) and not a.force:
                sys.exit("the brief has no numeric signals, so there is nothing to enrich. Add signals in /iv-brief, or pass --force "
                         "to enrich anyway (1 credit per matched company).")
            est = sg.estimate(rows)
            print("estimate: %d companies to enrich, up to %d credits (%d answered from the cache)" % (
                est["domains_to_enrich"], est["credits_max"], est["from_shared_cache"]))
            with run.lock():
                client = apollo.ApolloClient(usage_log=run.usage_log, label="signals")
                rep = sg.run_signals(client, scope=a.scope, limit=a.limit)
                print("signals:", rep)
                run.log("signals", "org_enrich", "%(requested)d requested, %(matched)d matched, %(not_found)d not found, "
                        "%(from_shared_cache)d from cache, credits %(credits)s" % rep, rep)
                if rep["paused"]:
                    print("PAUSED:", rep["paused"])
                if not a.no_sheet and run.sheet_id():
                    print("sheet:", sg.push_to_sheet(sg.scope_rows(a.scope), brief))
                print(run.write_summary())
    except (RunError, apollo.ApolloError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
