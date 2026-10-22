"""Stage 13: /iv-run, the orchestrator. Walks lib/stages.REGISTRY in order and drives one idea from brief to DRAFT campaigns.

Each stage has a KIND:
  user    the user must decide (brief, launch approval). The driver stops and says what to ask.
  claude  Claude does the judgement work with the user's review (qualify and tier tuning, copy, idea page). The driver stops and names
          the skill to follow; after the skill finishes, run /iv-run again, it resumes at the next stage.
  auto    a script does it (accounts pull, people search, enrich + verify, activity, phones, ready tabs). The driver runs it.
Rules from the Decisions: cost is SHOWN (estimate) and logged, never a gate and never a limit. Resumable: every stage is derived from files,
so re-running continues at the first stage that is not done or skipped. The driver never sends anything on its own: with execute=False it
only projects what it would do. The launch stage creates DRAFT campaigns only after the user's approval of the plan; nothing is started.
"""
from __future__ import annotations

import subprocess
import sys

import config
import stages
from util import read_csv, read_json

BIN = config.IDEA_LAUNCH_DIR / "bin"

# stage -> (kind, skill, instruction when the driver must stop)
KINDS = {
    "brief": ("user", "/iv-brief", "Agree the brief with the user (ICP, titles, countries, tier rules). Claude never decides these alone."),
    "pilot_accounts": ("claude", "/iv-accounts", "Account pilot gate: see pilot.next_action (the driver pulls and enriches the pilot, then stops for qualify and for the user's review)."),
    "accounts": ("auto", "/iv-accounts", None),
    "signals": ("auto", "/iv-signals", None),
    "qualify": ("claude", "/iv-qualify", "Tune the company judge prompt on samples of 10 with the user (2 clean rounds), then score everyone with subagents."),
    "people": ("auto", "/iv-people", None),
    "tier": ("claude", "/iv-tier", "Tune the T1/T2 prompt on samples of 10 with the user (2 clean rounds), tier everyone, apply caps."),
    "pilot_people": ("claude", "/iv-tier", "People pilot gate: see pilot.next_action (the driver draws the pilot, then stops for the user's review before any enrichment credit)."),
    "enrich_verify": ("auto", "/iv-enrich-verify", None),
    "activity": ("auto", "/iv-activity", None),
    "phones": ("auto", "/iv-phones", None),
    "ready": ("auto", "/iv-ready", None),
    "copy": ("claude", "/iv-copy", "Draft V1 plus variants, show samples, tune with the user, get the explicit approval before writing the final copy."),
    "idea_page": ("claude", "/iv-idea-page", "Draft the idea page text from the memo and brief, get the user's confirmation, create it with the Notion MCP."),
    "launch": ("user", "/iv-launch", "Show the launch plan, get the user's explicit approval, then create the lists and DRAFT campaigns (never started) and the call sheet."),
}


def cmd(script, *args):
    return [sys.executable, "-I", str(BIN / script)] + [str(a) for a in args]


# gate stages whose kind (auto, claude, user) depends on their state: lib/pilot.next_action decides
GATES = {"pilot_accounts": "accounts", "pilot_people": "people"}


def gate_action(run, name):
    import pilot
    return pilot.next_action(run, GATES[name])


def auto_commands(name, run, status):
    """The script command(s) an auto stage runs, given its current status. Returns [] when nothing can be run."""
    r = run.dir.name
    if name in GATES:
        return [cmd(c[0], *c[1:]) for c in gate_action(run, name)["cmds"]]
    if name == "signals":
        return [cmd("signals_run.py", "run", r)]
    if name == "accounts":
        plan_exists = (run.dir / "accounts.plan.json").exists()
        out = [] if plan_exists else [cmd("accounts_pull.py", r, "--dry-run")]
        return out + [cmd("accounts_pull.py", r)]
    if name == "people":
        return [cmd("people_search.py", r), cmd("people_search.py", r, "--finalize")]
    if name == "enrich_verify":
        return [cmd("enrich_verify.py", "all", r)]
    if name == "activity":
        st = read_json(run.dir / "activity" / "state.json", {}) or {}
        if st.get("activated_by_us"):  # an earlier run timed out and left the checker on: collect, do not send a new run
            return [cmd("activity_run.py", "run", r, "--resume")]
        return [cmd("activity_run.py", "run", r)]
    if name == "phones":
        return [cmd("phones_run.py", "request", r)]
    if name == "ready":
        return [cmd("ready_build.py", r)]
    if name == "launch":
        import launch as lmod
        ln = lmod.Launch(run)
        if read_json(ln.approval_path, None):
            return [cmd("launch_run.py", "execute", r), cmd("launch_run.py", "callsheet", r, "--execute")]
        return [cmd("launch_run.py", "plan", r)]
    return []


def estimate(run, name):
    """Short human estimate of what a stage will cost (credits, dollars, time). Never raises."""
    try:
        cfgd = config.get
        brief = run.brief()
        if name == "accounts":
            from volume import sizing
            sz = sizing(brief)
            pages = -(-sz["accounts_for_email_max"] // cfgd("apollo.per_page", 100))
            return "about %d to %d accounts needed, up to %d org-search pages (~%d Apollo credits, 1 per page)" % (
                sz["accounts_for_email_min"], sz["accounts_for_email_max"], pages, pages * cfgd("apollo.credits_per_org_search_page", 1))
        if name == "signals":
            import signals as sm
            sg = sm.Signals(run)
            e = sg.estimate(sg.accounts())
            return "%d companies to enrich = up to %d Apollo credits (1 per matched company, %d answered from the cache)" % (
                e["domains_to_enrich"], e["credits_max"], e["from_shared_cache"])
        import people as pm
        rows = pm.load_table(run)
        sel = [r for r in rows if r["cap_status"] == "selected"]
        if name == "people":
            pool = len(pm.pool_accounts(run))
            led = len(pm.ledger(run))
            left = max(0, pool - led)
            return "0 credits, %d companies left to search (~%.0f min at the shared rate limit)" % (
                left, left * cfgd("run.estimates.people_search_seconds_per_company", 0.4) / 60.0)
        if name == "enrich_verify":
            todo = [r for r in sel if r["enrich_status"] not in ("matched", "no_match")]
            return "%d people to enrich = about %d Apollo credits, plus MillionVerifier on their emails (~$%.2f)" % (
                len(todo), len(todo) * cfgd("apollo.credits_per_bulk_match_person", 1),
                len(todo) * 0.6 * cfgd("run.estimates.millionverifier_usd_per_email", 0.0005))
        if name == "activity":
            todo = [r for r in sel if r["linkedin_url"] and not r["linkedin_checked_at"]]
            return "%d profiles to check, Apify about $%.2f" % (len(todo), len(todo) * cfgd("run.estimates.apify_usd_per_profile", 0.003))
        if name == "phones":
            todo = [r for r in sel if r["tier"] == "T1" and r["phone_status"] not in ("received", "none", "not_available", "requested")]
            note = ""
            if cfgd("phones.phones_in_enrich", False):
                note = " (phones.phones_in_enrich is true but NOT implemented yet, see REVIEW-PHASE2 issue A)"
            return "%d T1 people, up to %d Apollo credits (%d per mobile found; measured about 6)%s" % (
                len(todo), len(todo) * cfgd("phones.credits_per_mobile", 8), cfgd("phones.credits_per_mobile", 8), note)
        if name == "launch":
            return "no credits; creates HeyReach lists and DRAFT campaigns only after approval"
    except Exception as e:  # an estimate must never stop the run
        return "no estimate (%s)" % str(e)[:60]
    return ""


def plan(run):
    """One record per stage: status, kind, skill, estimate, what happens next."""
    st = run.stage_status()
    out = []
    for s in stages.REGISTRY:
        name = s["name"]
        kind, skill, instr = KINDS.get(name, ("claude", s["command"].format(run=run.dir.name).split()[0], "Follow the skill."))
        status = st[name]["status"]
        est_auto = kind == "auto"
        if name in GATES and status not in stages.COMPLETE:
            ga = gate_action(run, name)
            kind, instr, est_auto = ga["kind"], ga["instruction"], ga["kind"] == "auto"
        rec = {"stage": name, "status": status, "detail": st[name]["detail"], "kind": kind, "skill": skill,
               "complete": status in stages.COMPLETE, "post_ready": bool(s.get("post_ready")), "instruction": instr,
               "estimate": estimate(run, name) if est_auto and name not in GATES or name in ("launch",) else ""}
        out.append(rec)
    return out


def projection(run):
    """Walk the whole pipeline: DONE / AUTO (the driver would run it) / GATE (stops for the user or Claude). The first non-done stage
    is `next`. After it, the projection assumes the stage completes and shows where the run would stop next."""
    recs = plan(run)
    first = True
    for r in recs:
        if r["complete"]:
            r["action"] = "done" if r["status"] == "done" else "skipped"
        elif r["kind"] == "auto":
            r["action"] = "AUTO: driver runs it" + (" (next)" if first else "")
        else:
            r["action"] = "STOP for %s (%s)" % ("the user" if r["kind"] == "user" else "Claude with the user", r["skill"]) + (" (next)" if first else "")
        if not r["complete"]:
            first = False
    return recs


def render(recs):
    L = ["| Stage | Status | Kind | What happens | Estimate |", "|---|---|---|---|---|"]
    for r in recs:
        L.append("| %s%s | %s | %s | %s | %s |" % (r["stage"], " (after READY)" if r["post_ready"] else "", r["status"], r["kind"],
                                                  r["action"], r["estimate"] or ""))
    return "\n".join(L)


def default_runner(argv):
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def plan_written_not_approved(run):
    import launch as lmod
    ln = lmod.Launch(run)
    return bool(read_json(ln.plan_path, None)) and not read_json(ln.approval_path, None)


def drive(run, execute=False, runner=default_runner, log=print, max_steps=None):
    """Run auto stages until a stage needs the user or Claude, a script fails, or nothing changes. Returns
    {state: complete|stopped|failed|stalled|dry, stage, needs, instruction}."""
    max_steps = max_steps or config.get("run.drive_max_steps", 30)
    for _ in range(max_steps):
        recs = plan(run)
        cur = next((r for r in recs if not r["complete"]), None)
        if cur is None:
            return {"state": "complete", "stage": None, "needs": None, "instruction": "every stage is done"}
        name = cur["stage"]
        auto = cur["kind"] == "auto" or (name == "launch")
        if name == "launch":
            import launch as lmod
            ln = lmod.Launch(run)
            if not read_json(ln.approval_path, None):
                if read_json(ln.plan_path, None):
                    return {"state": "stopped", "stage": name, "needs": "user",
                            "instruction": "Show launch/plan.md and ask the user to approve this exact plan, then: launch_run.py approve"}
                auto = True  # make the plan, then stop for approval
        if not auto:
            return {"state": "stopped", "stage": name, "needs": cur["kind"], "skill": cur["skill"], "instruction": cur["instruction"]}
        cmds = auto_commands(name, run, cur["status"])
        if not cmds:
            return {"state": "stalled", "stage": name, "needs": "claude", "instruction": "no script for stage %s (%s)" % (name, cur["detail"])}
        log("stage %s: %s" % (name, cur["estimate"] or cur["detail"]))
        if not execute:
            for c in cmds:
                log("  DRY RUN, would run: " + " ".join(["python3", "-I", c[2].split("/")[-1]] + c[3:]))
            return {"state": "dry", "stage": name, "needs": None, "instruction": "dry run, nothing was run"}
        before = (cur["status"], cur["detail"])
        for c in cmds:
            log("  running " + " ".join(["python3", "-I", c[2].split("/")[-1]] + c[3:]))
            rc, out = runner(c)
            tail = "\n".join(out.strip().splitlines()[-6:])
            if rc != 0:
                return {"state": "failed", "stage": name, "needs": "claude", "instruction": "script failed (exit %s): %s" % (rc, tail)}
            log("    " + tail.replace("\n", "\n    "))
        run.write_summary()
        after = next((r for r in plan(run) if r["stage"] == name), None)
        if after and (after["status"], after["detail"]) == before and not after["complete"]:
            return {"state": "stalled", "stage": name, "needs": "claude",
                    "instruction": "ran the stage but nothing changed (%s). Look at the stage detail; it may be waiting (for example phones)." % after["detail"]}
        if name == "launch" and plan_written_not_approved(run):
            return {"state": "stopped", "stage": name, "needs": "user",
                    "instruction": "Plan written. Show launch/plan.md and ask the user to approve it."}
    return {"state": "stalled", "stage": None, "needs": "claude", "instruction": "reached the step limit"}
