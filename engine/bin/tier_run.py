#!/usr/bin/env python3
"""Stage 5: T1 / T2 tiering of the people by Claude subagents, then caps. Subcommands:

  show-spec <run>                         print the starting spec built from brief.tier_rules (agreed in /iv-brief)
  set-spec <run> --spec-file spec.json    build tier/prompt.md from a spec (3 mandatory blocks enforced)
  sample <run> --round N [--n 10]         write tier/batches/sample-rN.json (10 people over different companies)
  sample-report <run> --round N           show the sample results as a table (after the subagent wrote them)
  tune-log <run> --round N --corrections K [--simulated]     record the user's review; prints the clean streak
  lock <run> [--force] [--simulated]      lock the prompt (needs 2 clean rounds, or --force on the user's say-so)
  batches <run> [--size 30] [--reissue]   batch files for people still waiting (grouped by company)
  ingest <run> [files...]                 validate and ingest result files
  retry <run>                             one retry pass for people with no valid answer
  status <run>                            counts, open batches, clean streak
  skip <run> --note "why"                 skip tiering on the user's say-so (title priority picks people, T2 channels)
  finalize <run>                          enforce caps, rebuild people.csv, update the sheet, summary.md

A Claude subagent reads tier/batches/batch-NNNN.json plus tier/prompt.md and writes batch-NNNN.result.json.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
import tier as tmod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import now_iso, read_json, write_json  # noqa: E402


def table(rows):
    print("%-28s | %-34s | %-5s | %-4s | %s" % ("Company", "Title", "Hint", "Tier", "Reason"))
    print("-" * 130)
    for r in rows:
        print("%-28s | %-34s | %-5s | %-4s | %s" % (r["company"][:28], r["title"][:34], r["hint"][:5], r["tier"], r["reason"]))


def ingest(t, files, force, quiet=False):
    files = files or sorted(str(p) for p in (t.dir / "batches").glob("batch-*.result.json"))
    done = read_json(t.dir / "ingested.json", {})
    tot = {"ok": 0, "invalid": 0, "missing": 0}
    for f in files:
        key = os.path.basename(f) + ":" + str(int(os.path.getmtime(f)))
        if key in done and not force:
            continue
        rep = t.ingest_file(f)
        for k in tot:
            tot[k] += rep[k]
        if not quiet:
            print("%s: ok=%d invalid=%d missing=%d %s" % (rep["batch"], rep["ok"], rep["invalid"], rep["missing"], "; ".join(rep["problems"][:3])))
        if not rep["missing"] and not rep["invalid"]:
            done[key] = True
            write_json(t.dir / "ingested.json", done)
    if not quiet:
        print("total:", tot)
    return tot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["show-spec", "set-spec", "sample", "sample-report", "tune-log", "lock", "batches",
                                    "ingest", "retry", "status", "skip", "finalize"])
    ap.add_argument("run")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--spec-file")
    ap.add_argument("--round", type=int)
    ap.add_argument("--n", type=int)
    ap.add_argument("--size", type=int)
    ap.add_argument("--corrections", type=int)
    ap.add_argument("--note", default="")
    ap.add_argument("--reissue", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--simulated", action="store_true", help="label a tuning round as simulated (not reviewed by the user)")
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        t = tmod.Tier(run)
        if a.cmd == "show-spec":
            print(json.dumps(tmod.spec_from_brief(run.brief()), indent=2))
        elif a.cmd == "set-spec":
            t.set_spec(json.load(open(a.spec_file, encoding="utf-8")))
            print("prompt written:", t.prompt_path)
            run.log("tier", "prompt_set", "spec updated, prompt rebuilt")
        elif a.cmd == "sample":
            if not t.prompt_path.exists():
                sys.exit("no prompt yet: run set-spec first")
            p = t.sample_batch(a.round or 1, a.n)
            print("sample batch:", p)
            print("result file the subagent must write:", str(p).replace(".json", ".result.json"))
        elif a.cmd == "sample-report":
            table(t.sample_report(a.round or 1))
        elif a.cmd == "tune-log":
            streak = t.log_round(a.round, a.corrections, a.note, a.simulated)
            need = config.get("tier.clean_rounds_needed")
            print("clean streak: %d of %d needed%s%s" % (streak, need, " -> ready to lock" if streak >= need else "",
                                                        " (SIMULATED review)" if a.simulated else ""))
        elif a.cmd == "lock":
            streak, need = t.clean_streak(), config.get("tier.clean_rounds_needed")
            if streak < need and not a.force:
                sys.exit("clean streak is %d, need %d. Run more tuning rounds or pass --force (user decision)." % (streak, need))
            t.lock(len(t.tuning()["rounds"]), a.note, simulated=a.simulated)
            run.log("tier", "prompt_locked", "rounds=%d streak=%d%s%s" % (len(t.tuning()["rounds"]), streak,
                    " (forced)" if streak < need else "", " SIMULATED review" if a.simulated else ""))
            print("prompt locked")
        elif a.cmd in ("batches", "retry"):
            if not t.is_locked() and not a.force:
                sys.exit("prompt is not locked. Finish tuning and run lock (or pass --force).")
            if t.f.tier_skipped.exists():
                sys.exit("tiering was skipped for this run (tier/skipped.json). Delete it to tier after all.")
            with run.lock():
                tot = ingest(t, [], False, quiet=True)
                if any(tot.values()):
                    print("ingested waiting result files first:", tot)
                if a.cmd == "retry":
                    st = read_json(t.dir / "retry.json", {"passes": 0})
                    if st["passes"] >= 1 and not a.force:
                        sys.exit("the one automatic retry pass was already used. Inspect status, or pass --force.")
                    st["passes"] += 1
                    write_json(t.dir / "retry.json", st)
                res = t.make_batches(a.size, a.reissue)
                print(json.dumps({"people_needing_a_tier": res["pending"], "skipped_in_flight": res["skipped_in_flight"],
                                  "batches_written": len(res["batches"])}))
                for b in res["batches"]:
                    print(b)
                run.log("tier", a.cmd, "%d batches for %d people" % (len(res["batches"]), res["pending"]),
                        {"batches": len(res["batches"]), "people": res["pending"]})
        elif a.cmd == "ingest":
            tot = ingest(t, a.files, a.force)
            run.log("tier", "ingest", json.dumps(tot), tot)
        elif a.cmd == "status":
            print(json.dumps(t.status(), indent=2))
        elif a.cmd == "skip":
            if not a.note:
                sys.exit("--note is required: say why tiering is skipped (user decision)")
            write_json(t.f.tier_skipped, {"skipped_at": now_iso(), "note": a.note})
            run.log("tier", "skipped", a.note)
            print("tiering skipped; run finalize")
        elif a.cmd == "finalize":
            with run.lock():
                tot = ingest(t, [], False, quiet=True)
                res = t.finalize(push=not a.no_sheet)
                print(json.dumps(res))
                run.log("tier", "finalize", "caps %s, selected %s" % (res["caps"], res["selected_by_tier"]),
                        {"selected": res["selected_by_tier"], "cap_status": res["cap_status"]})
        run.write_summary()
        if a.cmd == "finalize":
            print(run.summary_path.read_text().splitlines()[0])
    except (RunError, RuntimeError, ValueError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
