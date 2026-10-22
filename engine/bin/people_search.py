#!/usr/bin/env python3
"""Stage 4: Apollo people search, one company per call, T1 and T2 titles together (0 credits).

  python3 -I bin/people_search.py <run> --dry-run                 pool size, calls needed, time estimate, nothing sent
  python3 -I bin/people_search.py <run> [--limit-orgs N]          search companies not yet in the ledger (resumes)
  python3 -I bin/people_search.py <run> --finalize                rebuild people.csv and update the sheet only
  options: --no-sheet  --accept-query-change

Companies with no people go to the "3 Accounts: No People" tab (reason column); everyone else to "4 People".
Rate limits on this key: 200 per minute, 6,000 per hour (shared with every other Apollo call). The per-company ledger
(people/search.ledger.jsonl) makes the run resumable; the script stops cleanly when the hourly budget is nearly used.
<run> is a folder path, a folder name under runs, or the idea slug (newest match).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import apollo  # noqa: E402
import config  # noqa: E402
import people as peoplemod  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-orgs", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--accept-query-change", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        brief = run.brief()
        q = peoplemod.search_query(brief)
        if a.dry_run:
            pool = peoplemod.pool_accounts(run)
            done = peoplemod.ledger(run)
            todo = [o for o in pool if done.get(o["org_id"], {}).get("status") not in ("found", "none")]
            per_min = 60.0 / config.get("apollo.min_interval_s", 0.35)
            print("pool (keep + review): %d companies, already searched: %d, to search: %d" % (len(pool), len(pool) - len(todo), len(todo)))
            print("query: %d titles (T1 + T2 together), seniorities %s, similar titles %s" % (
                len(q["titles"]), ",".join(q["seniorities"]) or "any", q["include_similar_titles"]))
            print("calls: about %d (1 per company, more only above %d people), credits: 0" % (len(todo), config.get("people.per_page")))
            print("time: about %.0f minutes at the client's pace (%d per minute); the key allows 200 per minute and 6,000 per hour" % (
                len(todo) / min(per_min, 180.0), min(per_min, 180)))
            return
        with run.lock():
            if not a.finalize:
                client = apollo.ApolloClient(usage_log=run.usage_log, label="people")
                rep = peoplemod.run_search(run, brief, client, limit_orgs=a.limit_orgs,
                                           accept_query_change=a.accept_query_change)
                print("search: %s" % rep)
                run.log("people", "search", "searched %(searched)d companies: %(found)d with people, %(none)d without, "
                        "%(errors)d errors, %(people)d people" % rep, {k: rep[k] for k in ("searched", "found", "none", "errors", "people")})
                if rep["paused"]:
                    print("PAUSED:", rep["paused"])
            rows, sheet_rep = peoplemod.sync(run, brief, push=not a.no_sheet)
            print("people.csv: %d people. sheet: %s" % (len(rows), sheet_rep))
            run.log("people", "finalize", "people.csv rebuilt, %d people" % len(rows), {"people": len(rows)})
            print(run.write_summary())
    except (RunError, peoplemod.PeopleError, apollo.ApolloError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
