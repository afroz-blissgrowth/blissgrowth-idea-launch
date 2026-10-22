"""Stage 12: /iv-launch, HeyReach only (v1). Lists and DRAFT campaigns plus Mansi's call sheet. NOTHING IS EVER STARTED.

Flow: plan (pure, no network) -> user approval (approval.json tied to a hash of the plan and the copy) -> execute (idempotent).
  groups     "5 Ready: LinkedIn" rows grouped by tier x region (config launch.group_by). One HeyReach lead list per group.
  campaigns  per group a connect campaign (senders: Jay and Meelan accounts): CHECK_IS_CONNECTION, invite (note variants or blank),
             after accept a warm-up like and the follow-ups. Per group in launch.inmail_tiers an InMail campaign (sender: the associate).
             Variants V1..V4 go into the node's `messages` array, HeyReach rotates them (A/B).
  names      launch.name_template = "<prefix> - <Tier> - <Region> - <YYYY-MM-DD>" (+ " - InMail"). The prefix is the Campaign prefix of
             the idea page, the reply agent uses it to match a campaign to its idea.
  state      launch/launch.json records every id created, so a re-run resumes and never creates a list, campaign or lead twice.
  safety     the HeyReach client has no start, resume, pause or delete method. After a create the status is read back and must be DRAFT.
             A TEST brief, a SIMULATED copy or launch approval, an unapproved or changed plan, or missing sender accounts refuse execution.
  call sheet T1 leads with a phone, a separate Google Sheet shared only with launch.mansi_email (ask the user if empty).
"""
from __future__ import annotations

import csv
import getpass
import hashlib
import json
import re

import config
import copyrules
import schema
from util import now_iso, read_json, today, write_json


class LaunchError(RuntimeError):
    pass


def lcfg():
    return config.get("launch", {}) or {}


# ---- grouping --------------------------------------------------------------------------------------
def region_of(country):
    c = (country or "").strip().lower()
    star = None
    for region, names in (lcfg().get("regions") or {}).items():
        if names == "*":
            star = region
            continue
        if c in [n.lower() for n in names]:
            return region
    return star or "Other"


def prefix_of(brief, run=None):
    """The Campaign prefix. The idea page's prefix wins (the reply agent matches campaigns to the HRA Ideas row by it), then the
    brief's idea.campaign_prefix, then the idea name. A TEST idea page (renamed prefix) is ignored."""
    if run is not None:
        rec = read_json(run.dir / "idea-page.json", None) or {}
        fields = read_json(run.dir / "idea-page" / "fields.json", None) or {}
        for v in ((rec.get("prefix") if not rec.get("test") else None), fields.get("Campaign prefix")):
            if v and str(v).strip():
                return str(v).strip()
    idea = brief.get("idea") or {}
    return idea.get("campaign_prefix") or idea.get("name") or idea.get("slug") or "Idea"


def prefix_problem(prefix):
    """The reply agent (n8n 'HeyReach Reply Agent | 1. Intake & Draft', node Match Idea) silently ignores every campaign whose
    name does not start with launch.prefix_must_start_with (default 'bliss', case-insensitive). Returns a problem text or ''."""
    need = str(lcfg().get("prefix_must_start_with", "bliss") or "")
    if need and not prefix.lower().startswith(need.lower()):
        return ("Campaign prefix '%s' does not start with '%s': the reply agent ignores such campaigns (node Match Idea). "
                "Fix the idea page's Campaign prefix." % (prefix, need))
    return ""


def read_ready(run, which="linkedin"):
    p = run.dir / "ready" / (which + ".csv")
    try:
        with open(p, newline="", encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if r.get("status", "ready") == "ready"]
    except FileNotFoundError:
        return []


def group_leads(rows):
    keys = lcfg().get("group_by", ["tier", "region"])
    groups = {}
    for r in rows:
        r = dict(r, tier=r.get("tier") or "T2", region=region_of(r.get("country")))
        k = tuple(r[x] for x in keys)
        groups.setdefault(k, []).append(r)
    return groups


def fill(template, **kw):
    return re.sub(r"\s+", " ", template.format(**kw)).strip()


# ---- copy -> sequence --------------------------------------------------------------------------------
def pick(items, channel, tier, step):
    own = [i for i in items if i["channel"] == channel and i["tier"] == tier and i["step"] == step]
    pool = own or [i for i in items if i["channel"] == channel and i["tier"] == "all" and i["step"] == step]
    return sorted(pool, key=lambda i: (i["variant"] != "V1", i["variant"]))


def auto_fallback(text):
    """Fallback used when HeyReach cannot fill a variable: only {FIRST_NAME} style names are allowed in it."""
    t = text or ""
    t = re.sub(r",\s*\{FIRST_NAME\}", "", t)
    t = t.replace("{FIRST_NAME}", "there")
    return t


def fallback_for(variants):
    for v in variants:
        if v.get("fallback"):
            return v["fallback"]
    first = next((v for v in variants if v.get("body")), None)
    return auto_fallback(first["body"]) if first else ""


def _end(delay=1, unit="DAY"):
    return {"nodeType": "END", "actionDelay": delay, "actionDelayUnit": unit, "payload": None}


def build_connect_sequence(items, tier):
    cfg = lcfg()
    inv = pick(items, "li_invite", tier, 1)
    if not inv:
        raise LaunchError("no invite copy for tier %s" % tier)
    notes = [v.get("body", "") for v in inv]
    invite_payload = {"messages": notes if any(n.strip() for n in notes) else [""],
                      "toBeWithdrawnAfterDays": int(cfg.get("withdraw_invite_after_days", 14))}
    fb = fallback_for(inv)
    invite_payload["fallbackMessage"] = fb if any(n.strip() for n in notes) else ""
    steps = sorted({i["step"] for i in items if i["channel"] == "li_followup" and (i["tier"] in (tier, "all"))})
    if not steps:
        raise LaunchError("no follow-up copy for tier %s" % tier)
    delays = cfg.get("message_delays") or [[3, "HOUR"], [2, "DAY"]]
    nodes = []
    for n, s in enumerate(steps):
        vs = pick(items, "li_followup", tier, s)
        d = delays[min(n, len(delays) - 1)]
        nodes.append({"nodeType": "MESSAGE", "actionDelay": d[0], "actionDelayUnit": d[1],
                      "payload": {"messages": [v["body"] for v in vs], "fallbackMessage": fallback_for(vs)}})
    # chain the messages back to front
    nxt = _end(1, "DAY")
    for node in reversed(nodes):
        node["conditionalNode"] = _end(1, "DAY")
        node["unconditionalNode"] = nxt
        nxt = node
    chain = nxt
    warm = cfg.get("warmup_before_messages")
    if warm == "LIKE_POST":
        chain = {"nodeType": "LIKE_POST", "actionDelay": 3, "actionDelayUnit": "HOUR",
                 "payload": {"reactionType": "LIKE", "randomReaction": False, "reactBefore": "WEEK1",
                             "skipDelayIfCannotLike": True}, "unconditionalNode": chain}
    elif warm == "VIEW_PROFILE":
        chain = {"nodeType": "VIEW_PROFILE", "actionDelay": 3, "actionDelayUnit": "HOUR", "payload": None,
                 "unconditionalNode": chain}
    request = {"nodeType": "CONNECTION_REQUEST", "actionDelay": 0, "actionDelayUnit": "HOUR", "payload": invite_payload,
               "conditionalNode": chain, "unconditionalNode": _end(3, "DAY")}
    return {"nodeType": "CHECK_IS_CONNECTION", "actionDelay": 0, "actionDelayUnit": "HOUR", "payload": None,
            "conditionalNode": _end(1, "DAY"), "unconditionalNode": request}


def build_inmail_sequence(items, tier):
    vs = pick(items, "inmail", tier, 1)
    if not vs:
        raise LaunchError("no InMail copy for tier %s" % tier)
    fb = next((v for v in vs if v.get("fallback")), vs[0])
    fb_body = fb.get("fallback") or auto_fallback(fb["body"])
    inmail = {"nodeType": "INMAIL", "actionDelay": 3, "actionDelayUnit": "HOUR",
              "payload": {"messages": [{"subject": v.get("subject", ""), "message": v["body"]} for v in vs],
                          "fallbackMessage": {"subject": auto_fallback(fb.get("subject", "")), "message": fb_body}},
              "conditionalNode": _end(5, "DAY"), "unconditionalNode": _end(3, "DAY")}
    return {"nodeType": "VIEW_PROFILE", "actionDelay": 0, "actionDelayUnit": "HOUR", "payload": None,
            "unconditionalNode": inmail}


FOLLOWS = ("CONNECTION_REQUEST", "MESSAGE", "INMAIL", "VIEW_PROFILE", "FOLLOW", "LIKE_POST")


def validate_sequence(tree):
    """Local check of the rules HeyReach documents (create_campaign tool text): every path ends with END, MESSAGE and INMAIL have a
    conditional END and an unconditional next, CONNECTION_REQUEST and CHECK_IS_CONNECTION have both branches, a delay of at least 3
    hours after an action node (except the reply-exit END), at most one CONNECTION_REQUEST and CHECK per path, MESSAGE only on a
    connected path, size limits. Returns a list of problems (empty = fine)."""
    problems = []

    def walk(n, path, prev, first, connected, reply_exit):
        t = n.get("nodeType")
        d, u = n.get("actionDelay"), n.get("actionDelayUnit")
        if d is None or u not in ("HOUR", "DAY"):
            problems.append("%s node has no valid delay" % t)
        else:
            hours = d * (24 if u == "DAY" else 1)
            if hours > 500 * 24:
                problems.append("delay over 500 days")
            if prev in FOLLOWS and hours < 3 and not reply_exit and not first:
                problems.append("%s after %s needs a delay of at least 3 hours" % (t, prev))
        counts = dict(path)
        if t in ("CONNECTION_REQUEST", "CHECK_IS_CONNECTION", "FOLLOW"):
            counts[t] = counts.get(t, 0) + 1
            if counts[t] > 1:
                problems.append("more than one %s on a path" % t)
        cond, uncond = n.get("conditionalNode"), n.get("unconditionalNode")
        if t == "END":
            if cond or uncond:
                problems.append("END has children")
            return
        if t == "MESSAGE" and not connected:
            problems.append("MESSAGE on a path where the lead may not be connected")
        p = n.get("payload") or {}
        if t == "CONNECTION_REQUEST":
            for m in p.get("messages") or []:
                if len(m) > 300:
                    problems.append("invite note over 300 chars")
            if any(re.search(r"\{(?!FIRST_NAME|LAST_NAME|MY_FIRST_NAME|MY_LAST_NAME)[A-Z_]+\}", m or "") for m in [p.get("fallbackMessage") or ""]):
                problems.append("fallback uses a variable that is not allowed there")
            if not cond or not uncond:
                problems.append("CONNECTION_REQUEST needs both branches")
        if t == "CHECK_IS_CONNECTION" and (not cond or not uncond):
            problems.append("CHECK_IS_CONNECTION needs both branches")
        if t in ("MESSAGE", "INMAIL"):
            ms = p.get("messages") or []
            if not ms:
                problems.append("%s has no messages" % t)
            for m in ms:
                body = m.get("message") if isinstance(m, dict) else m
                if not (body or "").strip():
                    problems.append("%s has an empty message" % t)
                if t == "INMAIL":
                    if len(body or "") > 1900:
                        problems.append("InMail body over 1900 chars")
                    if len((m.get("subject") or "")) > 200 or not (m.get("subject") or "").strip():
                        problems.append("InMail subject missing or over 200 chars")
                if t == "MESSAGE" and len(body or "") > 8000:
                    problems.append("message over 8000 chars")
            allm = [(m.get("message") if isinstance(m, dict) else m) or "" for m in ms]
            need_fb = any(re.search(r"\{(?!FIRST_NAME|LAST_NAME|MY_FIRST_NAME|MY_LAST_NAME)[A-Z_]+\}", x) for x in allm)
            if need_fb and not p.get("fallbackMessage"):
                problems.append("%s uses personalisation so it needs a fallbackMessage" % t)
            if not cond or cond.get("nodeType") != "END" or not uncond:
                problems.append("%s needs a conditional END and an unconditional next node" % t)
        for child, ctype, label in ((cond, t, "c"), (uncond, t, "u")):
            if not child:
                continue
            ch_connected = connected or (t in ("CONNECTION_REQUEST", "CHECK_IS_CONNECTION") and label == "c")
            walk(child, counts, t, False, ch_connected, t in ("MESSAGE", "INMAIL") and label == "c")

    if not tree:
        return ["empty sequence"]
    walk(tree, {}, None, True, False, False)
    return problems


# ---- plan ------------------------------------------------------------------------------------------
def load_copy(run):
    cj = read_json(run.dir / "copy.json", None)
    if not cj:
        raise LaunchError("no copy.json: run /iv-copy first")
    return cj


def plan(run, date=None):
    """Pure plan (no network). Raises LaunchError for missing inputs; unmet execution gates are listed in plan['blockers']."""
    brief = run.brief()
    cj = load_copy(run)
    items = cj["items"]
    rows = read_ready(run, "linkedin")
    if not rows:
        raise LaunchError("no rows in ready/linkedin.csv: run /iv-ready first")
    date = date or today()
    cfg = lcfg()
    prefix = prefix_of(brief, run)
    groups = group_leads(rows)
    inmail_tiers = set(cfg.get("inmail_tiers", ["T1"]))
    senders = cfg.get("senders") or {}
    gl = []
    blockers = []
    pp = prefix_problem(prefix)
    if pp:
        blockers.append(pp)
    for key in sorted(groups):
        tier = groups[key][0]["tier"]
        region = groups[key][0]["region"]
        names = {"prefix": prefix, "tier": tier, "region": region, "date": date, "idea": prefix}
        list_name = fill(cfg["name_template"], **names)
        g = {"tier": tier, "region": region, "leads": len(groups[key]), "list_name": list_name, "campaigns": [],
             "person_ids": [r["person_id"] for r in groups[key]]}
        try:
            seq = build_connect_sequence(items, tier)
            g["campaigns"].append({"kind": "connect", "name": list_name, "sender": "founders", "sequence": seq,
                                   "problems": validate_sequence(seq)})
        except LaunchError as e:
            blockers.append("tier %s: %s" % (tier, e))
        if tier in inmail_tiers:
            try:
                seq = build_inmail_sequence(items, tier)
                g["campaigns"].append({"kind": "inmail", "name": fill(cfg["inmail_name_template"], **names),
                                       "sender": "associate", "sequence": seq, "problems": validate_sequence(seq)})
            except LaunchError as e:
                blockers.append("tier %s InMail: %s" % (tier, e))
        for c in g["campaigns"]:
            if len(c["name"]) > cfg.get("max_name_len", 120):
                blockers.append("name too long: %s" % c["name"])
            for p in c["problems"]:
                blockers.append("%s sequence: %s" % (c["name"], p))
        gl.append(g)
    p = {"run": run.dir.name, "date": date, "prefix": prefix, "test": bool((brief.get("idea") or {}).get("test")),
         "copy_hash": cj.get("items_hash"), "copy_approved": bool(cj.get("approved")), "copy_simulated": bool(cj.get("simulated")),
         "groups": gl, "leads_total": len(rows), "blockers": blockers,
         "senders": {"founders": senders.get("founders"), "associate": senders.get("associate")}}
    p["plan_hash"] = plan_hash(p)
    return p


def plan_hash(p):
    keep = {"date": p["date"], "prefix": p["prefix"], "copy_hash": p["copy_hash"],
            "groups": [{"list": g["list_name"], "tier": g["tier"], "region": g["region"], "n": g["leads"],
                        "ids": sorted(g["person_ids"]),
                        "campaigns": [{"name": c["name"], "kind": c["kind"],
                                       "seq": hashlib.sha1(json.dumps(c["sequence"], sort_keys=True).encode()).hexdigest()}
                                      for c in g["campaigns"]]} for g in p["groups"]]}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


def render_plan(p):
    L = ["# Launch plan (DRAFT campaigns only, nothing is started)", "",
         "Run %s, date %s, prefix `%s`. %d leads in %d lists. Plan hash `%s`." % (p["run"], p["date"], p["prefix"],
                                                                            p["leads_total"], len(p["groups"]), p["plan_hash"]), ""]
    L.append("| HeyReach list | Tier | Region | Leads | Campaigns (all created as DRAFT) |")
    L.append("|---|---|---|---|---|")
    for g in p["groups"]:
        L.append("| %s | %s | %s | %d | %s |" % (g["list_name"], g["tier"], g["region"], g["leads"],
                                                "; ".join("%s (%s)" % (c["name"], c["kind"]) for c in g["campaigns"])))
    L += ["", "Senders: founders (Jay, Meelan) %s, associate %s" % (p["senders"]["founders"], p["senders"]["associate"]), ""]
    if p["blockers"]:
        L += ["Problems in the plan:"] + ["- " + b for b in p["blockers"]] + [""]
    return "\n".join(L) + "\n"


# ---- approval and gates ----------------------------------------------------------------------------
class Launch:
    def __init__(self, run):
        self.run = run
        self.dir = run.dir / "launch"
        self.plan_path = self.dir / "plan.json"
        self.approval_path = self.dir / "approval.json"
        self.state_path = self.dir / "launch.json"
        self.callsheet_path = self.dir / "callsheet.json"

    def state(self):
        return read_json(self.state_path, {"groups": {}, "executed": False})

    def save_state(self, st):
        st["updated_at"] = now_iso()
        write_json(self.state_path, st)

    def make_plan(self, date=None):
        p = plan(self.run, date)
        write_json(self.plan_path, p)
        from util import atomic_write
        atomic_write(self.dir / "plan.md", render_plan(p))
        return p

    def approve(self, note, simulated=False):
        p = read_json(self.plan_path, None)
        if not p:
            raise LaunchError("no plan yet: run plan first and show it to the user")
        if not note:
            raise LaunchError("--note is required: who approved what")
        if p["blockers"]:
            raise LaunchError("the plan has problems, fix them first: " + "; ".join(p["blockers"][:3]))
        cur = plan(self.run, p["date"])
        if cur["plan_hash"] != p["plan_hash"]:
            raise LaunchError("launch/plan.json is out of date (inputs changed since it was written, hash %s now %s). Run plan again, "
                              "show the new plan to the user, then approve." % (p["plan_hash"], cur["plan_hash"]))
        a = {"approved_at": now_iso(), "by": getpass.getuser(), "note": note, "simulated": bool(simulated),
             "plan_hash": p["plan_hash"], "date": p["date"], "leads": p["leads_total"]}
        write_json(self.approval_path, a)
        return a

    def gates(self, p, require_senders=True):
        """List of reasons execution is refused (empty = go)."""
        out = []
        if p["test"]:
            out.append("TEST brief (idea.test is true): a test run never creates anything in HeyReach")
        if not p["copy_approved"]:
            out.append("copy is not approved (/iv-copy approve)")
        if p["copy_simulated"]:
            out.append("copy approval is SIMULATED, a real user must approve")
        a = read_json(self.approval_path, None)
        if not a:
            out.append("no launch approval (run approve after the user said yes to this plan)")
        else:
            if a.get("simulated"):
                out.append("launch approval is SIMULATED")
            if a.get("plan_hash") != p["plan_hash"]:
                out.append("the plan changed since it was approved (hash %s, approved %s): run plan, show it to the user, approve again" % (
                    p["plan_hash"], a.get("plan_hash")))
        if p["blockers"]:
            out.append("plan problems: " + "; ".join(p["blockers"][:3]))
        rec = read_json(self.run.dir / "idea-page.json", None)
        skipped = (self.run.dir / "idea-page" / "skipped.json").exists()
        if not skipped and (not rec or rec.get("test")):
            out.append("no real reply-agent idea page recorded (/iv-idea-page, or idea_page.py skip on the user's say-so): "
                       "replies would get no idea context")
        if require_senders:
            s = p["senders"]
            f = s.get("founders") or {}
            need_f = any(c["sender"] == "founders" for g in p["groups"] for c in g["campaigns"])
            need_a = any(c["sender"] == "associate" for g in p["groups"] for c in g["campaigns"])
            if need_f and not [v for v in f.values() if v]:
                out.append("launch.senders.founders has no HeyReach account id (bin/launch_run.py accounts lists them)")
            if need_a and not s.get("associate"):
                out.append("launch.senders.associate has no HeyReach account id")
        return out

    # ---- execute --------------------------------------------------------------------------------
    def execute(self, client, adopt_existing=False, log=print):
        """Create lists, add leads, create DRAFT campaigns with sequences. Idempotent through launch/launch.json."""
        saved = read_json(self.approval_path, None)
        p = plan(self.run, (saved or {}).get("date"))
        why = self.gates(p)
        if why:
            raise LaunchError("launch refused:\n  - " + "\n  - ".join(why))
        st = self.state()
        batch = int(lcfg().get("lead_batch", 100))
        founders = [v for v in (p["senders"]["founders"] or {}).values() if v]
        flags = dict(lcfg().get("campaign_flags") or {})
        rows = {r["person_id"]: r for r in read_ready(self.run, "linkedin")}
        for g in p["groups"]:
            gs = st["groups"].setdefault(g["list_name"], {"list_id": None, "added": [], "campaigns": {}})
            if not gs["list_id"]:
                found = client.find_list(g["list_name"])
                if found and not adopt_existing:
                    raise LaunchError("a HeyReach list named '%s' already exists (id %s) that this run did not create. Check it in "
                                      "HeyReach, then re-run with --adopt-existing-list to add leads to it." % (g["list_name"], found[0]["id"]))
                if found:
                    gs["list_id"] = found[0]["id"]
                else:
                    r = client.create_list(g["list_name"])
                    gs["list_id"] = r.get("id") or r.get("listId") or (r.get("list") or {}).get("id")
                    if not gs["list_id"]:
                        raise LaunchError("HeyReach did not return a list id: %s" % str(r)[:200])
                    log("created list %s (%s)" % (g["list_name"], gs["list_id"]))
                self.save_state(st)
            todo = [pid for pid in g["person_ids"] if pid not in set(gs["added"])]
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                leads = [lead_payload(rows[pid]) for pid in chunk if rows[pid].get("linkedin_url")]
                if leads:
                    res = client.add_leads(gs["list_id"], leads) or {}
                    failed = res.get("failedLeadsCount") or res.get("failed") or 0
                    if failed:
                        gs["failed_leads"] = gs.get("failed_leads", 0) + int(failed)
                        log("HeyReach reported %s failed leads in list %s" % (failed, g["list_name"]))
                gs["added"] += chunk
                self.save_state(st)
            for c in g["campaigns"]:
                cs = gs["campaigns"].setdefault(c["kind"], {})
                if not cs.get("id"):
                    found = client.find_campaign(c["name"])
                    if found:
                        raise LaunchError("a HeyReach campaign named '%s' already exists (id %s). Not touching it." % (
                            c["name"], found[0]["id"]))
                    accounts = founders if c["sender"] == "founders" else [p["senders"]["associate"]]
                    r = client.create_campaign(c["name"], gs["list_id"], accounts, **flags)
                    cid = r.get("id") or r.get("campaignId") or (r.get("campaign") or {}).get("id")
                    if not cid:
                        raise LaunchError("HeyReach did not return a campaign id: %s" % str(r)[:200])
                    cs.update({"id": cid, "name": c["name"], "created_at": now_iso()})
                    self.save_state(st)
                    log("created campaign %s (%s)" % (c["name"], cid))
                if not cs.get("sequence_set"):
                    client.update_sequence(cs["id"], c["sequence"])
                    cs["sequence_set"] = True
                    self.save_state(st)
                if not cs.get("status_verified"):
                    status = (client.campaign(cs["id"]) or {}).get("status")
                    cs["status"] = status
                    if status != "DRAFT":
                        self.save_state(st)
                        raise LaunchError("campaign %s has status %s, expected DRAFT. STOP: check it in HeyReach (this tool never "
                                          "starts campaigns)." % (cs["id"], status))
                    cs["status_verified"] = True
                    self.save_state(st)
        st["executed"] = True
        st["executed_at"] = now_iso()
        st["plan_hash"] = p["plan_hash"]
        st["date"] = p["date"]
        self.save_state(st)
        return st

    # ---- call sheet -----------------------------------------------------------------------------
    def callsheet_rows(self):
        p = self.run.dir / "ready" / "calls.csv"
        try:
            with open(p, newline="", encoding="utf-8") as f:
                return [r for r in csv.DictReader(f) if r.get("status", "ready") == "ready"]
        except FileNotFoundError:
            return []

    def callsheet(self, sc=None, dry_run=True):
        """Separate Google Sheet with Mansi's T1 call list, shared only with launch.mansi_email. Idempotent: re-running adds new or
        changed people (person fields only), never touches her status columns, never deletes."""
        cfg = lcfg()
        cs = cfg.get("callsheet") or {}
        email = (cfg.get("mansi_email") or "").strip()
        rows = self.callsheet_rows()
        brief = self.run.brief()
        headers = [h for h in schema.TABS[schema.TAB_READY_CALLS] if h != "status"] + list(cs.get("extra_columns", []))
        title = fill(cs.get("title_template", "{idea} - Call sheet - {date}"), idea=prefix_of(brief, self.run), date=today())
        rep = {"title": title, "rows": len(rows), "mansi_email": email or None, "dry_run": dry_run, "tab": cs.get("tab", "Calls"),
               "headers": headers}
        if not rows:
            rep["note"] = "no T1 people with a phone in ready/calls.csv"
            return rep
        if not email:
            rep["note"] = "launch.mansi_email is not set: ask the user for Mansi's Google account email, put it in config.local.json"
            return rep
        if dry_run:
            rep["note"] = "dry run: would create a sheet and share it with %s as %s" % (email, cs.get("share_role", "writer"))
            return rep
        if (brief.get("idea") or {}).get("test"):
            raise LaunchError("TEST brief: no call sheet is created for a test run")
        if sc is None:
            import sheet as sheetmod
            sc = sheetmod.SheetClient()
        st = read_json(self.callsheet_path, {})
        if not st.get("sheet_id"):
            res = sc.create(title, {cs.get("tab", "Calls"): headers})
            st = {"sheet_id": res.get("spreadsheetId") or res.get("sheet_id"), "url": res.get("url"), "created_at": now_iso(),
                  "pushed": {}, "shared_with": []}
            if not st["sheet_id"]:
                raise LaunchError("bridge did not return a sheet id: %s" % str(res)[:200])
            write_json(self.callsheet_path, st)
        if email not in st.get("shared_with", []):
            sc.share(st["sheet_id"], emails=[email], role=cs.get("share_role", "writer"))
            st.setdefault("shared_with", []).append(email)
            write_json(self.callsheet_path, st)
        send = []
        for r in rows:
            rec = {h: r.get(h, "") for h in schema.TABS[schema.TAB_READY_CALLS] if h != "status"}
            hsh = hashlib.sha1(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:12]
            if st["pushed"].get(r["person_id"]) != hsh:
                send.append(rec)
                st["pushed"][r["person_id"]] = hsh
        if send:
            sc.upsert(st["sheet_id"], cs.get("tab", "Calls"), "person_id", send)
        write_json(self.callsheet_path, st)
        rep.update({"sheet_id": st["sheet_id"], "url": st.get("url"), "upserted": len(send), "shared_with": st["shared_with"]})
        return rep


def lead_payload(r):
    out = {"firstName": r.get("first_name") or None, "lastName": r.get("last_name") or None,
           "profileUrl": r.get("linkedin_url"), "companyName": r.get("company") or None, "position": r.get("title") or None,
           "location": r.get("country") or None,
           "customUserFields": [{"name": "tier", "value": r.get("tier") or ""}, {"name": "person_id", "value": r["person_id"]}]}
    if r.get("email"):
        out["emailAddress"] = r["email"]
    return {k: v for k, v in out.items() if v not in (None, "")}
