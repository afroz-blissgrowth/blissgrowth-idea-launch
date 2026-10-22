#!/usr/bin/env python3
"""Build or search the copy library from campaigns already launched in the Bliss HeyReach workspace (READ ONLY).

  python3 -I bin/copy_library.py build [--out copy-library]      pull every non-draft campaign sequence + stats, template,
                                                                 write one file per campaign plus index.md / index.json
  python3 -I bin/copy_library.py search [--idea X] [--persona X] [--sender X] [--kind inmail|invite|message] [--top N]
                                                                 list library campaigns ranked by reply rate (min leads 20)
Only GET and read-style POST calls are made (campaign/GetAll, GetCampaignSequence, GetOverallStats). Nothing is created.
Re-running overwrites the library files with fresh numbers.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
import copylib  # noqa: E402
import heyreach  # noqa: E402

DEFAULT_OUT = config.IDEA_LAUNCH_DIR / "copy-library"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "search"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--idea")
    ap.add_argument("--persona")
    ap.add_argument("--sender")
    ap.add_argument("--kind")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-leads", type=int, default=20)
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            res = copylib.build(heyreach.HeyReach(), a.out)
            print("library: %d campaigns written to %s, %d skipped" % (res["campaigns"], a.out, len(res["skipped"])))
            for s in res["skipped"]:
                print("  skipped %s: %s" % (s["name"], s["why"]))
        else:
            idx = json.load(open(os.path.join(a.out, "index.json"), encoding="utf-8"))
            rows = []
            for c in idx["campaigns"]:
                if a.idea and a.idea.lower() not in (c["idea"] or "").lower():
                    continue
                if a.persona and not any(a.persona.lower() in p.lower() for p in c["persona"]):
                    continue
                if a.sender and a.sender.lower() not in (c["sender"] or "").lower():
                    continue
                if c["leads"] < a.min_leads:
                    continue
                s = c["stats"]
                if a.kind == "inmail":
                    rate = s.get("inMailReplyRate") if s.get("inmailMessagesSent") else None
                elif a.kind == "invite":
                    rate = s.get("connectionAcceptanceRate") if s.get("connectionsSent") else None
                else:
                    rate = s.get("messageReplyRate") if s.get("messagesSent") else None
                if rate is None:
                    continue
                rows.append((rate, c))
            rows.sort(key=lambda x: -x[0])
            for rate, c in rows[:a.top]:
                print("%5.1f%%  %-9s leads %-4s %s  [%s]  %s" % (rate * 100, c["id"], c["leads"], c["name"][:62], c["structure"], c["file"]))
    except heyreach.HeyReachError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
