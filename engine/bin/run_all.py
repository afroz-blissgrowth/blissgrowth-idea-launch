#!/usr/bin/env python3
"""Stage 13: /iv-run, the orchestrator for one idea (brief -> accounts -> qualify -> people -> tier -> enrich-verify -> activity -> phones
-> ready -> copy -> idea page -> launch).

  python3 -I bin/run_all.py status <run>            the projected pipeline: done / AUTO (script) / STOP (user or Claude), with cost estimates
  python3 -I bin/run_all.py next <run>              the first stage that is not complete and exactly what to do about it
  python3 -I bin/run_all.py go <run> [--execute]    default is a DRY RUN (prints what it would run). --execute runs the auto stages in order
                                                    and stops where the user or Claude must act (exit code 10), or on failure (exit code 1)
Resumable (stages come from files). Cost is shown, never a gate. Nothing is started in HeyReach, ever; launch needs the user's approval.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import orchestrate as orch  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "next", "go"])
    ap.add_argument("run")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        if a.cmd == "status":
            recs = orch.projection(run)
            print(json.dumps(recs, indent=2) if a.json else orch.render(recs))
            print()
            print(run.write_summary())
        elif a.cmd == "next":
            recs = orch.projection(run)
            cur = next((r for r in recs if not r["complete"]), None)
            if not cur:
                print("every stage is complete")
            else:
                print(json.dumps(cur, indent=2) if a.json else "%s (%s): %s\n%s" % (cur["stage"], cur["status"], cur["detail"],
                                                                                  cur["instruction"] or "the driver runs this: " + (cur["estimate"] or ""), ))
        else:
            if not a.execute:
                print(orch.render(orch.projection(run)))
                print()
            res = orch.drive(run, execute=a.execute)
            print(json.dumps(res, indent=2))
            if res["state"] == "stopped":
                sys.exit(10)
            if res["state"] in ("failed", "stalled"):
                sys.exit(1)
    except RunError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
