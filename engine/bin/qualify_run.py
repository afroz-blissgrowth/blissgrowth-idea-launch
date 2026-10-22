#!/usr/bin/env python3
"""Stage 3: qualify companies (AI fit check) with Claude subagents. Subcommands:

  set-spec <run> --spec-file spec.json     build qualify/prompt.md from a spec (4 mandatory blocks enforced)
  sample <run> --round N [--n 10]          fetch sites, write qualify/batches/sample-rN.json (tuning sample)
  sample-report <run> --round N            show the sample results as a table (after the subagent wrote them)
  tune-log <run> --round N --corrections K record the user's corrections for a round; prints the clean streak
  lock <run>                               lock the prompt (needs the clean streak, or --force)
  batches <run> [--size 25] [--reissue]    fetch missing sites, resolve dead/parked, write batch-NNNN.json files
  ingest <run> [files...]                  validate and ingest result files (default: all unanswered-ingest)
  retry <run>                              one retry pass: new batches for rows with errors or no result
  status <run>                             counts, open batches, clean streak
  finalize <run>                           qualified.csv, upsert the '2 Accounts' tab, run log, summary.md

<run> is a folder path, a folder name under runs, or the idea slug (newest match).
A Claude subagent reads batches/batch-NNNN.json and the prompt file and writes batch-NNNN.result.json.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
import qualify as qmod  # noqa: E402
from run import Run, RunError  # noqa: E402
from util import read_json, write_json  # noqa: E402


def table(rows):
    print("%-30s | %-6s | %-5s | %-4s | %s" % ("Company", "Site", "Qual", "Conf", "Reason"))
    print("-" * 110)
    for r in rows:
        q = {True: "YES", False: "NO", None: "?"}[r["qualified"]]
        print("%-30s | %-6s | %-5s | %-4s | %s" % ((r["name"] or r["domain"])[:30], (r["site"] or "")[:6], q,
                                                   "" if r["confidence"] is None else r["confidence"], r["reason"]))


def ingest(q, files, force, quiet=False):
    """Validate and ingest result files not ingested yet. Returns totals."""
    files = files or sorted(str(p) for p in (q.dir / "batches").glob("batch-*.result.json"))
    done = read_json(q.dir / "ingested.json", {})
    tot = {"ok": 0, "invalid": 0, "missing": 0}
    for f in files:
        key = os.path.basename(f) + ":" + str(int(os.path.getmtime(f)))
        if key in done and not force:
            continue
        rep = q.ingest_file(f)
        for k in tot:
            tot[k] += rep[k]
        if not quiet:
            print("%s: ok=%d invalid=%d missing=%d %s" % (rep["batch"], rep["ok"], rep["invalid"], rep["missing"],
                                                          ("; ".join(rep["problems"][:3]))))
        if not rep["missing"] and not rep["invalid"]:
            done[key] = True
            write_json(q.dir / "ingested.json", done)
    if not quiet:
        print("total:", tot)
    return tot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["set-spec", "sample", "sample-report", "tune-log", "lock", "batches", "ingest",
                                    "retry", "status", "finalize"])
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
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    try:
        run = Run.resolve(a.run)
        q = qmod.Qualify(run)
        if a.cmd == "set-spec":
            spec = json.load(open(a.spec_file, encoding="utf-8"))
            q.set_spec(spec)
            print("prompt written:", q.prompt_path)
            run.log("qualify", "prompt_set", "spec updated, prompt rebuilt", sheet=bool(run.sheet_id()))
        elif a.cmd == "sample":
            if not q.prompt_path.exists():
                sys.exit("no prompt yet: run set-spec first")
            p = q.sample_batch(a.round or 1, a.n)
            print("sample batch:", p)
            print("result file the subagent must write:", str(p).replace(".json", ".result.json"))
        elif a.cmd == "sample-report":
            table(q.sample_report(a.round or 1))
        elif a.cmd == "tune-log":
            streak = q.log_round(a.round, a.corrections, a.note)
            need = config.get("qualify.clean_rounds_needed")
            print("clean streak: %d of %d needed%s" % (streak, need, " -> ready to lock" if streak >= need else ""))
        elif a.cmd == "lock":
            streak = q.clean_streak()
            need = config.get("qualify.clean_rounds_needed")
            if streak < need and not a.force:
                sys.exit("clean streak is %d, need %d. Run more tuning rounds or pass --force (user decision)." % (streak, need))
            q.lock(len(q.tuning()["rounds"]), a.note)
            run.log("qualify", "prompt_locked", "rounds=%d streak=%d%s" % (len(q.tuning()["rounds"]), streak,
                                                                          " (forced)" if streak < need else ""))
            print("prompt locked")
        elif a.cmd in ("batches", "retry"):
            if not q.is_locked() and not a.force:
                sys.exit("prompt is not locked. Finish tuning and run lock (or pass --force).")
            with run.lock():
                # result files written since the last ingest must be ingested first, or their rows look
                # unscored and get batched (and scored) a second time
                tot = ingest(q, [], False, quiet=True)
                if any(tot.values()):
                    print("ingested waiting result files first:", tot)
                if a.cmd == "retry":
                    st = read_json(q.dir / "retry.json", {"passes": 0})
                    if st["passes"] >= 1 and not a.force:
                        sys.exit("the one automatic retry pass was already used. Inspect status, or pass --force.")
                    st["passes"] += 1
                    write_json(q.dir / "retry.json", st)
                res = q.make_batches(a.size, a.reissue)
                print(json.dumps({"website_fetch": res["fetched"], "rows_needing_a_score": res["pending"],
                                  "skipped_in_flight": res["skipped_in_flight"], "batches_written": len(res["batches"]),
                                  "dropped_by_hard_signals": res.get("signal_drops", 0)}))
                for b in res["batches"]:
                    print(b)
                run.log("qualify", "batches" if a.cmd == "batches" else "retry",
                        "%d batches for %d rows" % (len(res["batches"]), res["pending"]),
                        {"batches": len(res["batches"]), "rows": res["pending"]})
        elif a.cmd == "ingest":
            tot = ingest(q, a.files, a.force)
            run.log("qualify", "ingest", json.dumps(tot), tot)
        elif a.cmd == "status":
            print(json.dumps(q.status(), indent=2))
        elif a.cmd == "finalize":
            res = q.finalize(push=not a.no_sheet)
            print(json.dumps(res))
            run.log("qualify", "finalize", "scored %d of %d" % (res["scored"], res["rows"]), {"scored": res["scored"]})
            print(run.write_summary())
        if a.cmd in ("set-spec", "lock", "ingest", "batches", "retry"):
            run.write_summary()
    except (RunError, RuntimeError, ValueError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
