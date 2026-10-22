"""Copy library: templated sequences of campaigns already launched in the Bliss HeyReach workspace (READ ONLY).

build(client, out_dir) pulls every non-draft campaign (GetAll, GetCampaignSequence, GetOverallStats), flattens the
sequence tree into steps, templates the text and writes
  copy-library/campaigns/<id>-<slug>.md   one file per campaign (what each step does, templated copy, stats, rule flags)
  copy-library/campaigns/<id>-<slug>.json machine readable twin (used by /iv-copy to find patterns)
  copy-library/index.md + index.json      one row per campaign: idea, persona, region, sender, structure, stats, flags
Templating (pure, tested): internal idea names -> {IDEA_NAME}, links -> {LINK}, the clause after "building a/an ..."
-> {IDEA_PLAIN} (the plain-words idea description is the part that changes per idea), names of the founders -> kept.
The library is a pattern source, NOT approved copy. Old copy often breaks the current rules (quick chat, internal
idea names, time commitment); the per-campaign `flags` list says which, using lib/copyrules.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import copyrules
from util import atomic_write, now_iso, write_json

NODE_LABEL = {"CHECK_IS_CONNECTION": "Check if already connected", "CONNECTION_REQUEST": "Connection request",
              "LIKE_POST": "Like a recent post (warm-up)", "VIEW_PROFILE": "View profile (warm-up)",
              "FOLLOW": "Follow (warm-up)", "MESSAGE": "Message", "INMAIL": "InMail", "END": "End",
              "CHECK_IS_OPEN_PROFILE": "Check open profile", "FIND_EMAIL": "Find email"}
SENDERS = ["Jay & Meelan", "Jay", "Meelan", "Akhil", "Mansi", "Prajwal", "Vinamr", "Punith"]
REGIONS = [("USA", r"\bUSA?\b|\bUnited States\b"), ("UK", r"\bUK\b"), ("EU", r"\bEU\b"), ("Gulf", r"\bGULF\b|\bGulf\b")]


# ---- tree handling (pure) -------------------------------------------------------------------------------------
def flatten(node, branch="start", depth=0, out=None, parent_type=None):
    """Depth-first list of steps. branch tells which path of the parent led here:
    start | already_connected | not_connected | accepted | not_accepted | next | replied."""
    out = [] if out is None else out
    if not node:
        return out
    t = node.get("nodeType")
    out.append({"type": t, "branch": branch, "delay": node.get("actionDelay"), "unit": node.get("actionDelayUnit"),
                "payload": node.get("payload"), "depth": depth})
    cond, uncond = node.get("conditionalNode"), node.get("unconditionalNode")
    cond_label = {"CHECK_IS_CONNECTION": "already_connected", "CONNECTION_REQUEST": "accepted",
                  "MESSAGE": "replied", "INMAIL": "replied"}.get(t, "yes")
    uncond_label = {"CHECK_IS_CONNECTION": "not_connected", "CONNECTION_REQUEST": "not_accepted"}.get(t, "next")
    # the accepted path first (it is the main message chain), then the not-accepted path
    if cond and cond.get("nodeType") != "END":
        flatten(cond, cond_label, depth + 1, out, t)
    if uncond and uncond.get("nodeType") != "END":
        flatten(uncond, uncond_label, depth + (1 if t in ("CONNECTION_REQUEST", "CHECK_IS_CONNECTION") else 0), out, t)
    return out


def variants_of(payload):
    """List of variant dicts {subject, body} from a MESSAGE, CONNECTION_REQUEST or INMAIL payload."""
    out = []
    for m in (payload or {}).get("messages") or []:
        if isinstance(m, dict):
            out.append({"subject": m.get("subject") or "", "body": m.get("message") or ""})
        else:
            out.append({"subject": "", "body": m or ""})
    for mv in (payload or {}).get("messageVersions") or []:
        out.append({"subject": "", "body": mv.get("message") or "", "type": mv.get("type", "TEXT")})
    return out


def fallback_of(payload):
    fb = (payload or {}).get("fallbackMessage")
    if isinstance(fb, dict):
        return fb.get("message") or ""
    return fb or ""


# ---- templating (pure) ----------------------------------------------------------------------------------------
IDEA_NAME_RE = re.compile(r"\bBliss(?!growth\b)[A-Z][A-Za-z]*\b")
LINK_RE = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|io|ai|co)/\S*)", re.I)
BUILDING_RE = re.compile(r"\b(building|launching|developing|creating)\s+((?:an?|the)\s+[^.\n!?]*)", re.I)


def dedash(text):
    """Em and en dashes in quoted old copy and campaign names become hyphens (the project never writes em dashes). The rule check
    runs on the original text first, so the 'em_dash' flag is still reported."""
    return (text or "").replace("\u2014", "-").replace("\u2013", "-")


def templatize(text):
    t = dedash(text)
    t = IDEA_NAME_RE.sub("{IDEA_NAME}", t)
    t = LINK_RE.sub("{LINK}", t)
    t = BUILDING_RE.sub(lambda m: "%s {IDEA_PLAIN}" % m.group(1), t)
    return t


# ---- classification (pure, heuristic: labelled as such in the files) ------------------------------------------
def classify(text, index, total, blank=False):
    """One short phrase: what this message does."""
    t = (text or "").lower()
    words = len(re.findall(r"\S+", t))
    if blank:
        return "Blank invite: no note, the profile does the work"
    tags = []
    if index == 0:
        tags.append("opener")
    if re.search(r"advis", t):
        tags.append("advisor ask")
    if re.search(r"launched|built|sold|valued|backed|yieldify|reachdesk|founded|track record|startups", t):
        tags.append("credibility")
    if re.search(r"do you agree|do you think|does this match|exception|your read|your view|would you say|agree\?", t):
        tags.append("opinion question")
    if re.search(r"\bcall\b|\bchat\b|\bmeet|\bcalendar|\bthis week|\bslot", t):
        tags.append("asks for a call")
    if re.search(r"funding|funded|mvp|moving ahead|update", t):
        tags.append("progress update")
    if re.search(r"early feedback|getting strong|design partner|customers", t):
        tags.append("social proof")
    if re.search(r"last|final|closing|leave it", t):
        tags.append("close-out")
    if not tags:
        tags.append("nudge" if words < 30 else "message")
    if index > 0 and "opener" in tags:
        tags.remove("opener")
    return ", ".join(tags)


def parse_name(name):
    """idea, persona tags, regions, sender from the campaign name (best effort, shown as parsed)."""
    idea = ""
    m = re.search(r"\bBliss[A-Za-z]+\b", name or "")
    if m:
        idea = m.group(0)
    else:
        idea = re.split(r"\s[\u2014-]\s", name or "")[0].strip()
    tags = re.findall(r"\[([^\]]+)\]", name or "")
    regions = [r for r, rx in REGIONS if re.search(rx, name or "")]
    sender = ""
    for s in SENDERS:
        if re.search(r"\b" + re.escape(s) + r"\b", name or ""):
            sender = s
            break
    persona = [t for t in tags if t.lower() not in ("punith",) and not re.search(r"^(USA|UK|EU|USA, EU, UK|UK,\s?EU|UK, EU)$", t)]
    kind = []
    if re.search(r"inmail", name or "", re.I):
        kind.append("inmail")
    return {"idea": idea, "persona": persona, "regions": regions, "sender": sender, "kind": kind}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60] or "campaign"


# ---- one campaign ---------------------------------------------------------------------------------------------
def describe_tree(node):
    """Compact structure of a sequence tree, branches in brackets, e.g.
    CHECK(connected: MSG x3 | new: INVITE(blank)(accepted: LIKE > MSG x4 | not: INMAIL))."""
    if not node or node.get("nodeType") == "END":
        return "end"
    parts, n = [], node
    while n and n.get("nodeType") != "END":
        t = n["nodeType"]
        cond, uncond = n.get("conditionalNode"), n.get("unconditionalNode")
        if t == "MESSAGE":
            cnt = 0
            while n and n.get("nodeType") == "MESSAGE":
                cnt += 1
                n = n.get("unconditionalNode")
            parts.append("MSG x%d" % cnt)
            continue
        if t == "CHECK_IS_CONNECTION":
            parts.append("CHECK(connected: %s | new: %s)" % (describe_tree(cond), describe_tree(uncond)))
            break
        if t == "CONNECTION_REQUEST":
            blank = not any(x["body"].strip() for x in variants_of(n.get("payload")))
            lab = "INVITE(blank)" if blank else "INVITE(note x%d)" % len(variants_of(n.get("payload")))
            parts.append("%s(accepted: %s | not: %s)" % (lab, describe_tree(cond), describe_tree(uncond)))
            break
        parts.append({"LIKE_POST": "LIKE", "VIEW_PROFILE": "VIEW"}.get(t, t))
        n = uncond
    return " > ".join(parts) or "end"


def build_one(camp, seq, stats):
    steps = flatten(seq) if seq and "nodeType" in seq else []
    msg_total = sum(1 for s in steps if s["type"] == "MESSAGE")
    items, msg_idx = [], 0
    flags = {}
    for i, s in enumerate(steps):
        t = s["type"]
        if t not in ("CONNECTION_REQUEST", "MESSAGE", "INMAIL"):
            items.append({"n": i + 1, "type": t, "branch": s["branch"], "delay": "%s %s" % (s["delay"], s["unit"]),
                          "what": NODE_LABEL.get(t, t), "variants": []})
            continue
        vs = variants_of(s["payload"])
        blank = t == "CONNECTION_REQUEST" and not any(v["body"].strip() for v in vs)
        channel = {"CONNECTION_REQUEST": "li_invite", "MESSAGE": "li_followup", "INMAIL": "inmail"}[t]
        step_no = 1
        if t == "MESSAGE":
            msg_idx += 1
            step_no = msg_idx
        out_vs = []
        for v in vs:
            chk = copyrules.check({"channel": channel, "step": step_no, "variant": "V", "subject": v["subject"],
                                   "body": v["body"], "fallback": fallback_of(s["payload"])},
                                  {"idea_name": ""}) if v["body"].strip() else {"errors": [], "warnings": []}
            for e in chk["errors"]:
                flags[e["rule"]] = flags.get(e["rule"], 0) + 1
            out_vs.append({"subject": templatize(v["subject"]), "body": templatize(v["body"]),
                           "words": copyrules.word_count(v["body"]),
                           "errors": sorted(set(e["rule"] for e in chk["errors"]))})
        what = classify(vs[0]["body"] if vs else "", msg_idx - 1 if t == "MESSAGE" else 0, msg_total, blank) \
            if t == "MESSAGE" or blank else ("Connection note" if t == "CONNECTION_REQUEST" else "InMail: " + classify(
                vs[0]["body"] if vs else "", 0, 1))
        items.append({"n": i + 1, "type": t, "branch": s["branch"], "delay": "%s %s" % (s["delay"], s["unit"]),
                      "what": what, "channel": channel, "step": step_no, "variants": out_vs,
                      "fallback": templatize(fallback_of(s["payload"])), "blank": blank,
                      "withdraw_after_days": (s["payload"] or {}).get("toBeWithdrawnAfterDays")})
    meta = parse_name(dedash(camp.get("name", "")))
    ps = camp.get("progressStats") or {}
    st = stats or {}
    return {"id": camp.get("id"), "name": dedash(camp.get("name")), "status": camp.get("status"),
            "created": (camp.get("creationTime") or "")[:10], "list": dedash(camp.get("linkedInUserListName")),
            "leads": ps.get("totalUsers", 0), **meta, "structure": describe_tree(seq) if seq and "nodeType" in seq else "",
            "stats": {k: st.get(k) for k in ("connectionsSent", "connectionsAccepted", "connectionAcceptanceRate",
                                             "messagesSent", "totalMessageStarted", "totalMessageReplies",
                                             "messageReplyRate", "inmailMessagesSent", "totalInmailReplies",
                                             "inMailReplyRate", "autoTaggedInterested", "uniqueLeadsContacted")},
            "steps": items, "rule_flags": flags}


def pct(x):
    try:
        return "%.0f%%" % (float(x) * 100)
    except (TypeError, ValueError):
        return "n/a"


def render_md(c):
    L = ["# %s" % c["name"], "",
         "- HeyReach campaign id: %s (read only copy, status %s, created %s)" % (c["id"], c["status"], c["created"]),
         "- Idea: %s | Persona: %s | Region: %s | Sender: %s" % (c["idea"] or "?", ", ".join(c["persona"]) or "?",
                                                                 ", ".join(c["regions"]) or "?", c["sender"] or "?"),
         "- Leads: %s | Structure: `%s`" % (c["leads"], c["structure"])]
    s = c["stats"]
    L.append("- Results: invites sent %s, accepted %s (%s); messages sent %s, replies %s (%s); InMails sent %s, replies %s (%s); "
             "tagged interested %s" % (s.get("connectionsSent"), s.get("connectionsAccepted"),
                                      pct(s.get("connectionAcceptanceRate")), s.get("messagesSent"),
                                      s.get("totalMessageReplies"), pct(s.get("messageReplyRate")),
                                      s.get("inmailMessagesSent"), s.get("totalInmailReplies"), pct(s.get("inMailReplyRate")),
                                      s.get("autoTaggedInterested")))
    L.append("- Rules today: " + (", ".join("%s x%d" % kv for kv in sorted(c["rule_flags"].items())) or "no rule errors")
             + "  (old copy often breaks the current rules, use the structure, not the wording)")
    L += ["", "Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. "
          "The 'what it does' labels are heuristic.", ""]
    for it in c["steps"]:
        L.append("## Step %d: %s (%s, wait %s, path: %s)" % (it["n"], NODE_LABEL.get(it["type"], it["type"]), it["what"],
                                                            it["delay"], it["branch"]))
        if it.get("withdraw_after_days"):
            L.append("Withdraw the invite after %s days." % it["withdraw_after_days"])
        for i, v in enumerate(it["variants"], 1):
            L.append("")
            tag = "Variant %d" % i + (" (blank invite)" if it.get("blank") and not v["body"].strip() else "")
            L.append("**%s**, %d words%s" % (tag, v["words"], ", rule errors: " + ", ".join(v["errors"]) if v["errors"] else ""))
            if v["subject"]:
                L.append("Subject: %s" % v["subject"])
            L += ["", "```", v["body"], "```"]
        L.append("")
    return "\n".join(L) + "\n"


def build(client, out_dir, log=print, only_non_draft=True):
    out = Path(out_dir)
    (out / "campaigns").mkdir(parents=True, exist_ok=True)
    camps = client.campaigns()
    rows, skipped = [], []
    for camp in camps:
        if only_non_draft and camp.get("status") == "DRAFT":
            skipped.append({"id": camp["id"], "name": camp.get("name"), "why": "draft, never launched"})
            continue
        try:
            seq = client.sequence(camp["id"])
        except Exception as e:  # keep going: one broken campaign must not stop the library
            skipped.append({"id": camp["id"], "name": camp.get("name"), "why": "sequence error: %s" % str(e)[:120]})
            continue
        try:
            stats = client.stats(camp["id"])
        except Exception:
            stats = {}
        c = build_one(camp, seq, stats)
        base = "%s-%s" % (c["id"], slug(c["name"]))
        atomic_write(out / "campaigns" / (base + ".md"), render_md(c))
        write_json(out / "campaigns" / (base + ".json"), c)
        c["file"] = "campaigns/%s.md" % base
        rows.append(c)
        log("  %s %s" % (c["id"], c["name"][:70]))
    rows.sort(key=lambda r: (r["idea"] or "~", r["created"]), reverse=False)
    write_json(out / "index.json", {"built_at": now_iso(), "campaigns": [
        {k: r[k] for k in ("id", "name", "status", "created", "idea", "persona", "regions", "sender", "kind", "leads",
                           "structure", "stats", "rule_flags", "file")} for r in rows], "skipped": skipped})
    atomic_write(out / "index.md", render_index(rows, skipped))
    return {"campaigns": len(rows), "skipped": skipped}


def render_index(rows, skipped):
    L = ["# Copy library index", "",
         "Built %s by `bin/copy_library.py build` from the Bliss HeyReach workspace (read only). One file per campaign in "
         "`campaigns/`. Structure codes: INVITE(blank or note), CHECK, LIKE/VIEW (warm-up), MSG xN (follow-ups after "
         "accept), INMAIL. Rates: accept = invites accepted / sent, reply = replies / messages sent, InMail = replies / sent. "
         "Small campaigns have noisy rates, read them with the lead count. 'Rule errors' = how many pieces of text "
         "would fail today's rules (lib/copyrules.py)." % now_iso()[:10], "",
         "| Campaign | Idea | Persona | Region | Sender | Status | Leads | Structure | Accept | Reply | InMail | Rule errors |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["stats"]
        L.append("| [%s](%s) | %s | %s | %s | %s | %s | %s | `%s` | %s | %s | %s | %s |" % (
            r["name"].replace("|", "/")[:60], r["file"], r["idea"] or "?", ", ".join(r["persona"])[:30] or "?",
            ", ".join(r["regions"]) or "?", r["sender"] or "?", r["status"], r["leads"], r["structure"],
            pct(s.get("connectionAcceptanceRate")) if s.get("connectionsSent") else "n/a",
            pct(s.get("messageReplyRate")) if s.get("messagesSent") else "n/a",
            pct(s.get("inMailReplyRate")) if s.get("inmailMessagesSent") else "n/a",
            sum(r["rule_flags"].values())))
    if skipped:
        L += ["", "Skipped (%d): " % len(skipped) + "; ".join("%s (%s)" % (x["name"], x["why"]) for x in skipped)]
    return "\n".join(L) + "\n"
