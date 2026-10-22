#!/usr/bin/env python3
"""Stage 7: LinkedIn activity check through the n8n "LinkedIn Activity Checker" (contract in lib/activity.py).

  python3 -I bin/activity_run.py run <run> [--limit N]     check selected people not yet cached (activates the checker for
                                                           the run only, deactivates it afterwards, caches by profile URL)
  python3 -I bin/activity_run.py run <run> --resume        after a timeout: only collect results, then deactivate
  python3 -I bin/activity_run.py deactivate <run>          safety: make sure the checker is inactive
  python3 -I bin/activity_run.py skip <run> --note "why"   skip the check on the user's say-so (LinkedIn needs only a URL)
  python3 -I bin/activity_run.py backfill <run>            free: copy the checker's employment columns (headline, current jobs ...) into
                                                           the cache of profiles checked earlier, for the employment exclusions
  python3 -I bin/activity_run.py status <run>
Inactive profiles get the email channel only; people without a valid email get LinkedIn only. Apify costs a few cents.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import activity as amod  # noqa: E402
import config  # noqa: E402
import n8n  # noqa: E402
import people as peoplemod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import now_iso, read_json, write_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "deactivate", "skip", "status", "backfill"])
    ap.add_argument("run")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        f = peoplemod.Files(run)
        if a.cmd == "deactivate":
            print("active after:", n8n.set_active(config.get("activity.workflow_id"), False))
            return
        if a.cmd == "backfill":
            rep = amod.backfill_employment(run, amod.Checker(run))
            print(json.dumps(rep))
            rows, srep = peoplemod.sync(run, push=not a.no_sheet)
            peoplemod.log_exclusions(run, rows)
            print(run.write_summary())
            return
        if a.cmd == "status":
            c = amod.cache(run)
            print(json.dumps({"cached_profiles": len(c), "state": read_json(f.activity_state, {})}, indent=2))
            return
        if a.cmd == "skip":
            if not a.note:
                sys.exit("--note is required: say why the activity check is skipped (user decision)")
            write_json(f.activity_skipped, {"skipped_at": now_iso(), "note": a.note})
            run.log("activity", "skipped", a.note)
            peoplemod.sync(run, push=not a.no_sheet)
            print(run.write_summary())
            return
        with run.lock():
            rep = amod.run_activity(run, limit=a.limit, resume=a.resume)
            print(json.dumps(rep, indent=2, default=str))
            run.log("activity", "check", "%s profiles, counts %s, tab %s" % (rep["to_check"], rep["counts"], rep["tab"]),
                    rep["counts"] or {})
            rows, srep = peoplemod.sync(run, push=not a.no_sheet)
            print("sheet:", srep)
            peoplemod.log_exclusions(run, rows)
            print(run.write_summary())
    except (RunError, amod.ActivityError, n8n.N8nError, peoplemod.PeopleError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
