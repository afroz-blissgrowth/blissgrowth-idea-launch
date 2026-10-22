"""Run folder, state.json, stage derivation and summary.md (the run-lane pattern).

Pattern ported from GrowthEngine coldoutboundskills list-builder/scripts/run-lane.ts and
RUNBOOK.md (MIT, copyright 2026 GrowthEngineX): a run folder per idea, state.json written
atomically, stage completion decided from OUTPUT FILES (state.json is a cache plus a few
facts), re-running the same command resumes, summary.md line 1 is READY or NOT READY.

Folder: runs/<YYYY-MM-DD>-<idea-slug>/
  brief.json                  the agreed brief (written by /iv-brief)
  sheet.json                  {sheet_id, url, bridge}   (artifact: lets state.json be rebuilt)
  state.json                  cache: stages, usage, brief hash
  accounts.csv                stage 2 output, written only when the pull is COMPLETE
  accounts.stream.jsonl       rows as pages arrive (resume source)
  accounts.ledger.json        per shard progress
  apollo-usage.jsonl          every Apollo call and credits
  qualify/                    prompt, evidence cache, batches, results, qualified.csv
  runlog.jsonl                local run log (mirrored to the sheet's 9 Run Log tab)
  summary.md                  line 1: READY or NOT READY
"""
from __future__ import annotations

import contextlib
import getpass
import json
import os
import re
from pathlib import Path

import brief as briefmod
import config
import schema
import stages
from util import append_jsonl, atomic_write, now_iso, read_csv, read_json, read_jsonl, today, write_json

class RunError(RuntimeError):
    pass


class Run:
    def __init__(self, path):
        self.dir = Path(path)
        if not self.dir.is_dir():
            raise RunError("run folder not found: %s" % self.dir)
        d = self.dir
        self.brief_path = d / "brief.json"
        self.state_path = d / "state.json"
        self.sheet_path = d / "sheet.json"
        self.accounts_csv = d / "accounts.csv"
        self.accounts_stream = d / "accounts.stream.jsonl"
        self.ledger_path = d / "accounts.ledger.json"
        self.usage_log = d / "apollo-usage.jsonl"
        self.qdir = d / "qualify"
        self.runlog = d / "runlog.jsonl"
        self.summary_path = d / "summary.md"
        self.lock_path = d / ".lock"

    # ---- creation / resolution ---------------------------------------------------------------
    @classmethod
    def create(cls, slug, date=None):
        slug = briefmod.slugify(slug)
        name = "%s-%s" % (date or today(), slug)
        path = config.lists_dir() / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "qualify").mkdir(exist_ok=True)
        return cls(path)

    @classmethod
    def resolve(cls, arg):
        """arg may be a path, a folder name, or an idea slug (newest folder ending in it)."""
        p = Path(arg)
        if p.is_dir():
            return cls(p)
        root = config.lists_dir()
        if (root / arg).is_dir():
            return cls(root / arg)
        slug = briefmod.slugify(arg)
        pat = re.compile(r"\d{4}-\d{2}-\d{2}-" + re.escape(slug) + "$")  # exact slug, so "test" never grabs "...-x-test"
        matches = sorted(x for x in root.glob("*-" + slug) if x.is_dir() and pat.fullmatch(x.name))
        if matches:
            return cls(matches[-1])
        raise RunError("no run folder matches '%s' under %s" % (arg, root))

    # ---- files -------------------------------------------------------------------------------
    def brief(self):
        return briefmod.load(self.brief_path)

    def sheet(self):
        return read_json(self.sheet_path, {}) or {}

    def sheet_id(self):
        return self.sheet().get("sheet_id")

    # ---- state -------------------------------------------------------------------------------
    def load_state(self):
        try:
            st = read_json(self.state_path)
        except json.JSONDecodeError:
            bad = self.state_path.with_name("state.json.bad")
            os.replace(self.state_path, bad)  # corrupt: set aside, rebuild from artifacts
            st = None
        return st or {"run": self.dir.name, "created_at": now_iso(), "usage": {"apollo_credits": 0, "apollo_calls": 0},
                      "brief_sha": None, "stages": {}}

    def save_state(self, st):
        st["updated_at"] = now_iso()
        write_json(self.state_path, st)

    def update_state(self, **kw):
        st = self.load_state()
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(st.get(k), dict):
                st[k].update(v)
            else:
                st[k] = v
        self.save_state(st)
        return st

    def apollo_usage(self):
        calls = credits = 0
        for r in read_jsonl(self.usage_log):
            if r.get("status") == 200:
                calls += 1
                credits += r.get("credits", 0)
        return {"apollo_calls": calls, "apollo_credits": credits}

    # ---- locking -----------------------------------------------------------------------------
    @contextlib.contextmanager
    def lock(self, steal=False):
        if self.lock_path.exists() and not steal:
            try:
                pid = int(self.lock_path.read_text().strip() or 0)
                if pid <= 0:
                    raise ValueError("empty lock")
                os.kill(pid, 0)
                raise RunError("run is already being worked on (pid %d). Re-run when it finishes, or delete %s "
                               "if you know it is dead." % (pid, self.lock_path))
            except (ValueError, ProcessLookupError):
                pass  # stale lock
            except PermissionError:
                raise RunError("run is locked by another user's process: %s" % self.lock_path)
        self.lock_path.write_text(str(os.getpid()))
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                self.lock_path.unlink()

    # ---- run log -----------------------------------------------------------------------------
    def log(self, stage, event, detail="", counts=None, sheet=True):
        usage = self.apollo_usage()
        rec = {"timestamp": now_iso(), "stage": stage, "event": event, "detail": detail,
               "counts": json.dumps(counts or {}, sort_keys=True), "apollo_credits": usage["apollo_credits"],
               "run_by": getpass.getuser()}
        append_jsonl(self.runlog, rec)
        if sheet and self.sheet_id():
            try:
                import sheet as sheetmod
                sheetmod.SheetClient().append(self.sheet_id(), schema.TAB_RUNLOG,
                                              [[rec[c] for c in schema.TABS[schema.TAB_RUNLOG]]])
            except Exception as e:  # the local log is the source of truth; the sheet mirror is best effort
                append_jsonl(self.runlog, {"timestamp": now_iso(), "stage": "log", "event": "sheet_mirror_failed",
                                           "detail": str(e)[:200]})
        return rec

    # ---- stage derivation (from files) -------------------------------------------------------
    def stage_status(self):
        """Return {stage: {status, detail, ...}} from the registry in lib/stages.py (derived from files).
        status is pending|partial|done|failed|skipped."""
        return stages.derive(self)

    def next_command(self, stages_=None):
        return stages.next_command(self, stages_ or self.stage_status())

    # ---- summary.md --------------------------------------------------------------------------
    def counts(self):
        rows = read_csv(self.accounts_csv)
        res = {}
        for r in read_jsonl(self.qdir / "results.jsonl"):
            res[r.get("org_id")] = r
        flags = {}
        for r in rows:
            f = res.get(r["org_id"], {}).get("flag", "unscored")
            flags[f] = flags.get(f, 0) + 1
        return {"accounts": len(rows), "flags": flags}

    def _ready_counts(self):
        try:
            import people
            c = people.counts(people.load_table(self))["channels"]
            return "ready to launch: LinkedIn %d, Email %d, Calls %d" % (c["linkedin"], c["email"], c["call"])
        except Exception:
            return "no people counts"

    def _people_section(self):
        """Phase 2 counts and the list-quality grade for summary.md (empty before people exist)."""
        try:
            import people
            rows = people.load_table(self)
            if not rows:
                return []
            c = people.counts(rows)
            led = people.ledger(self)
            lines = ["", "## People", "", "- Companies searched: %d (without people: %d)" % (
                len(led), sum(1 for r in led.values() if r.get("status") == "none")),
                "- People found: %d" % c["people"]]
            for k in sorted(c["by_cap"]):
                lines.append("- cap_status %s: %d" % (k, c["by_cap"][k]))
            for k in sorted(c["by_tier"]):
                lines.append("- tier %s: %d" % (k, c["by_tier"][k]))
            ev = {}
            for r in rows:
                if r["email_verdict"]:
                    ev[r["email_verdict"]] = ev.get(r["email_verdict"], 0) + 1
            if ev:
                lines.append("- email verdicts: " + ", ".join("%s %d" % kv for kv in sorted(ev.items())))
            act = {}
            for r in rows:
                if r["linkedin_active"]:
                    act[r["linkedin_active"]] = act.get(r["linkedin_active"], 0) + 1
            if act:
                lines.append("- LinkedIn active: " + ", ".join("%s %d" % kv for kv in sorted(act.items())))
            lines.append("- Ready channels: LinkedIn %d, Email %d, Calls %d" % (
                c["channels"]["linkedin"], c["channels"]["email"], c["channels"]["call"]))
            import exclusions
            ec = exclusions.category_counts(rows)
            if ec["total"]:
                lines.append("- Exclusions, employment and pilot rejects (channel none, rows kept): %d (%s)" % (
                    ec["total"], ", ".join("%s %d" % kv for kv in sorted(ec.items()) if kv[0] != "total")))
            else:
                lines.append("- Exclusions, employment and pilot rejects: 0")
            q = read_json(people.Files(self).quality_json, None)
            if q:
                lines += ["", "## List quality", "", "- Grade %s (%s/100) on %d rows" % (q["grade"], q["score"], q["rows"])]
                lines += ["- %s" % i for i in q.get("issues", [])[:5]]
            return lines
        except Exception as e:
            return ["", "## People", "", "- could not read people artifacts: %s" % e]

    def _signals_pilot_section(self):
        """Company signals and the two pilot gates for summary.md (empty when none of them is in use)."""
        lines = []
        try:
            import pilot
            import signals as signalsmod
            brief = self.brief()
            if signalsmod.needs_apollo(brief) and self.accounts_csv.exists():
                sg = signalsmod.Signals(self)
                c = sg.summary(sg.accounts())
                lines += ["", "## Signals", "", "- Signals in the brief: %s" % ", ".join(
                    "%s (%s)" % (x["name"], x["strength"]) for x in signalsmod.canonical(brief.get("signals"))),
                    "- Accounts: %d enriched, %d not found in Apollo, %d without domain, %d to do" % (
                        c["enriched"], c["not_found"], c["no_domain"], c["pending"] + c["error"])]
                drops = sum(1 for r in read_jsonl(self.qdir / "results.jsonl") if r.get("batch") == "auto-signal")
                if drops:
                    lines.append("- Dropped automatically by a hard signal (rows kept, flag drop): %d" % drops)
            gl = []
            for kind in pilot.KINDS:
                st = pilot.accounts_state(self) if kind == pilot.ACCOUNTS else pilot.people_state(self)
                if st["state"] not in ("legacy",):
                    gl.append("- %s: %s" % (kind, st["detail"]))
            if gl:
                lines += ["", "## Pilot gates", ""] + gl
        except Exception as e:
            lines += ["", "## Signals and pilot", "", "- could not read: %s" % e]
        return lines

    def write_summary(self):
        s = self.stage_status()
        c = self.counts()
        brief = {}
        with contextlib.suppress(Exception):
            brief = self.brief()
        test = bool((brief.get("idea") or {}).get("test"))
        usage = self.apollo_usage()
        pool = sum(c["flags"].get(f, 0) for f in schema.POOL_FLAGS)
        maxerr = config.get("run.max_error_rate_for_ready", 0.05)
        reasons = []
        for name in stages.required_names():
            if s[name]["status"] not in stages.COMPLETE:
                reasons.append("%s is %s (%s)" % (name, s[name]["status"], s[name]["detail"]))
        if not reasons and c["accounts"] and c["flags"].get(schema.FLAG_ERROR, 0) / float(c["accounts"]) > maxerr:
            reasons.append("too many scoring errors")
        if not reasons and pool == 0:
            reasons.append("no qualified companies")
        if test:
            reasons.append("TEST run, not for launch")
        nxt = self.next_command(s)
        first = ("READY: %d qualified companies, %s. Next: %s" % (pool, self._ready_counts(), nxt)) if not reasons \
            else "NOT READY: %s. Next: %s" % ("; ".join(reasons), nxt)
        lines = [first, "", "# %s" % self.dir.name, ""]
        lines.append("| Stage | Status | Detail |")
        lines.append("|---|---|---|")
        for name in stages.names():
            lines.append("| %s | %s | %s |" % (name, s[name]["status"], s[name]["detail"]))
        lines += ["", "## Counts", "", "- Accounts: %d" % c["accounts"]]
        for k in sorted(c["flags"]):
            lines.append("- %s: %d" % (k, c["flags"][k]))
        lines.append("- Qualified pool (keep + review): %d" % pool)
        try:
            from volume import sizing
            sz = sizing(brief) if brief else None
            if sz:
                lines += ["", "## Volume check", "",
                          "- Accounts needed for %d to %d verified emails (at the assumed rates): %d to %d"
                          % (sz["targets"]["verified_emails_min"], sz["targets"]["verified_emails_max"],
                             sz["accounts_for_email_min"], sz["accounts_for_email_max"]),
                          "- Accounts needed for %d LinkedIn-active people: %d"
                          % (sz["targets"]["linkedin_active_min"], sz["accounts_for_linkedin_min"]),
                          "- Qualified pool now: %d. Raw accounts pulled: %d" % (pool, c["accounts"])]
        except Exception:
            pass
        lines += self._signals_pilot_section()
        lines += self._people_section()
        lines += ["", "## Apollo usage", "", "- Calls: %d, credits: %s" % (usage["apollo_calls"], round(usage["apollo_credits"], 1))]
        if self.sheet().get("url"):
            lines += ["", "Sheet: %s" % self.sheet()["url"]]
        atomic_write(self.summary_path, "\n".join(lines) + "\n")
        st = self.load_state()
        st["stages"] = {k: v["status"] for k, v in s.items()}
        st["usage"] = usage
        st["brief_sha"] = st.get("brief_sha")
        self.save_state(st)
        return first
