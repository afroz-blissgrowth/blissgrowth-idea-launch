#!/usr/bin/env python3
"""Save an agreed brief: validate, create the run folder and Google Sheet, write the '1 Brief' tab.

  python3 -I bin/brief_save.py --brief /path/to/draft-brief.json [--memo-file memo.md] [--no-sheet] [--date YYYY-MM-DD] [--new-run]

Safe to re-run: the newest run folder for the slug is reused (any date; --new-run or --date starts a
fresh one), an existing sheet is reused,
and a changed brief.json is archived as brief.json.old-<timestamp> before the new one is written.
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import brief as briefmod  # noqa: E402
import config  # noqa: E402
import schema  # noqa: E402
import sheet as sheetmod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import atomic_write, now_iso, read_json, write_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--memo-file")
    ap.add_argument("--date")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--new-run", action="store_true", help="start a new dated run folder even if one exists for the slug")
    a = ap.parse_args()
    try:
        brief = briefmod.load(a.brief)
    except briefmod.BriefError as e:
        sys.exit("error: %s" % e)
    errs = briefmod.validate(brief)
    if errs:
        sys.exit("brief is not valid:\n  - " + "\n  - ".join(errs))
    idea = brief["idea"]
    run = None
    if not a.date and not a.new_run:
        try:
            run = Run.resolve(idea["slug"])  # revising a brief on a later day must not fork a second run and sheet
            print("reusing run folder:", run.dir.name)
        except RunError:
            run = None
    run = run or Run.create(idea["slug"], a.date)
    text = json.dumps(brief, indent=2, ensure_ascii=False) + "\n"
    if run.brief_path.exists() and run.brief_path.read_text(encoding="utf-8") != text:
        shutil.copy(run.brief_path, str(run.brief_path) + ".old-" + now_iso().replace(":", ""))
        print("existing brief.json differed, archived the old one")
    atomic_write(run.brief_path, text)
    if a.memo_file:
        shutil.copy(a.memo_file, run.dir / "memo.md")
    sid = run.sheet_id()
    if not a.no_sheet:
        sc = sheetmod.SheetClient()
        if not sid:
            title = "%s %s | Idea Launch%s" % (run.dir.name[:10], idea["name"], " (TEST)" if idea.get("test") else "")
            res = sc.create(title)
            sid = res["spreadsheetId"]
            write_json(run.sheet_path, {"sheet_id": sid, "url": res["url"].split("?")[0], "title": title,
                                        "created_at": now_iso(), "tabs": res["tabs"]})
            print("created sheet:", run.sheet()["url"])
            share_cfg = config.get("sheet.share") or {}
            if share_cfg.get("auto_on_create") and (share_cfg.get("domain") or share_cfg.get("emails")):
                try:
                    r = sc.share(sid, domain=share_cfg.get("domain"), emails=share_cfg.get("emails"),
                                 role=share_cfg.get("role", "writer"))
                    print("shared:", ", ".join("%s (%s)" % (x["target"], "ok" if x["ok"] else x["error"]) for x in r["shared"]))
                except sheetmod.SheetError as e:  # never block the brief on sharing
                    print("WARNING: sheet created but NOT shared (%s). Share it by hand." % e)
        else:
            print("reusing sheet:", run.sheet()["url"])
        up = sc.upsert(sid, schema.TAB_BRIEF, "key", briefmod.to_rows(brief))
        print("'%s' tab: %d new, %d updated rows" % (schema.TAB_BRIEF, up["appended"], up["updated"]))
    run.update_state(brief_sha=briefmod.sha(brief), idea=idea["name"], test=bool(idea.get("test")))
    run.log("brief", "saved", "brief.json saved%s" % (", sheet created" if sid else ""),
            {"filter_sets": len(brief["apollo"]["filter_sets"])}, sheet=bool(sid) and not a.no_sheet)
    print(run.write_summary())
    print("run folder:", run.dir)


if __name__ == "__main__":
    main()
