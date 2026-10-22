"""Stage 7: LinkedIn activity check through the existing n8n workflow "LinkedIn Activity Checker"
(id NrweLKOV7gMu54bD, builder engine/vendor/activity-checker/build_workflow_v21.py).

THE CONTRACT (the checker itself is unchanged apart from three optional body fields, see
workflows/patch_activity_checker.py, marker IL_CONTRACT_V1):
  input    LinkedIn profile URLs (https://www.linkedin.com/in/<slug>), optionally name, title and company.
  how      the rows are upserted into two tabs (leads and runs) of a Google Sheet through the checker's webhook,
           then a run is started. The checker is normally INACTIVE: this module activates it for the run only and
           deactivates it afterwards (always, in a finally block, also after errors).
  output   per profile: activity_status Active | Inactive | Shell | (blank = still unknown), active_via,
           activity_reason, activity_checked_at, scrape_error, scrape_attempts.
  cache    activity/cache.jsonl keyed by the normalised profile URL. A profile with a final answer is never
           sent again, in this run or a later one. Blank answers are retried (the checker allows 3 attempts).
  mapping  Active -> linkedin_active yes; Inactive and Shell -> no; blank after the final attempt -> unknown.
           Inactive people get the email channel only, people without a valid email get LinkedIn only
           (people.channels_for). activity.unknown_policy in config.json decides whether unknown counts as active.

The sheet and tabs: by default the checker's own spreadsheet (config activity.sheet_id) with two new tabs per run,
`il <run name>` and `il <run name> runs`, the same way earlier campaigns used a tab pair each.
Cost: Apify (profile, posts, comments and reactions scrapers), a few cents for a small run.
"""
from __future__ import annotations

import json
import re
import time

import config
import n8n
import net
import people as peoplemod
import schema
from util import append_jsonl, now_iso, read_json, read_jsonl, write_json

MARK = "IL_CONTRACT_V1"


class ActivityError(RuntimeError):
    pass


def canonical_url(u):
    """https://www.linkedin.com/in/<slug> (query and trailing slash dropped). '' if not a profile URL."""
    k = peoplemod.norm_url(u)
    m = re.match(r"linkedin\.com/in/([^/]+)", k)
    return "https://www.linkedin.com/in/%s" % m.group(1) if m else ""


def tab_names(run):
    base = ("il " + run.dir.name)[:80]
    return base, base + " runs"


def todo_rows(rows, cache):
    """Selected people with a profile URL and no final cached answer, one per distinct profile."""
    seen, out = set(), []
    for r in rows:
        if r["cap_status"] != schema.CAP_SELECTED or r.get("exclusion_reason"):
            continue  # excluded people (Apollo employment data, pilot rejects) are not worth an Apify check
        u = canonical_url(r["linkedin_url"])
        k = peoplemod.norm_url(u)
        if not u or k in seen or k in cache:
            continue
        seen.add(k)
        out.append({"linkedin_url": u, "first_name": r["first_name"], "last_name": r["last_name"],
                    "current_title": r["title"], "current_company": r["company"]})
    return out


def cache(run):
    out = {}
    for r in read_jsonl(peoplemod.Files(run).activity_cache):
        out[r.get("linkedin_key")] = r
    return out


def is_final(rec, max_attempts=3):
    """A checker row is final when it has an activity_status, or it used all its attempts."""
    if str(rec.get("activity_status") or "").strip():
        return True
    try:
        return int(rec.get("scrape_attempts") or 0) >= max_attempts
    except (TypeError, ValueError):
        return False


class Checker:
    """Thin client for the n8n checker: webhook for upsert and run, the sheet (through the bridge) for results."""

    def __init__(self, run, sheet_client=None, post=None, sleep=time.sleep, clock=time.time):
        import sheet as sheetmod
        self.run = run
        self.cfg = config.get("activity")
        self.sc = sheet_client or sheetmod.SheetClient()
        self.post = post or self._post
        self.sleep = sleep
        self.clock = clock
        self.leads_tab, self.runs_tab = tab_names(run)
        self.sheet_id = self.cfg["sheet_id"]
        self.wid = self.cfg["workflow_id"]

    def _post(self, body, timeout=60):
        url = n8n.webhook_url(self.cfg["webhook_path"])
        st, _, raw = net.fetch("POST", url, {"Content-Type": "application/json"}, json.dumps(body).encode(), timeout)
        return st, raw.decode("utf-8", "replace")[:300]

    def _webhook(self, body, tries=8):
        """POST to the production webhook. Right after activation n8n may answer 404 for a few seconds."""
        last = ""
        for i in range(tries):
            st, text = self.post(body)
            if st in (200, 201, 202):
                return text
            last = "%s %s" % (st, text)
            self.sleep(3 if st == 404 else 5)
        raise ActivityError("checker webhook did not accept the request: %s" % last)

    def assert_contract(self):
        wf = n8n.get_workflow(self.wid)
        js = next((n["parameters"].get("jsCode", "") for n in wf["nodes"] if n["name"] == "Config"), "")
        if MARK not in js:
            raise ActivityError("the live checker does not have the Idea Launch contract yet. Run "
                                "python3 -I engine/workflows/patch_activity_checker.py (backs up first).")
        return wf

    def common(self):
        return {"sheet_id": self.sheet_id, "leads_tab": self.leads_tab, "runs_tab": self.runs_tab}

    def upsert(self, rows):
        size = self.cfg["upsert_chunk"]
        for i in range(0, len(rows), size):
            self._webhook(dict(self.common(), action="upsert", rows=rows[i:i + size]))
            self.sleep(2)  # executions are asynchronous; keep them in order

    def read_leads(self):
        return self.sc.read_records(self.sheet_id, self.leads_tab)

    def read_runs(self):
        return self.sc.read_records(self.sheet_id, self.runs_tab)

    def wait_rows_present(self, urls, timeout_s=240):
        want = {peoplemod.norm_url(u) for u in urls}
        end = self.clock() + timeout_s
        while self.clock() < end:
            try:
                have = {peoplemod.norm_url(r.get("linkedin_url", "")) for r in self.read_leads()}
            except Exception:
                have = set()
            if want <= have:
                return True
            self.sleep(8)
        return False

    def start_run(self, max_leads):
        t0 = self.clock()
        self._webhook(dict(self.common(), action="run", max_leads=max_leads))
        return t0

    def wait_run_end(self, started_iso, timeout_s, poll_s):
        """Wait for a run_end row logged after started_iso. Returns the row or None on timeout."""
        end = self.clock() + timeout_s
        while self.clock() < end:
            try:
                for r in self.read_runs():
                    if r.get("stage") == "run_end" and str(r.get("logged_at", "")) >= started_iso:
                        return r
            except Exception:
                pass
            self.sleep(poll_s)
        return None


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


def collect(run, checker, urls):
    """Read the checker tab and cache every FINAL answer for the given profile URLs. Returns counts."""
    f = peoplemod.Files(run)
    want = {peoplemod.norm_url(u) for u in urls}
    known = cache(run)
    counts = {"final": 0, "pending": 0, "Active": 0, "Inactive": 0, "Shell": 0, "unknown": 0, "usd": 0.0}
    for rec in checker.read_leads():
        k = peoplemod.norm_url(rec.get("linkedin_url", ""))
        if k not in want or k in known:
            continue
        if not is_final(rec):
            counts["pending"] += 1
            continue
        st = str(rec.get("activity_status") or "").strip()
        append_jsonl(f.activity_cache, {"linkedin_key": k, "linkedin_url": rec.get("linkedin_url", ""),
                                        "activity_status": st, "active_via": rec.get("active_via", ""),
                                        "activity_reason": rec.get("activity_reason", "") or rec.get("scrape_error", ""),
                                        "scrape_attempts": rec.get("scrape_attempts", ""),
                                        # employment fields of the checker, read by lib/exclusions.py
                                        "headline": rec.get("headline", ""), "current_title": rec.get("current_title", ""),
                                        "current_company": rec.get("current_company", ""),
                                        "jobs_count": rec.get("jobs_count", ""),
                                        "current_jobs_count": rec.get("current_jobs_count", ""),
                                        "latest_job_start": rec.get("latest_job_start", ""),
                                        "checked_at": str(rec.get("activity_checked_at") or now_iso()),
                                        "tab": checker.leads_tab, "final": True})
        counts["final"] += 1
        counts[st if st in ("Active", "Inactive", "Shell") else "unknown"] += 1
    return counts


def backfill_employment(run, checker):
    """Free (no Apify, only a sheet read): refresh the cached profiles with the employment columns of the checker
    (headline, current_title, current_company, jobs_count, current_jobs_count, latest_job_start) for runs checked before
    those columns were cached. Appends a new cache record per profile that gained data (last record wins). Returns counts."""
    f = peoplemod.Files(run)
    known = cache(run)
    rep = {"profiles_in_tab": 0, "updated": 0, "unchanged": 0}
    for rec in checker.read_leads():
        k = peoplemod.norm_url(rec.get("linkedin_url", ""))
        if k not in known:
            continue
        rep["profiles_in_tab"] += 1
        cur = known[k]
        new = {c: rec.get(c, "") for c in ("headline", "current_title", "current_company", "jobs_count", "current_jobs_count",
                                           "latest_job_start")}
        if all(str(cur.get(c, "")) == str(v) for c, v in new.items()):
            rep["unchanged"] += 1
            continue
        append_jsonl(f.activity_cache, dict(cur, **new, backfilled_at=now_iso()))
        rep["updated"] += 1
    return rep


def run_activity(run, limit=None, progress=print, checker=None, resume=False):
    """Full flow. Activates the checker only for the run, deactivates it in finally. Returns a report."""
    f = peoplemod.Files(run)
    rows = peoplemod.rebuild(run)
    todo = todo_rows(rows, cache(run))
    if limit:
        todo = todo[:limit]
    rep = {"to_check": len(todo), "tab": None, "run_end": None, "counts": None, "deactivated": None, "note": ""}
    if not todo and not resume:
        rep["note"] = "nothing to check (every selected profile is cached or has no URL)"
        return rep
    ch = checker or Checker(run)
    rep["tab"] = ch.leads_tab
    ch.assert_contract()
    acfg = ch.cfg
    state = read_json(f.activity_state, {})
    state.update({"leads_tab": ch.leads_tab, "runs_tab": ch.runs_tab, "sheet_id": ch.sheet_id, "workflow_id": ch.wid})
    write_json(f.activity_state, state)
    state["backup"] = state.get("backup") or n8n.backup_workflow(ch.wid, "before-run-" + run.dir.name[:30])
    write_json(f.activity_state, state)
    # "was_active" means active for someone else's reasons. A checker we left active after a timeout is ours to switch off.
    was_active = bool(n8n.get_workflow(ch.wid).get("active")) and not state.get("activated_by_us")
    try:
        if not bool(n8n.get_workflow(ch.wid).get("active")):
            n8n.set_active(ch.wid, True)
            state["activated_by_us"] = True
            write_json(f.activity_state, state)
            progress("checker activated for this run (it is normally inactive)")
        urls = [r["linkedin_url"] for r in todo]
        started = None
        if not resume:
            ch.upsert(todo)
            if not ch.wait_rows_present(urls):
                raise ActivityError("rows did not appear in tab %r within 4 minutes" % ch.leads_tab)
            started = ch.start_run(len(todo))
            state.update({"run_started_at": iso(started), "n_sent": len(todo)})
            write_json(f.activity_state, state)
            progress("run started for %d profiles, polling every %ss" % (len(todo), acfg["poll_interval_s"]))
        else:
            started = time.time() - 3600 * 6
            state.setdefault("run_started_at", iso(started))
        end = ch.wait_run_end(state.get("run_started_at", iso(started)), acfg["timeout_min"] * 60, acfg["poll_interval_s"])
        rep["run_end"] = end
        if end is None:
            rep["note"] = ("timed out after %d minutes. The checker may still be running: re-run with --resume to collect, "
                           "it is deactivated only after collecting or with --deactivate" % acfg["timeout_min"])
            rep["counts"] = collect(run, ch, urls)
            return rep
        rep["counts"] = collect(run, ch, urls)
        try:
            rep["counts"]["usd"] = float(end.get("usage_usd") or 0)
        except (TypeError, ValueError):
            pass
        return rep
    finally:
        if rep.get("run_end") is not None or not rep.get("note", "").startswith("timed out"):
            if not was_active:
                try:
                    n8n.set_active(ch.wid, False)
                    state["activated_by_us"] = False
                    write_json(f.activity_state, state)
                    rep["deactivated"] = True
                    progress("checker deactivated again")
                except Exception as e:  # never hide this: an active checker is a loose end
                    rep["deactivated"] = False
                    progress("WARNING: could not deactivate the checker: %s" % e)
