"""Stage registry: every stage of the run is ONE entry (name, label, how to tell it is done, next command).

Completion is derived from output FILES (state.json is only a cache), the same rule as Phase 1. To add a stage,
write a check function `check(run, done) -> {"status", "detail", ...}` and call register(). `done` is the dict of
statuses of the stages before it (a stage cannot be done before its predecessors). Statuses:
  pending | partial | done | failed | skipped
`skipped` counts as complete for READY (the user chose to skip: marker file tier/skipped.json etc.).
"""
from __future__ import annotations


import brief as briefmod
import config
import schema
from util import read_csv, read_json, read_jsonl

REGISTRY = []  # ordered list of dicts


def register(name, label, command, check, optional=False, post_ready=False):
    """command: format string with {run}; shown as the next step when this stage is not complete."""
    REGISTRY.append({"name": name, "label": label, "command": command, "check": check, "optional": optional,
                     "post_ready": post_ready})


def names():
    return [s["name"] for s in REGISTRY]


def required_names():
    """Stages that must be complete for READY (ready to launch). `post_ready` stages (launch) are the action AFTER READY."""
    return [s["name"] for s in REGISTRY if not s.get("post_ready")]


COMPLETE = ("done", "skipped")


def derive(run):
    out = {}
    for s in REGISTRY:
        try:
            out[s["name"]] = s["check"](run, dict(out))
        except Exception as e:  # a broken artifact must show up as a failed stage, not crash the summary
            out[s["name"]] = {"status": "failed", "detail": "could not read artifacts: %s" % e}
    return out


def next_command(run, statuses):
    for s in REGISTRY:
        if statuses[s["name"]]["status"] not in COMPLETE:
            return s["command"].format(run=run.dir.name)
    return "nothing left: every stage is complete"


def _blocked(done, *needs):
    """A stage cannot start while a predecessor has not started or failed. A PARTIAL predecessor (for example a limit
    test pull) does not hide progress here; READY still needs every stage complete."""
    for n in needs:
        if done.get(n, {}).get("status") in ("pending", "failed"):
            return {"status": "pending", "detail": "waiting for %s" % n}
    return None


def _newer(a, b):
    """True when file a exists and is at least as new as file b (or b does not exist)."""
    return a.exists() and (not b.exists() or a.stat().st_mtime >= b.stat().st_mtime)


# ---- Phase 1 stages (moved here unchanged) -------------------------------------------------------
def check_brief(run, done):
    b = {"status": "pending", "detail": "no brief.json"}
    if run.brief_path.exists():
        try:
            errs = briefmod.validate(run.brief())
        except briefmod.BriefError as e:
            errs = [str(e)]
        if errs:
            b = {"status": "failed", "detail": "; ".join(errs[:3])}
        elif not run.sheet_id():
            b = {"status": "partial", "detail": "brief ok, sheet not created"}
        else:
            b = {"status": "done", "detail": "brief ok, sheet %s" % run.sheet_id()}
    return b


def check_accounts(run, done):
    a = {"status": "pending", "detail": "not started"}
    ledger = read_json(run.ledger_path, None)
    import pilot
    pil = pilot.Gate(run, pilot.ACCOUNTS).selection()
    if ledger:
        n_stream = len(read_jsonl(run.accounts_stream))
        if ledger.get("complete") and not ledger.get("limit") and run.accounts_csv.exists():
            n = len(read_csv(run.accounts_csv))
            a = {"status": "done", "detail": "%d accounts" % n, "rows": n}
        elif ledger.get("limit") and run.accounts_csv.exists():
            if pil:
                open_ = pilot.gate_open_for_full_pull(run)
                d = ("pilot of %d accounts approved, the full pull has not run yet" if open_ else
                     "pilot of %d accounts only, the full pull waits for the pilot gate") % len(pil["ids"])
            else:
                d = "limit test run (%s accounts), not a full pull" % ledger["limit"]
            a = {"status": "partial", "detail": d, "rows": n_stream}
        else:
            a = {"status": "partial", "detail": "%d rows streamed, pull unfinished" % n_stream, "rows": n_stream}
    return a


def check_qualify(run, done):
    q = {"status": "pending", "detail": "not started"}
    if (run.qdir / "prompt.md").exists():
        rows = read_csv(run.accounts_csv)
        res = {}
        for r in read_jsonl(run.qdir / "results.jsonl"):
            res[r.get("org_id")] = r
        scored = sum(1 for r in rows if r["org_id"] in res and res[r["org_id"]].get("flag") != schema.FLAG_ERROR)
        errors = sum(1 for r in rows if res.get(r["org_id"], {}).get("flag") == schema.FLAG_ERROR)
        maxerr = config.get("run.max_error_rate_for_ready", 0.05)
        all_answered = rows and scored + errors == len(rows) and errors <= maxerr * len(rows)
        qcsv, rjsonl = run.qdir / "qualified.csv", run.qdir / "results.jsonl"
        finalized = qcsv.exists() and (not rjsonl.exists() or qcsv.stat().st_mtime >= rjsonl.stat().st_mtime)
        if all_answered and finalized and done["accounts"]["status"] == "done":
            q = {"status": "done", "detail": "%d scored, %d errors" % (scored, errors), "scored": scored,
                 "total": len(rows), "errors": errors}
        elif all_answered and not finalized:
            q = {"status": "partial", "detail": "all %d scored, run qualify_run.py finalize" % len(rows),
                 "scored": scored, "total": len(rows), "errors": errors}
        elif res:
            q = {"status": "partial", "detail": "%d of %d scored, %d errors" % (scored, len(rows), errors),
                 "scored": scored, "total": len(rows), "errors": errors}
        else:
            q = {"status": "partial", "detail": "prompt locked, nothing scored yet"}
    return q


# ---- Phase 2 stages -----------------------------------------------------------------------------
def _people_rows(run):
    import people
    return people.load_table(run)


def check_people(run, done):
    import people
    blk = _blocked(done, "qualify")
    if blk:
        return blk
    f = people.Files(run)
    led = people.ledger(run)
    if not led or not (run.qdir / "qualified.csv").exists():
        return {"status": "pending", "detail": "not started"}
    pool = people.pool_accounts(run)
    answered = [o for o in pool if led.get(o["org_id"], {}).get("status") in ("found", "none")]
    errors = [o for o in pool if led.get(o["org_id"], {}).get("status") == "error"]
    with_people = sum(1 for o in pool if led.get(o["org_id"], {}).get("status") == "found")
    n_people = len(_people_rows(run))
    maxerr = config.get("run.people_stage_max_error_rate", 0.05)
    all_answered = pool and len(answered) + len(errors) == len(pool) and len(errors) <= maxerr * len(pool)
    detail = "%d of %d companies searched, %d with people, %d without, %d people, %d errors" % (
        len(answered), len(pool), with_people, len(answered) - with_people, n_people, len(errors))
    if all_answered and f.table.exists() and _newer(f.table, f.ledger):
        return {"status": "done", "detail": detail}
    if all_answered:
        return {"status": "partial", "detail": detail + "; run people_search.py finalize"}
    return {"status": "partial", "detail": detail}


def check_tier(run, done):
    import people
    blk = _blocked(done, "people")
    if blk:
        return blk
    f = people.Files(run)
    if f.tier_skipped.exists():
        return {"status": "skipped", "detail": "tiering skipped by the user (title priority picks people, T2 channels)"}
    rows = _people_rows(run)
    if not rows:
        return {"status": "done", "detail": "no people to tier"}
    pool = [r for r in rows if r["cap_status"] != schema.CAP_OVER or r["tier"]]
    untiered = [r for r in rows if r["cap_status"] == schema.CAP_CANDIDATE]
    tiered = [r for r in rows if r["tier"]]
    t = {}
    for r in tiered:
        t[r["tier"]] = t.get(r["tier"], 0) + 1
    detail = "%d tiered (%s), %d waiting" % (len(tiered), ", ".join("%s %d" % kv for kv in sorted(t.items())) or "none",
                                            len(untiered))
    if not untiered and tiered:
        return {"status": "done", "detail": detail + ", caps applied"}
    return {"status": "partial" if tiered else "pending", "detail": detail}


def _selected(rows):
    """Selected people that still need work. A person rejected in the pilot review (exclusion_reason, never enriched)
    is not waited for."""
    return [r for r in rows if r["cap_status"] == schema.CAP_SELECTED and not (r.get("exclusion_reason") and not r.get("enrich_status"))]


def check_enrich_verify(run, done):
    import people
    blk = _blocked(done, "tier")
    if blk:
        return blk
    rows = _selected(_people_rows(run))
    if not rows:
        return {"status": "pending", "detail": "nobody selected yet"}
    enriched = [r for r in rows if r["enrich_status"] in ("matched", "no_match")]
    with_email = [r for r in enriched if r["email"]]
    verified = [r for r in with_email if r["mv_result"]]
    detail = "%d of %d selected enriched, %d with email, %d verified (valid %d, catch_all %d)" % (
        len(enriched), len(rows), len(with_email), len(verified),
        sum(1 for r in rows if r["email_verdict"] == "valid"), sum(1 for r in rows if r["email_verdict"] == "catch_all"))
    if len(enriched) == len(rows) and len(verified) == len(with_email):
        if not config.env("MILLIONVERIFIER_API_KEY") and not verified and with_email:
            return {"status": "partial", "detail": detail + "; MILLIONVERIFIER_API_KEY missing"}
        return {"status": "done", "detail": detail}
    return {"status": "partial" if enriched else "pending", "detail": detail}


def check_activity(run, done):
    import people
    blk = _blocked(done, "enrich_verify")
    if blk:
        return blk
    f = people.Files(run)
    if f.activity_skipped.exists():
        return {"status": "skipped", "detail": "activity check skipped by the user (LinkedIn needs only a profile URL)"}
    sel = _selected(_people_rows(run))
    rows = [r for r in sel if r["linkedin_url"] and (not r.get("exclusion_reason") or r["linkedin_checked_at"])]
    if not rows:
        if sel and all(r["enrich_status"] for r in sel):
            return {"status": "done", "detail": "no selected person has a LinkedIn URL"}
        return {"status": "pending", "detail": "no selected people with a LinkedIn URL yet"}
    checked = [r for r in rows if r["linkedin_checked_at"]]
    yes = sum(1 for r in rows if r["linkedin_active"] == "yes")
    no = sum(1 for r in rows if r["linkedin_active"] == "no")
    detail = "%d of %d profiles checked (active %d, inactive %d, unknown %d)" % (
        len(checked), len(rows), yes, no, len(checked) - yes - no)
    return {"status": "done" if len(checked) == len(rows) else ("partial" if checked else "pending"), "detail": detail}


def check_phones(run, done):
    import people
    blk = _blocked(done, "enrich_verify")
    if blk:
        return blk
    f = people.Files(run)
    if f.phones_skipped.exists():
        return {"status": "skipped", "detail": "phones skipped by the user (no call list)"}
    sel = _selected(_people_rows(run))
    rows = [r for r in sel if r["tier"] == schema.TIER_T1 and not r.get("exclusion_reason")]
    if not rows:
        if sel:
            return {"status": "done", "detail": "no selected T1 people, no phones needed"}
        return {"status": "pending", "detail": "no selected T1 people yet"}
    final = ("received", "none", "not_available")
    got = [r for r in rows if r["phone_status"] in final]
    waiting = [r for r in rows if r["phone_status"] == "requested"]
    with_phone = sum(1 for r in rows if r["phone"])
    detail = "%d of %d T1 people resolved, %d with a phone, %d requested and waiting" % (
        len(got), len(rows), with_phone, len(waiting))
    return {"status": "done" if len(got) == len(rows) else ("partial" if (got or waiting) else "pending"),
            "detail": detail}


def check_ready(run, done):
    import people
    blk = _blocked(done, "activity", "phones")
    if blk:
        return blk
    f = people.Files(run)
    meta = read_json(f.ready_meta, None)
    if not meta:
        return {"status": "pending", "detail": "Ready tabs not built (run ready_build.py)"}
    if not _newer(f.ready_meta, f.table):
        return {"status": "partial", "detail": "people changed after the Ready tabs were built; re-run ready_build.py"}
    return {"status": "done", "detail": "LinkedIn %d, Email %d, Calls %d%s" % (
        meta.get("linkedin", 0), meta.get("email", 0), meta.get("calls", 0),
        ", list grade %s" % meta["grade"] if meta.get("grade") else "")}


# ---- pilot gates and signals (added after the first review round, see PLAN.md "Pilot gates, signals, exclusions") ----
def check_pilot_accounts(run, done):
    import pilot
    blk = _blocked(done, "brief")
    if blk:
        return blk
    st = pilot.stage_status(run, pilot.ACCOUNTS)
    return {"status": st["status"], "detail": st["detail"]}


def check_signals(run, done):
    import signals as signalsmod
    brief = run.brief()
    if not signalsmod.needs_apollo(brief):
        return {"status": "done", "detail": "no numeric signals in the brief, nothing to enrich"}
    if not run.accounts_csv.exists():
        return {"status": "pending", "detail": "waiting for accounts"}
    sg = signalsmod.Signals(run)
    rows = sg.accounts()
    c = sg.summary(rows)
    todo = c["pending"] + c["error"]
    detail = "%d accounts: %d enriched, %d not found in Apollo, %d without domain, %d to do" % (
        c["accounts"], c["enriched"], c["not_found"], c["no_domain"], todo)
    if not todo:
        return {"status": "done", "detail": detail}
    return {"status": "partial" if c["enriched"] + c["not_found"] else "pending", "detail": detail}


def check_pilot_people(run, done):
    import pilot
    blk = _blocked(done, "tier")
    if blk:
        return blk
    st = pilot.stage_status(run, pilot.PEOPLE)
    return {"status": st["status"], "detail": st["detail"]}


register("brief", "brief", "/iv-brief (finish and save the brief)", check_brief)
register("pilot_accounts", "pilot accounts", "/iv-accounts {run} (pilot gate)", check_pilot_accounts)
register("accounts", "accounts", "/iv-accounts {run}", check_accounts)
register("signals", "signals", "/iv-signals {run}", check_signals)
register("qualify", "qualify", "/iv-qualify {run}", check_qualify)
register("people", "people", "/iv-people {run}", check_people)
register("tier", "tier", "/iv-tier {run}", check_tier)
register("pilot_people", "pilot people", "/iv-tier {run} (people pilot gate)", check_pilot_people)
register("enrich_verify", "enrich + verify", "/iv-enrich-verify {run}", check_enrich_verify)
register("activity", "activity", "/iv-activity {run}", check_activity, optional=True)
register("phones", "phones", "/iv-phones {run}", check_phones, optional=True)
register("ready", "ready tabs", "/iv-ready {run}", check_ready)


# ---- Phase 3 stages -----------------------------------------------------------------------------
def check_copy(run, done):
    import copydraft
    blk = _blocked(done, "ready")
    if blk:
        return blk
    cd = copydraft.CopyDraft(run)
    items = cd.items()
    if not items:
        return {"status": "pending", "detail": "no copy drafted yet"}
    comp = cd.completeness()
    n = len(items)
    if not comp["ok"]:
        probs = comp["missing"] + comp["thin"] + comp["toomany"] + comp["blocked"]
        return {"status": "partial", "detail": "%d items, %d open problems (%s)" % (n, len(probs), probs[0])}
    if not cd.approval_valid():
        stale = cd.approval() is not None
        return {"status": "partial", "detail": "%d items complete and clean, %s" % (
            n, "approval is stale (copy changed after it), approve again" if stale else "waiting for the user's approval")}
    a = cd.approval()
    test = bool((run.brief().get("idea") or {}).get("test"))
    if a.get("simulated") and not test:
        return {"status": "partial", "detail": "approval is SIMULATED, a real user must approve"}
    fin = read_json(cd.final_path, None)
    if not fin or fin.get("items_hash") != cd.items_hash() or not fin.get("approved"):
        return {"status": "partial", "detail": "approved, run copy_run.py write (copy.json and the 8 Copy tab)"}
    if run.sheet_id() and not cd.pushed_path.exists():
        return {"status": "partial", "detail": "approved, copy.json written, 8 Copy tab not pushed yet"}
    return {"status": "done", "detail": "%d items approved%s" % (n, " (SIMULATED approval, test run)" if a.get("simulated") else "")}


def check_idea_page(run, done):
    import ideapage
    blk = _blocked(done, "ready")
    if blk:
        return blk
    ip = ideapage.IdeaPage(run)
    if ip.skip_path.exists():
        return {"status": "skipped", "detail": "idea page skipped by the user"}
    r = ip.record()
    if r and r.get("test") and not (run.brief().get("idea") or {}).get("test"):
        return {"status": "partial", "detail": "only a TEST page is recorded (%s); a real run needs the real page" % r["page_url"]}
    if r:
        tag = " (TEST page)" if r.get("test") else (" (existing page adopted)" if r.get("existing") else "")
        return {"status": "done", "detail": "%s%s" % (r["page_url"], tag)}
    if ip.confirmed():
        return {"status": "partial", "detail": "text confirmed, create the page with the Notion MCP then run idea_page.py record"}
    if ip.fields():
        return {"status": "partial", "detail": "fields drafted, waiting for the user to confirm the text"}
    return {"status": "pending", "detail": "no idea page yet"}


def check_launch(run, done):
    import launch
    blk = _blocked(done, "copy", "idea_page")
    if blk:
        return blk
    ln = launch.Launch(run)
    st = read_json(ln.state_path, None)
    cs = read_json(ln.callsheet_path, None) or {}
    calls = len(ln.callsheet_rows())
    if st and st.get("executed"):
        n_c = sum(len(g.get("campaigns", {})) for g in st["groups"].values())
        d = "%d lists, %d DRAFT campaigns created, nothing started" % (len(st["groups"]), n_c)
        if calls and not cs.get("sheet_id"):
            return {"status": "partial", "detail": d + "; call sheet for Mansi not created"}
        return {"status": "done", "detail": d + ("; call sheet shared" if cs.get("sheet_id") else "")}
    if read_json(ln.approval_path, None):
        return {"status": "partial", "detail": "plan approved, not executed"}
    if read_json(ln.plan_path, None):
        return {"status": "partial", "detail": "plan written, waiting for the user's approval"}
    return {"status": "pending", "detail": "not planned yet"}


register("copy", "copy", "/iv-copy {run}", check_copy)
register("idea_page", "idea page", "/iv-idea-page {run}", check_idea_page)
register("launch", "launch", "/iv-launch {run}", check_launch, post_ready=True)
