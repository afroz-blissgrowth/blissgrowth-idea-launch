"""Stage 11: the reply-agent idea page in the Blissgrowth Notion database "Idea Contexts".

The page is what the HeyReach Reply Agent reads to draft replies from day one (n8n table HRA Ideas, filled by the workflow
"HeyReach Reply Agent | 4. Idea Sync"). Properties (database e895ef6bf69d41cf9faf11e1cbbdee4f): Idea (title), Campaign prefix,
Calendly (Jay), Calendly (Meelan), Pitch, Who we're targeting, Idea specifics.

NO Notion API key is used. The skill runs inside Claude Code and creates the page with the Notion MCP tools of the person running it
(`notion-query-data-sources`, `notion-create-pages`, the claude.ai Notion connection whose workspace is "Blissgrowth"). This module
holds everything that is not an MCP call: the draft fields, validation, the user's confirmation, the exact MCP payload, and the
record that keeps the step idempotent (idea-page.json in the run folder: never create twice).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import re

import config
import copyrules
from util import now_iso, read_json, write_json


class IdeaPageError(RuntimeError):
    pass


def icfg():
    return config.get("idea_page", {}) or {}


REQUIRED = ["Idea", "Campaign prefix", "Pitch", "Who we're targeting", "Idea specifics"]
OPTIONAL = ["Calendly (Jay)", "Calendly (Meelan)"]
CALENDLY_RE = re.compile(r"^https://calendly\.com/\S+$")


def page_id_from_url(url):
    """The 32 hex characters at the end of a Notion page link (with or without a title slug and ?pvs=)."""
    m = re.search(r"([0-9a-fA-F]{32})(?:[/?#].*)?$", url.strip())
    return m.group(1).lower() if m else ""


class IdeaPage:
    def __init__(self, run):
        self.run = run
        self.dir = run.dir / "idea-page"
        self.fields_path = self.dir / "fields.json"
        self.confirm_path = self.dir / "confirm.json"
        self.record_path = run.dir / "idea-page.json"
        self.skip_path = self.dir / "skipped.json"

    # ---- draft ----------------------------------------------------------------------------------
    def starter(self):
        """A mechanical starting point from the brief. Claude rewrites it from the memo in the style of the existing pages."""
        brief = self.run.brief()
        idea = brief.get("idea") or {}
        icp = brief.get("icp") or {}
        rules = brief.get("tier_rules") or {}
        who = []
        for t, label in (("T1", "A)"), ("T2", "B)")):
            if rules.get(t):
                who.append("%s %s" % (label, rules[t]))
        return {"Idea": idea.get("name", ""), "Campaign prefix": idea.get("campaign_prefix") or idea.get("name", ""),
                "Calendly (Jay)": "", "Calendly (Meelan)": "",
                "Pitch": idea.get("one_liner", ""),
                "Who we're targeting": "\n".join(who) or icp.get("summary", ""),
                "Idea specifics": "Early stage, we are building it and want advisors to shape it. Offer is an advisor role; the ask is a call with Jay and Meelan."}

    def fields(self):
        return read_json(self.fields_path, None)

    def set_fields(self, fields):
        errs, warns = self.validate(fields)
        if errs:
            raise IdeaPageError("fields rejected: " + "; ".join(errs))
        write_json(self.fields_path, fields)
        return warns

    # ---- validation -------------------------------------------------------------------------------
    def validate(self, f):
        errs, warns = [], []
        if not isinstance(f, dict):
            return ["fields must be an object"], []
        for k in REQUIRED:
            if not str(f.get(k) or "").strip():
                errs.append("%s is empty" % k)
        extra = set(f) - set(REQUIRED) - set(OPTIONAL)
        if extra:
            errs.append("unknown properties: %s (database has %s)" % (", ".join(sorted(extra)), ", ".join(icfg().get("properties", []))))
        mx = int(icfg().get("max_property_chars", 2000))
        for k, v in f.items():
            v = str(v or "")
            if len(v) > mx:
                errs.append("%s is %d chars, limit %d" % (k, len(v), mx))
            if copyrules.EM in v or copyrules.EN in v:
                errs.append("%s contains an em or en dash" % k)
            for m in re.finditer(copyrules.CURRENCY, v.lower()):
                around = v.lower()[max(0, m.start() - 40): m.end() + 40]
                if re.search(copyrules.FUND_WORDS, around):
                    errs.append("%s gives a funding amount or investor detail; the reply agent must never state those" % k)
                    break
        for k in OPTIONAL:
            v = str(f.get(k) or "").strip()
            if not v:
                warns.append("%s is empty: the reply agent cannot offer that founder's booking link" % k)
            elif not CALENDLY_RE.match(v):
                errs.append("%s must be a https://calendly.com/... link" % k)
        if re.search(r"bliss\s?growth", json.dumps(f), re.I) and not re.search(r"Blissgrowth", json.dumps(f)):
            errs.append("spell Blissgrowth exactly")
        pre = str(f.get("Campaign prefix") or "").strip()
        need = str(config.get("launch.prefix_must_start_with", "bliss") or "")
        if pre and need and not pre.lower().startswith(need.lower()):
            errs.append("Campaign prefix must start with '%s': the reply agent ignores campaigns whose name does not (n8n node Match Idea)" % need)
        if str(f.get("Campaign prefix") or "") and " " in str(f.get("Campaign prefix")):
            warns.append("Campaign prefix has a space; campaign names must START with it exactly")
        return errs, warns

    def fields_hash(self):
        return hashlib.sha256(json.dumps(self.fields() or {}, sort_keys=True).encode()).hexdigest()[:16]

    # ---- confirmation -------------------------------------------------------------------------------
    def confirm(self, note, simulated=False):
        f = self.fields()
        if not f:
            raise IdeaPageError("no fields.json yet: draft the fields first and show them to the user")
        errs, _ = self.validate(f)
        if errs:
            raise IdeaPageError("fields have errors: " + "; ".join(errs))
        if not note:
            raise IdeaPageError("--note is required: who confirmed the text")
        c = {"confirmed_at": now_iso(), "by": getpass.getuser(), "note": note, "simulated": bool(simulated),
             "fields_hash": self.fields_hash()}
        write_json(self.confirm_path, c)
        return c

    def confirmed(self):
        c = read_json(self.confirm_path, None)
        return bool(c) and c.get("fields_hash") == self.fields_hash()

    # ---- MCP payload and record -----------------------------------------------------------------------
    def record(self):
        return read_json(self.record_path, None)

    def payload(self, test=False):
        """Exact arguments for the Notion MCP tool notion-create-pages. Refused when a page was already recorded, or the text
        has not been confirmed by the user. test=True renames the page and prefix so it cannot be mistaken for a real idea."""
        if self.record():
            raise IdeaPageError("an idea page is already recorded for this run (%s). Never create it twice." % self.record().get("page_url"))
        if not self.confirmed():
            raise IdeaPageError("the text is not confirmed (or changed after confirming). Show it to the user and run confirm.")
        f = dict(self.fields())
        if test:
            f["Idea"] = "TEST DELETE ME - " + f["Idea"]
            f["Campaign prefix"] = "TEST-DELETE-ME-" + re.sub(r"\W+", "", f["Campaign prefix"])
        props = {k: v for k, v in f.items() if str(v or "").strip()}
        return {"tool": "mcp__claude_ai_Notion__notion-create-pages",
                "arguments": {"parent": {"type": "data_source_id", "data_source_id": icfg()["data_source"].replace("collection://", "")},
                              "pages": [{"properties": props}]},
                "before": "Query for an existing page first: notion-query-data-sources, mode rows, data_source_url %s, filter property "
                          "'Campaign prefix' (text) string_is '%s'. If a page exists, run record --adopt <url> instead of creating." % (
                              icfg()["data_source"], f["Campaign prefix"])}

    def save_record(self, page_url, page_id="", test=False, existing=False, simulated=False):
        if self.record():
            raise IdeaPageError("already recorded: %s" % self.record().get("page_url"))
        if not page_url.startswith("http"):
            raise IdeaPageError("page_url must be the Notion page link")
        r = {"page_url": page_url, "page_id": page_id or page_id_from_url(page_url),
             "recorded_at": now_iso(), "by": getpass.getuser(), "test": bool(test), "existing": bool(existing),
             "simulated": bool(simulated), "prefix": (self.fields() or {}).get("Campaign prefix"),
             "sync_note": "n8n HRA Ideas is filled by the workflow 'HeyReach Reply Agent | 4. Idea Sync'; see README, 'Reply-agent idea page'."}
        write_json(self.record_path, r)
        return r

    def skip(self, note):
        if not note:
            raise IdeaPageError("--note is required")
        write_json(self.skip_path, {"skipped_at": now_iso(), "note": note, "by": getpass.getuser()})

    # ---- n8n sync check (read only) -----------------------------------------------------------------------
    def sync_status(self, fetch_rows=None):
        """Is this idea's page in the n8n table HRA Ideas? Read only. fetch_rows lets tests inject rows."""
        r = self.record()
        if not r:
            return {"synced": None, "note": "no page recorded yet"}
        if fetch_rows is None:
            import n8n
            st, d = n8n.api("GET", "/data-tables/%s/rows?limit=250" % icfg()["n8n_ideas_table_id"])
            if st != 200:
                raise IdeaPageError("could not read the HRA Ideas table (%s)" % st)
            rows = d.get("data", [])
            wf = None
            try:
                wf = n8n.get_workflow(icfg()["n8n_sync_workflow_id"])
            except Exception:
                pass
        else:
            rows, wf = fetch_rows(), None
        pid = (r.get("page_id") or "").replace("-", "")
        hit = [x for x in rows if (x.get("notion_page_id") or "").replace("-", "") == pid]
        return {"synced": bool(hit), "rows_in_table": len(rows), "prefixes": sorted(x.get("campaign_prefix") or "" for x in rows),
                "sync_workflow_active": (wf or {}).get("active") if wf else None,
                "how_to_sync": "Run the workflow 'HeyReach Reply Agent | 4. Idea Sync' once by hand in n8n (Execute workflow), or activate it "
                               "(it then runs every 15 minutes). Check again with idea_page.py sync-check."}
