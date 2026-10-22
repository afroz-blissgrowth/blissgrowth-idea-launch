"""Stage 10: per-run copy (LinkedIn invite, LinkedIn follow-ups, InMail), checked, tuned with the user, approved.

Named copydraft (not copy) so it never shadows the stdlib `copy` module.

Who writes what: Claude drafts the copy (no model API key in the project) from the brief, the memo, the idea page text and the copy
library patterns, as strict JSON items; this module validates them with lib/copyrules.py, stores them append-only, shows samples, logs
tuning rounds, records the user's explicit approval and writes copy.json plus the "8 Copy" tab.

Item: {channel, tier, step, variant, subject, body, sender, fallback?, note?}
  channel  li_invite | li_followup | inmail
  tier     T1 | T2 | all        (a tier-specific item beats an `all` item for that tier)
  step     1 for invite and InMail, 1..N for follow-ups
  variant  V1 (the main version) then V2, V3, V4 (A/B variants; HeyReach rotates them), or `blank` (an invite with no note)
  sender   founder (Jay or Meelan, first person) | associate (a founder's office associate, InMail)
Slots needed (config.json `copy`): invite, follow-up steps 1..followup_steps, InMail (only for the tiers in launch.inmail_tiers),
each with variants_min to variants_max variants (V1 plus 2 to 3 variants), for every tier that has people in "5 Ready: LinkedIn".
Files in <run>/copy/: items.jsonl (append-only, last record per slot wins), tuning.json, approval.json, context.json.
Approval: record() writes approval.json tied to a hash of the current items. Changing any item afterwards makes the approval stale.
A SIMULATED approval (tests) is labelled and can never start a real launch.
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
from util import append_jsonl, atomic_write, now_iso, read_json, read_jsonl, write_json

CHANNELS = ("li_invite", "li_followup", "inmail")
TIERS = ("T1", "T2", "all")
SENDERS = ("founder", "associate")
VARIANT_RE = re.compile(r"^(V[1-9]|blank)$")


class CopyError(RuntimeError):
    pass


def copy_cfg():
    return config.get("copy", {}) or {}


class CopyDraft:
    def __init__(self, run):
        self.run = run
        self.dir = run.dir / "copy"
        self.items_path = self.dir / "items.jsonl"
        self.tuning_path = self.dir / "tuning.json"
        self.approval_path = self.dir / "approval.json"
        self.context_path = self.dir / "context.json"
        self.final_path = run.dir / "copy.json"
        self.pushed_path = self.dir / "pushed.json"

    # ---- context for the drafter -------------------------------------------------------------------
    def tiers_present(self):
        """Tiers that have people in the LinkedIn Ready list (the copy must cover each)."""
        p = self.run.dir / "ready" / "linkedin.csv"
        out = {}
        try:
            with open(p, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("status", "ready") == "ready":
                        out[r["tier"] or "T2"] = out.get(r["tier"] or "T2", 0) + 1
        except FileNotFoundError:
            pass
        return out

    def required_slots(self, tiers=None):
        """[(channel, tier_or_all, step)] that must have enough variants. A slot may be met by a tier item or an `all` item."""
        c = copy_cfg()
        tiers = sorted(tiers or self.tiers_present() or ["T1", "T2"])
        inmail_tiers = set(config.get("launch.inmail_tiers", ["T1"]))
        slots = []
        for t in tiers:
            slots.append(("li_invite", t, 1))
            for s in range(1, int(c.get("followup_steps", 3)) + 1):
                slots.append(("li_followup", t, s))
            if t in inmail_tiers:
                slots.append(("inmail", t, 1))
        return slots

    def context(self, write=True):
        brief = self.run.brief()
        idea = brief.get("idea") or {}
        idea_page = read_json(self.run.dir / "idea-page.json", {}) or {}
        ctx = {
            "idea": idea, "icp": brief.get("icp"), "tier_rules": brief.get("tier_rules"),
            "tiers_with_people": self.tiers_present(),
            "memo_file": str(self.run.dir / "memo.md"),
            "idea_page": idea_page.get("page_url"),
            "required_slots": ["%s|%s|%d" % s for s in self.required_slots()],
            "variants": {"min": copy_cfg().get("variants_min", 3), "max": copy_cfg().get("variants_max", 4)},
            "rules": {"never_names": sorted(copyrules.internal_names({"idea_name": idea.get("name"), "idea_slug": idea.get("slug")})),
                      "word_targets": copy_cfg().get("word_targets"), "limits": copyrules.LIMITS,
                      "placeholders": sorted(copyrules.ALLOWED_VARS)},
            "library": str(config.IDEA_LAUNCH_DIR / "copy-library" / "index.md"),
            "voices": copy_cfg().get("voices"),
            "frameworks": copy_cfg().get("frameworks"),
            "item_format": {"channel": "li_invite|li_followup|inmail", "tier": "T1|T2|all", "step": 1,
                            "variant": "V1|V2|V3|V4|blank", "subject": "InMail only", "body": "text",
                            "sender": "founder|associate", "fallback": "text without personalisation (needed when the body uses"
                            " {COMPANY} or {POSITION})", "note": "why this angle"},
        }
        if write:
            write_json(self.context_path, ctx)
        return ctx

    def check_ctx(self):
        idea = (self.run.brief().get("idea") or {})
        return {"idea_name": idea.get("name"), "idea_slug": idea.get("slug")}

    # ---- ingest ----------------------------------------------------------------------------------
    def validate_shape(self, it):
        errs = []
        if not isinstance(it, dict):
            return ["item is not an object"]
        if it.get("channel") not in CHANNELS:
            errs.append("channel must be one of %s" % ", ".join(CHANNELS))
        if it.get("tier") not in TIERS:
            errs.append("tier must be T1, T2 or all")
        try:
            if int(it.get("step")) < 1:
                errs.append("step must be 1 or more")
        except (TypeError, ValueError):
            errs.append("step must be an integer")
        if not VARIANT_RE.match(str(it.get("variant") or "")):
            errs.append("variant must be V1..V9 or blank")
        if it.get("sender") not in SENDERS:
            errs.append("sender must be founder or associate")
        if it.get("channel") == "inmail" and it.get("sender") != "associate":
            errs.append("an InMail is sent by an associate (a founder's office employee)")
        if it.get("channel") in ("li_invite", "li_followup") and it.get("sender") == "associate":
            errs.append("LinkedIn invites and follow-ups come from a founder")
        if it.get("channel") != "inmail" and it.get("subject"):
            errs.append("only an InMail has a subject")
        if not isinstance(it.get("body", ""), str):
            errs.append("body must be text")
        if it.get("channel") == "li_invite" and int(it.get("step") or 1) != 1:
            errs.append("an invite has step 1")
        return errs

    def ingest(self, path_or_items, round_label=""):
        """Validate items (strict: shape errors reject the item; rule errors store it as blocked so the user sees it).
        Returns {ok, blocked, rejected:[...]}."""
        items = path_or_items
        if isinstance(path_or_items, str):
            try:
                items = json.load(open(path_or_items, encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise CopyError("cannot read %s: %s" % (path_or_items, e))
        if not isinstance(items, list):
            raise CopyError("a draft file is one JSON array of items")
        ctx = self.check_ctx()
        rep = {"ok": 0, "blocked": 0, "rejected": []}
        for i, it in enumerate(items):
            shape = self.validate_shape(it)
            if shape:
                rep["rejected"].append({"index": i, "problems": shape})
                continue
            it = dict(it, step=int(it["step"]))
            res = copyrules.check(it, ctx)
            rec = dict(it, id=copyrules.item_id(it), errors=res["errors"], warnings=res["warnings"],
                       words=copyrules.word_count(it.get("body", "")),
                       status="ok" if not res["errors"] else "blocked", ingested_at=now_iso(), round=round_label)
            append_jsonl(self.items_path, rec)
            rep["ok" if rec["status"] == "ok" else "blocked"] += 1
        return rep

    def items(self):
        """Last record per slot id wins. A record with `withdrawn: true` removes it."""
        cur = {}
        for r in read_jsonl(self.items_path):
            cur[r["id"]] = r
        return [r for r in cur.values() if not r.get("withdrawn")]

    def withdraw(self, item_id):
        append_jsonl(self.items_path, {"id": item_id, "withdrawn": True, "ingested_at": now_iso()})

    def recheck(self):
        """Re-run the rules over stored items (after the rules or the brief changed)."""
        ctx = self.check_ctx()
        n = 0
        for r in self.items():
            res = copyrules.check(r, ctx)
            st = "ok" if not res["errors"] else "blocked"
            if st != r["status"] or res["errors"] != r["errors"] or res["warnings"] != r["warnings"]:
                append_jsonl(self.items_path, dict(r, errors=res["errors"], warnings=res["warnings"], status=st,
                                                   ingested_at=now_iso()))
                n += 1
        return n

    def items_hash(self):
        keep = sorted(({k: r.get(k) for k in ("id", "subject", "body", "fallback", "sender")} for r in self.items()),
                      key=lambda x: x["id"])
        return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]

    # ---- completeness ----------------------------------------------------------------------------
    def completeness(self):
        """{missing:[...], thin:[...], blocked:[...], ok: bool}. A slot is met by tier items, else by `all` items."""
        items = [r for r in self.items()]
        vmin, vmax = int(copy_cfg().get("variants_min", 3)), int(copy_cfg().get("variants_max", 4))
        missing, thin, blocked, toomany = [], [], [], []
        for ch, tier, step in self.required_slots():
            own = [r for r in items if r["channel"] == ch and r["tier"] == tier and r["step"] == step]
            pool = own or [r for r in items if r["channel"] == ch and r["tier"] == "all" and r["step"] == step]
            label = "%s %s step %d" % (ch, tier, step)
            if not pool:
                missing.append(label)
                continue
            if not any(r["variant"] in ("V1", "blank") for r in pool):
                missing.append(label + " (no V1)")
            if len(pool) < vmin:
                thin.append("%s has %d variants, need at least %d" % (label, len(pool), vmin))
            if len(pool) > vmax:
                toomany.append("%s has %d variants, at most %d" % (label, len(pool), vmax))
        for r in items:
            if r["status"] == "blocked":
                blocked.append("%s: %s" % (r["id"], "; ".join(e["rule"] for e in r["errors"])))
        return {"missing": missing, "thin": thin, "toomany": toomany, "blocked": blocked,
                "ok": not (missing or thin or toomany or blocked)}

    # ---- tuning and approval ---------------------------------------------------------------------
    def tuning(self):
        return read_json(self.tuning_path, {"rounds": []})

    def log_round(self, rnd, corrections, note="", simulated=False):
        t = self.tuning()
        t["rounds"] = [r for r in t["rounds"] if r["round"] != rnd]
        t["rounds"].append({"round": rnd, "corrections": corrections, "note": note, "simulated": bool(simulated),
                            "at": now_iso(), "items_hash": self.items_hash(), "by": getpass.getuser()})
        t["rounds"].sort(key=lambda r: r["round"])
        write_json(self.tuning_path, t)
        return corrections == 0

    def approval(self):
        return read_json(self.approval_path, None)

    def approve(self, note, simulated=False):
        """Explicit approval of the CURRENT items. Needs: complete and clean, and a tuning round with 0 corrections on exactly these
        items (the user saw them and had no changes). `simulated` labels an approval nobody gave (tests)."""
        comp = self.completeness()
        if not comp["ok"]:
            raise CopyError("copy is not ready for approval: " + "; ".join(
                (comp["missing"] + comp["thin"] + comp["toomany"] + comp["blocked"])[:6]))
        if not note:
            raise CopyError("--note is required: say who approved and what was approved")
        rounds = self.tuning()["rounds"]
        clean = [r for r in rounds if r["corrections"] == 0 and r["items_hash"] == self.items_hash()]
        if not clean:
            raise CopyError("no tuning round with 0 corrections was logged for exactly these items. Show the samples, ask the user, "
                            "run tune-log --corrections 0 (or fix and re-draft), then approve.")
        a = {"approved_at": now_iso(), "by": getpass.getuser(), "note": note, "simulated": bool(simulated),
             "items_hash": self.items_hash(), "rounds": len(rounds)}
        write_json(self.approval_path, a)
        return a

    def approval_valid(self):
        a = self.approval()
        return bool(a) and a.get("items_hash") == self.items_hash()

    # ---- output ----------------------------------------------------------------------------------
    def sheet_rows(self):
        a_ok = self.approval_valid()
        status = "approved" if a_ok else "draft"
        if a_ok and self.approval().get("simulated"):
            status = "approved (SIMULATED)"
        rows = []
        for r in sorted(self.items(), key=lambda x: (x["channel"], x["tier"], x["step"], x["variant"])):
            notes = r.get("note", "")
            if r["warnings"]:
                notes = (notes + " | " if notes else "") + "warnings: " + ", ".join(w["rule"] for w in r["warnings"])
            rows.append({"channel": r["channel"], "tier": r["tier"], "step": r["step"], "variant": r["variant"],
                         "subject": r.get("subject", ""), "body": r.get("body", ""), "status": status, "notes": notes,
                         "copy_id": r["id"], "sender": r.get("sender", ""), "words": r["words"]})
        return rows

    def write(self, push=True, sc=None):
        """copy.json (always) and the 8 Copy tab (upsert by copy_id; items withdrawn after a push become status `withdrawn`)."""
        rows = self.sheet_rows()
        a = self.approval() if self.approval_valid() else None
        final = {"written_at": now_iso(), "approved": bool(a), "approval": a, "simulated": bool(a and a.get("simulated")),
                 "items_hash": self.items_hash(), "tiers": self.tiers_present(), "items": [
                     {k: r.get(k) for k in ("id", "channel", "tier", "step", "variant", "subject", "body", "fallback",
                                            "sender", "note", "words", "warnings")} for r in self.items()]}
        write_json(self.final_path, final)
        rep = {"items": len(rows), "approved": bool(a), "sheet": None}
        if push and self.run.sheet_id():
            import sheet as sheetmod
            sc = sc or sheetmod.SheetClient()
            sid = self.run.sheet_id()
            sc.ensure_schema(sid, [schema.TAB_COPY])
            prev = read_json(self.pushed_path, {})
            now = {r["copy_id"]: hashlib.sha1(json.dumps(r, sort_keys=True).encode()).hexdigest()[:12] for r in rows}
            send = [r for r in rows if prev.get(r["copy_id"]) != now[r["copy_id"]]]
            gone = [{"copy_id": k, "status": "withdrawn"} for k, v in prev.items() if k not in now and v != "withdrawn"]
            if send or gone:
                sc.upsert(sid, schema.TAB_COPY, "copy_id", send + gone)
            write_json(self.pushed_path, dict(now, **{g["copy_id"]: "withdrawn" for g in gone}))
            rep["sheet"] = {"upserted": len(send), "withdrawn": len(gone)}
        return rep

    def render(self, sample=False, tier=None):
        """Markdown for the user: one block per slot, every variant, word counts and flags."""
        items = self.items()
        out = []
        order = {"li_invite": 0, "li_followup": 1, "inmail": 2}
        keys = sorted({(r["channel"], r["tier"], r["step"]) for r in items}, key=lambda k: (order[k[0]], k[1], k[2]))
        for ch, t, s in keys:
            if tier and t not in (tier, "all"):
                continue
            vs = sorted([r for r in items if (r["channel"], r["tier"], r["step"]) == (ch, t, s)], key=lambda r: r["variant"])
            if sample:
                vs = vs[:1]
            title = {"li_invite": "LinkedIn connection invite", "li_followup": "LinkedIn follow-up %d" % s,
                     "inmail": "InMail"}[ch]
            out.append("### %s | tier %s | sender %s" % (title, t, vs[0].get("sender")))
            for r in vs:
                out.append("")
                flag = "" if r["status"] == "ok" else "  BLOCKED: " + "; ".join(e["detail"] for e in r["errors"])
                out.append("**%s** (%d words)%s" % (r["variant"], r["words"], flag))
                if r.get("subject"):
                    out.append("Subject: %s" % r["subject"])
                out.append("")
                out.append("> " + (r.get("body") or "(blank invite, no note)").replace("\n", "\n> "))
                if r["warnings"]:
                    out.append("")
                    out.append("Warnings: " + "; ".join(w["detail"] for w in r["warnings"]))
            out.append("")
        return "\n".join(out)

    def status(self):
        comp = self.completeness()
        a = self.approval()
        return {"items": len(self.items()), "completeness": comp, "approved": self.approval_valid(),
                "approval": a, "stale_approval": bool(a) and not self.approval_valid(),
                "tuning_rounds": len(self.tuning()["rounds"]),
                "copy_json": self.final_path.exists()}
