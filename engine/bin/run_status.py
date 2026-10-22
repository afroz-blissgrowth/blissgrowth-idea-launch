#!/usr/bin/env python3
"""Show where a run stands and rewrite summary.md.   python3 -I bin/run_status.py <run>   (or --list)"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
from run import Run, RunError  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", nargs="?")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.run:
        for p in sorted(config.lists_dir().glob("*")):
            if (p / "brief.json").exists():
                first = (p / "summary.md").read_text().splitlines()[0] if (p / "summary.md").exists() else "(no summary)"
                print("%s  %s" % (p.name, first))
        return
    try:
        run = Run.resolve(a.run)
    except RunError as e:
        sys.exit("error: %s" % e)
    print(run.write_summary())
    print(json.dumps(run.stage_status(), indent=2))


if __name__ == "__main__":
    main()
