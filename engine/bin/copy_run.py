#!/usr/bin/env python3
"""Stage 10: per-run copy (LinkedIn invite, follow-ups, InMail): draft with Claude, check, tune with the user, approve, write.

  python3 -I bin/copy_run.py context <run>                 write copy/context.json: brief, tiers with people, slots to fill, rules, voices
  python3 -I bin/copy_run.py ingest <run> <draft.json>...  validate drafted items (strict JSON array), run the rule checker, store them
  python3 -I bin/copy_run.py show <run> [--sample] [--tier T1]   the copy as the user should read it (all variants, word counts, flags)
  python3 -I bin/copy_run.py check <run>                   re-run the rule checker over stored items and list blockers
  python3 -I bin/copy_run.py withdraw <run> <item id>      remove one item (ids look like li_followup|T1|2|V3)
  python3 -I bin/copy_run.py tune-log <run> --round N --corrections K [--note ..] [--simulated]   record the user's review
  python3 -I bin/copy_run.py approve <run> --note "who approved" [--simulated]   explicit approval of exactly these items
  python3 -I bin/copy_run.py write <run> [--no-sheet]      copy.json and the "8 Copy" tab (status draft until approved)
  python3 -I bin/copy_run.py status <run>
An item: {channel li_invite|li_followup|inmail, tier T1|T2|all, step, variant V1..V4|blank, subject (InMail), body, sender founder|associate,
fallback?, note?}. Rules: lib/copyrules.py and config.json `copy`. Never approve without the user's explicit yes.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import copydraft  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["context", "ingest", "show", "check", "withdraw", "tune-log", "approve", "write", "status"])
    ap.add_argument("run")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--tier")
    ap.add_argument("--round", type=int)
    ap.add_argument("--corrections", type=int)
    ap.add_argument("--note", default="")
    ap.add_argument("--simulated", action="store_true", help="label a review or approval nobody gave (tests only)")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        cd = copydraft.CopyDraft(run)
        if a.cmd == "context":
            print(json.dumps(cd.context(), indent=2, ensure_ascii=False))
        elif a.cmd == "ingest":
            tot = {"ok": 0, "blocked": 0, "rejected": 0}
            for f in a.files:
                rep = cd.ingest(f, round_label=os.path.basename(f))
                print("%s: ok %d, blocked by rules %d, rejected %d" % (os.path.basename(f), rep["ok"], rep["blocked"], len(rep["rejected"])))
                for r in rep["rejected"]:
                    print("  rejected item %d: %s" % (r["index"], "; ".join(r["problems"])))
                tot["ok"] += rep["ok"]
                tot["blocked"] += rep["blocked"]
                tot["rejected"] += len(rep["rejected"])
            for r in cd.items():
                if r["status"] == "blocked":
                    print("  BLOCKED %s: %s" % (r["id"], "; ".join("%s (%s)" % (e["rule"], e["detail"]) for e in r["errors"])))
            run.log("copy", "ingest", json.dumps(tot), tot)
        elif a.cmd == "show":
            print(cd.render(sample=a.sample, tier=a.tier))
        elif a.cmd == "check":
            n = cd.recheck()
            c = cd.completeness()
            print(json.dumps({"rechecked_changed": n, **c}, indent=2))
        elif a.cmd == "withdraw":
            cd.withdraw(a.files[0])
            print("withdrawn", a.files[0])
        elif a.cmd == "tune-log":
            clean = cd.log_round(a.round, a.corrections, a.note, a.simulated)
            print("round %d logged%s%s" % (a.round, ", clean (user had no changes): you may approve" if clean else ", corrections: fix, re-ingest, review again",
                                        " (SIMULATED review)" if a.simulated else ""))
            run.log("copy", "tune_round", "round %s corrections %s%s" % (a.round, a.corrections, " SIMULATED" if a.simulated else ""))
        elif a.cmd == "approve":
            ap_ = cd.approve(a.note, a.simulated)
            run.log("copy", "approved", a.note + (" (SIMULATED approval, not a real user)" if a.simulated else ""))
            print(json.dumps(ap_, indent=2))
        elif a.cmd == "write":
            with run.lock():
                rep = cd.write(push=not a.no_sheet)
                print(json.dumps(rep))
                run.log("copy", "written", "copy.json + 8 Copy (%d items, approved %s)" % (rep["items"], rep["approved"]), rep)
        elif a.cmd == "status":
            print(json.dumps(cd.status(), indent=2))
        run.write_summary()
    except (RunError, copydraft.CopyError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
