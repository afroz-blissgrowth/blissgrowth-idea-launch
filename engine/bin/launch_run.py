#!/usr/bin/env python3
"""Stage 12: /iv-launch, HeyReach only (v1). Lists + DRAFT campaigns + Mansi's call sheet. NOTHING IS EVER STARTED.

  python3 -I bin/launch_run.py accounts                     list HeyReach LinkedIn accounts (read only) to fill launch.senders
  python3 -I bin/launch_run.py plan <run> [--date D]        the plan: lists, campaign names, sequences, problems (no network, writes launch/plan.md)
  python3 -I bin/launch_run.py approve <run> --note "..."   the USER approved this exact plan (hash) [--simulated for tests]
  python3 -I bin/launch_run.py execute <run> [--dry-run] [--adopt-existing-list]
                                                            create the lists, add the leads, create DRAFT campaigns with sequences.
                                                            --dry-run shows every gate and exactly what would be sent, calls nothing.
  python3 -I bin/launch_run.py callsheet <run> [--execute]  Mansi's call sheet (separate sheet, shared only with launch.mansi_email)
  python3 -I bin/launch_run.py status <run>
A TEST brief, simulated approvals, an unapproved or changed plan, or missing sender accounts refuse execution. Resumable: launch/launch.json
records every id created. The HeyReach client has no start, resume, pause or delete call.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import heyreach  # noqa: E402
import launch as lmod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import read_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["accounts", "plan", "approve", "execute", "callsheet", "status"])
    ap.add_argument("run", nargs="?")
    ap.add_argument("--date")
    ap.add_argument("--note", default="")
    ap.add_argument("--simulated", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--adopt-existing-list", action="store_true")
    a = ap.parse_args()
    try:
        if a.cmd == "accounts":
            seen = {}
            for c in heyreach.HeyReach().campaigns():
                for i in c.get("campaignAccountIds") or []:
                    seen.setdefault(i, []).append(c["name"])
            print("LinkedIn account ids used by campaigns in the Bliss workspace (the campaign names tell whose account it is):")
            for i, names in sorted(seen.items()):
                print("  %s  used in %d campaigns, e.g. %s" % (i, len(names), names[0][:70]))
            print("Put the ids in engine/config.json under launch.senders (not secrets), or set IDEA_LAUNCH_SENDER_JAY, IDEA_LAUNCH_SENDER_MEELAN, IDEA_LAUNCH_SENDER_ASSOCIATE.")
            return
        if not a.run:
            sys.exit("a run is required")
        run = Run.resolve(a.run)
        ln = lmod.Launch(run)
        if a.cmd == "plan":
            p = ln.make_plan(a.date)
            print((ln.dir / "plan.md").read_text())
            why = ln.gates(p)
            if why:
                print("Execution is currently refused because:\n  - " + "\n  - ".join(why))
            run.log("launch", "plan", "hash %s, %d leads, %d lists" % (p["plan_hash"], p["leads_total"], len(p["groups"])))
        elif a.cmd == "approve":
            ap_ = ln.approve(a.note, a.simulated)
            run.log("launch", "approved", "plan %s: %s%s" % (ap_["plan_hash"], a.note, " (SIMULATED)" if a.simulated else ""))
            print(json.dumps(ap_, indent=2))
        elif a.cmd == "execute":
            saved = read_json(ln.approval_path, None)
            p = lmod.plan(run, (saved or {}).get("date"))
            why = ln.gates(p)
            if a.dry_run:
                print("DRY RUN, nothing is sent. Plan hash %s, %d lists, %d campaigns (all DRAFT)." % (
                    p["plan_hash"], len(p["groups"]), sum(len(g["campaigns"]) for g in p["groups"])))
                for g in p["groups"]:
                    print("  list '%s': %d leads in batches of %d" % (g["list_name"], g["leads"], lmod.lcfg().get("lead_batch", 100)))
                    for c in g["campaigns"]:
                        print("    DRAFT campaign '%s' (%s, sender %s), sequence problems: %s" % (c["name"], c["kind"], c["sender"], c["problems"] or "none"))
                print("Refused for a real run because:" if why else "All gates pass.")
                for w in why:
                    print("  - " + w)
                return
            with run.lock():
                st = ln.execute(heyreach.HeyReach(), adopt_existing=a.adopt_existing_list)
                run.log("launch", "executed", "lists/campaigns created as DRAFT, nothing started", {"groups": len(st["groups"])})
                print(json.dumps(st, indent=2))
                print("Done. Every campaign is a DRAFT. Open HeyReach, check, and press Start yourself.")
        elif a.cmd == "callsheet":
            rep = ln.callsheet(dry_run=not a.execute)
            print(json.dumps(rep, indent=2))
            if a.execute and rep.get("sheet_id"):
                run.log("launch", "callsheet", "%s rows, shared with %s" % (rep["rows"], rep.get("shared_with")))
        elif a.cmd == "status":
            print(json.dumps({"plan": bool(read_json(ln.plan_path, None)), "approval": read_json(ln.approval_path, None),
                              "state": ln.state(), "callsheet": read_json(ln.callsheet_path, None)}, indent=2))
        run.write_summary()
    except (RunError, lmod.LaunchError, heyreach.HeyReachError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
