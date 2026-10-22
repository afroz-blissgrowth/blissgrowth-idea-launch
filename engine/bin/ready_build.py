#!/usr/bin/env python3
"""Stage 9: assign channels and fill the three Ready tabs (+ list quality grade).

  python3 -I bin/ready_build.py <run> [--no-sheet]
T1: LinkedIn + email + call. T2: LinkedIn + email. Inactive profiles lose LinkedIn, non-`ok` emails lose email, no phone
loses call. Tabs: 5 Ready: LinkedIn, 6 Ready: Email, 7 Ready: Calls (T1 with a phone, for the cold caller).
Rows are never deleted; people who stop qualifying are marked status=withdrawn.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import people as peoplemod  # noqa: E402
import ready as rmod  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        with run.lock():
            rep = rmod.build(run, push=not a.no_sheet)
            print(rep)
            run.log("ready", "built", "LinkedIn %(linkedin)d, Email %(email)d, Calls %(calls)d, list grade %(grade)s" % rep,
                    {k: rep[k] for k in ("linkedin", "email", "calls", "withdrawn")})
            peoplemod.log_exclusions(run, peoplemod.load_table(run))
            print(run.write_summary())
    except (RunError, peoplemod.PeopleError, RuntimeError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
