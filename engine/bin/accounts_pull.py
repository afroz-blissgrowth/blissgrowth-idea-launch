#!/usr/bin/env python3
"""Stage 2: Apollo company search from the run's brief.json.

  python3 -I bin/accounts_pull.py <run> --dry-run           count first, show estimate, write accounts.plan.json
  python3 -I bin/accounts_pull.py <run> --pilot [N]         pull the PILOT (10 to 20, default 15) for the human review, see pilot_run.py
  python3 -I bin/accounts_pull.py <run> --limit 25          small test pull (page 1 only, no counting)
  python3 -I bin/accounts_pull.py <run>                     full pull (resumes where it stopped). REFUSED until the accounts pilot is approved
                                                            (or skipped by the user, or the run predates the gate)
  options: --no-sheet  --accept-brief-change

<run> is a folder path, a folder name under runs, or the idea slug (newest match).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import accounts  # noqa: E402
import brief as briefmod  # noqa: E402
import pilot  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--pilot", nargs="?", const=-1, type=int, help="pull the pilot (size 10 to 20, default from config)")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--accept-brief-change", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        brief = run.brief()
        errs = briefmod.validate(brief)
        if errs:
            sys.exit("brief.json is not valid:\n  - " + "\n  - ".join(errs))
        if a.pilot is not None and not a.dry_run:
            with run.lock():
                ids = pilot.start_accounts(run, brief, None if a.pilot == -1 else a.pilot, push=not a.no_sheet)
                run.log("pilot", "accounts_started", "pilot of %d accounts" % len(ids), {"size": len(ids)})
                print("pilot of %d accounts pulled. Next: signals_run.py run %s --scope pilot, qualify, then the user's review." % (len(ids), run.dir.name))
                print(run.write_summary())
            return
        if not a.dry_run and not a.limit and not pilot.gate_open_for_full_pull(run):
            st = pilot.accounts_state(run)
            sys.exit("error: the full account pull is blocked by the pilot gate (%s). Run the pilot first: pilot_run.py accounts start %s "
                     "(or accounts_pull.py --pilot), review it, then approve. A user decision can skip the gate: pilot_run.py accounts skip."
                     % (st["detail"], run.dir.name))
        with run.lock():
            if a.dry_run:
                plan = accounts.dry_run(run, brief)
                print(accounts.format_plan(plan))
                print("\nPlan saved to %s. Run again without --dry-run to pull." % accounts.plan_path(run))
            else:
                res = accounts.execute(run, brief, limit=a.limit, accept_brief_change=a.accept_brief_change,
                                       push=not a.no_sheet)
                print("accounts: %(accounts)d (duplicates merged %(duplicates)d, excluded %(excluded)d)" % res)
            print(run.write_summary())
    except (RunError, briefmod.BriefError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
