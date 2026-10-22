#!/usr/bin/env python3
"""Stage 6: Apollo bulk_match for the capped people (credits), then MillionVerifier, then the list quality report.

  python3 -I bin/enrich_verify.py enrich <run> --dry-run        who would be enriched, expected credits (nothing sent)
  python3 -I bin/enrich_verify.py enrich <run> [--limit N]      people/bulk_match, 10 per call, real credits logged
  python3 -I bin/enrich_verify.py verify <run> [--limit N]      MillionVerifier on the emails (needs MILLIONVERIFIER_API_KEY)
  python3 -I bin/enrich_verify.py verify <run> --canary 20      verify a random 20 first and show the pass rate
  python3 -I bin/enrich_verify.py quality <run>                 list quality grade (8 checks) -> list-quality.md, summary, Run Log
  python3 -I bin/enrich_verify.py all <run> [--limit N]         enrich, verify (if the key exists), waterfall list, quality
  options: --no-sheet
Without the MillionVerifier key the verify step is skipped with a clear message (emails stay `unverified`, nothing is
lost, re-run once the key is in <repo>/.env). Missing or invalid emails are listed in enrich/waterfall-needed.csv.
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import apollo  # noqa: E402
import enrich as emod  # noqa: E402
import people as peoplemod  # noqa: E402
import pilot  # noqa: E402
import quality as qmod  # noqa: E402
import verify as vmod  # noqa: E402
import waterfall  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import append_jsonl  # noqa: E402

NOKEY = ("MILLIONVERIFIER_API_KEY is not in <repo>/.env: SKIPPING email verification. Emails stay 'unverified' "
         "and no Ready: Email rows are produced until it is added. Re-run the verify step then (nothing is lost).")


def do_enrich(run, a):
    rows = peoplemod.rebuild(run)
    est = emod.estimate(rows)
    if a.dry_run:
        print(json.dumps(est, indent=2))
        return
    if not pilot.gate_open_for_enrich(run):
        st = pilot.people_state(run)
        sys.exit("error: enrichment spends credits and is blocked by the people pilot gate (%s). Run pilot_run.py people start %s, "
                 "have the user review the pilot, then approve (or skip by a user decision)." % (st["detail"], run.dir.name))
    client = apollo.ApolloClient(usage_log=run.usage_log, label="enrich")
    rep = emod.run_enrich(run, client, limit=a.limit)
    print("enrich:", rep)
    run.log("enrich", "bulk_match", "%(requested)d requested, %(matched)d matched, %(with_email)d with email, "
            "credits %(credits)s" % rep, rep)
    if rep["paused"]:
        print("PAUSED:", rep["paused"])


def do_verify(run, a, soft=False):
    if not vmod.key_available():
        print(NOKEY)
        run.log("verify", "skipped", "MILLIONVERIFIER_API_KEY missing")
        return 0 if soft else 2
    if a.canary:
        rows = peoplemod.rebuild(run)
        todo = vmod.todo_emails(rows, vmod.cache(run))
        random.Random(run.dir.name).shuffle(todo)
        sample = todo[: a.canary]
        mv = vmod.MillionVerifier()
        res = {}
        for e in sample:
            r = mv.verify(e)
            append_jsonl(peoplemod.Files(run).mv, r)
            res[r["result"]] = res.get(r["result"], 0) + 1
        ok = res.get("ok", 0)
        print("canary of %d emails: %s, ok rate %.0f%%" % (len(sample), res, 100.0 * ok / max(len(sample), 1)))
        run.log("verify", "canary", json.dumps(res), res)
        return 0
    rep = vmod.run_verify(run, limit=a.limit)
    print("verify:", rep)
    run.log("verify", "millionverifier", "%(checked)d of %(to_check)d checked: %(results)s" % rep, rep["results"])
    if rep["fatal"]:
        print("STOPPED:", rep["fatal"])
        return 2
    return 0


def do_quality(run):
    rows = peoplemod.rebuild(run)
    by = waterfall.write_list(run, rows)
    rep = qmod.write_report(run, rows)
    print("list quality: grade %s (%s/100) on %d rows" % (rep["grade"], rep["score"], rep["rows"]))
    for d in rep["dims"]:
        print("  %-24s %3d  %s" % (d["name"], d["score"], d["detail"]))
    for i in rep["issues"]:
        print("  issue:", i)
    print("waterfall needed:", by or "none")
    run.log("quality", "list_quality", "grade %s (%s/100), %d rows. %s" % (rep["grade"], rep["score"], rep["rows"],
            "; ".join(rep["issues"][:2])), {"grade": rep["grade"], "score": rep["score"], "rows": rep["rows"],
                                            "waterfall": by})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["enrich", "verify", "quality", "all"])
    ap.add_argument("run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--canary", type=int)
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    code = 0
    try:
        run = Run.resolve(a.run)
        with run.lock():
            if a.cmd in ("enrich", "all"):
                do_enrich(run, a)
                if a.dry_run:
                    return
            if a.cmd in ("verify", "all"):
                code = do_verify(run, a, soft=a.cmd == "all")
            if a.cmd in ("quality", "all", "verify", "enrich"):
                do_quality(run)
            rows, rep = peoplemod.sync(run, push=not a.no_sheet)
            print("sheet:", rep)
            peoplemod.log_exclusions(run, rows)
            print(run.write_summary())
    except (RunError, peoplemod.PeopleError, apollo.ApolloError, vmod.MVError) as e:
        sys.exit("error: %s" % e)
    sys.exit(code)


if __name__ == "__main__":
    main()
