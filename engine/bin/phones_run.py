#!/usr/bin/env python3
"""Stage 8: phones for T1 people only (Apollo async reveal, 8 credits per mobile found).

  python3 -I bin/phones_run.py request <run> --dry-run      who would be requested (T1, selected, enriched), expected cost
  python3 -I bin/phones_run.py request <run> [--limit N]    bulk_match with reveal_phone_number + webhook, then poll the
                                                            n8n data table "IL Phone Results" until results arrive
  python3 -I bin/phones_run.py request <run> --no-wait      send the requests and return; collect later
  python3 -I bin/phones_run.py collect <run>                read the receiver table and record arrived numbers
  python3 -I bin/phones_run.py skip <run> --note "why"      skip phones on the user's say-so
  python3 -I bin/phones_run.py status <run>
Needs the receiver once: python3 -I workflows/deploy_phone_webhook.py. Prospeo and Amplemarket fallbacks are hooks only.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import apollo  # noqa: E402
import config  # noqa: E402
import n8n  # noqa: E402
import people as peoplemod  # noqa: E402
import phones as pmod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import now_iso, write_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["request", "collect", "skip", "status"])
    ap.add_argument("run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--rerequest-stale", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        f = peoplemod.Files(run)
        if a.cmd == "skip":
            if not a.note:
                sys.exit("--note is required: say why phones are skipped (user decision)")
            write_json(f.phones_skipped, {"skipped_at": now_iso(), "note": a.note})
            run.log("phones", "skipped", a.note)
            print(run.write_summary())
            return
        if a.cmd == "status":
            st = pmod.state(run)
            c = {}
            for r in st.values():
                c[r["status"]] = c.get(r["status"], 0) + 1
            print(json.dumps({"people": c}, indent=2))
            return
        with run.lock():
            if a.cmd == "collect":
                print(pmod.collect(run))
            else:
                rows = peoplemod.rebuild(run)
                todo = pmod.candidates(rows, pmod.state(run), a.rerequest_stale)
                if a.dry_run:
                    n = len(todo)
                    print(json.dumps({"t1_people_to_request": n, "credits_max": n * config.get("phones.credits_per_mobile", 8),
                                      "note": "8 credits per mobile actually found; nothing for people with no number"}))
                    return
                client = apollo.ApolloClient(usage_log=run.usage_log, label="phones")
                rep = pmod.run_phones(run, client, limit=a.limit, poll=not a.no_wait, rerequest_stale=a.rerequest_stale)
                print(json.dumps(rep, indent=2))
                run.log("phones", "request", "requested %(requested)d, received %(received)d, none %(none)d, waiting "
                        "%(still_waiting)d, credits %(credits)s" % rep, rep)
            rows, srep = peoplemod.sync(run, push=not a.no_sheet)
            print("sheet:", srep)
            print(run.write_summary())
    except (RunError, pmod.PhoneError, apollo.ApolloError, n8n.N8nError, peoplemod.PeopleError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
