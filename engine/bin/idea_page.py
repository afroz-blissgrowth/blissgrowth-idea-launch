#!/usr/bin/env python3
"""Stage 11: reply-agent idea page (Notion database "Idea Contexts", Blissgrowth workspace).

  python3 -I bin/idea_page.py starter <run>                    print a starting set of fields from the brief (Claude rewrites it from the memo)
  python3 -I bin/idea_page.py set-fields <run> --file f.json   validate and save the drafted fields (idea-page/fields.json)
  python3 -I bin/idea_page.py show <run>                       show the fields exactly as they will be written, plus warnings
  python3 -I bin/idea_page.py confirm <run> --note "who confirmed" [--simulated]    the USER confirmed the text
  python3 -I bin/idea_page.py payload <run> [--test]           the exact Notion MCP call (notion-create-pages) to make
  python3 -I bin/idea_page.py record <run> --url <notion url> [--test] [--adopt]   store the created (or existing) page link
  python3 -I bin/idea_page.py skip <run> --note "why"          skip the stage on the user's say-so
  python3 -I bin/idea_page.py status <run>
  python3 -I bin/idea_page.py sync-check <run>                 is the page in the n8n table HRA Ideas? (read only)
The page itself is created by Claude with the Notion MCP tools (no Notion API key); this script prepares, checks and records.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import ideapage  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["starter", "set-fields", "show", "confirm", "payload", "record", "skip", "status", "sync-check"])
    ap.add_argument("run")
    ap.add_argument("--file")
    ap.add_argument("--note", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--adopt", action="store_true", help="the page already existed in Notion")
    ap.add_argument("--simulated", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        ip = ideapage.IdeaPage(run)
        if a.cmd == "starter":
            print(json.dumps(ip.starter(), indent=2, ensure_ascii=False))
        elif a.cmd == "set-fields":
            warns = ip.set_fields(json.load(open(a.file, encoding="utf-8")))
            print("fields saved:", ip.fields_path)
            for w in warns:
                print("warning:", w)
        elif a.cmd == "show":
            f = ip.fields()
            if not f:
                sys.exit("no fields yet: run starter, rewrite from the memo, then set-fields")
            for k, v in f.items():
                print("## %s\n%s\n" % (k, v))
            errs, warns = ip.validate(f)
            for e in errs:
                print("ERROR:", e)
            for w in warns:
                print("warning:", w)
            print("confirmed by the user:", ip.confirmed())
        elif a.cmd == "confirm":
            print(json.dumps(ip.confirm(a.note, a.simulated), indent=2))
            run.log("idea_page", "confirmed", a.note + (" (SIMULATED)" if a.simulated else ""))
        elif a.cmd == "payload":
            print(json.dumps(ip.payload(a.test), indent=2, ensure_ascii=False))
        elif a.cmd == "record":
            r = ip.save_record(a.url, test=a.test, existing=a.adopt, simulated=a.simulated)
            run.log("idea_page", "recorded", r["page_url"] + (" (TEST)" if a.test else ""))
            print(json.dumps(r, indent=2))
        elif a.cmd == "skip":
            ip.skip(a.note)
            run.log("idea_page", "skipped", a.note)
            print("idea page stage skipped")
        elif a.cmd == "status":
            print(json.dumps({"record": ip.record(), "fields": bool(ip.fields()), "confirmed": ip.confirmed(),
                              "skipped": ip.skip_path.exists()}, indent=2))
        elif a.cmd == "sync-check":
            print(json.dumps(ip.sync_status(), indent=2))
        run.write_summary()
    except (RunError, ideapage.IdeaPageError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
