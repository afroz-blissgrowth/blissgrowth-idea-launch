#!/usr/bin/env python3
"""Debug and admin helper for the Sheets Bridge.

  python3 -I bin/sheet_tool.py ping                                (creates nothing; checks secret + bridge are alive)
  python3 -I bin/sheet_tool.py read <sheet_id> "<tab>" [--raw]
  python3 -I bin/sheet_tool.py format <sheet_id>
  python3 -I bin/sheet_tool.py ensure-schema <sheet_id>            add any new schema columns to an existing sheet's tabs
  python3 -I bin/sheet_tool.py share <sheet_id> [--domain d] [--email a@b.c ...] [--role writer]
                                                                  (default: sheet.share in config.json)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
import sheet  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ping", "read", "format", "ensure-schema", "share"])
    ap.add_argument("sheet_id", nargs="?")
    ap.add_argument("tab", nargs="?")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--domain")
    ap.add_argument("--email", action="append", default=[])
    ap.add_argument("--role")
    a = ap.parse_args()
    c = sheet.SheetClient()
    try:
        if a.cmd == "ping":
            try:
                c.call({"action": "bogus"})
            except sheet.SheetError as e:
                print("bridge reachable:", e)
        elif a.cmd == "read":
            for row in c.read(a.sheet_id, a.tab, a.raw):
                print(json.dumps(row, ensure_ascii=False))
        elif a.cmd == "ensure-schema":
            print(json.dumps(c.ensure_schema(a.sheet_id), indent=1) or "{}")
        elif a.cmd == "share":
            cfg = config.get("sheet.share") or {}
            res = c.share(a.sheet_id, domain=a.domain or (None if a.email else cfg.get("domain")),
                          emails=a.email or cfg.get("emails"), role=a.role or cfg.get("role", "writer"))
            print(json.dumps(res, indent=1))
        else:
            print(c.format(a.sheet_id))
    except sheet.SheetError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
