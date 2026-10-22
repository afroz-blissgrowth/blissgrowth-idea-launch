"""Pilot gates: a small human-reviewed pilot BEFORE the money is spent at scale.

Why (call findings, CHANGES-PROPOSAL-2026-10-21): the real pain is a wrong ICP, and "the first 10, 20 subset needs to be
reviewed properly". So the engine stops twice and waits for a person:

  ACCOUNTS gate  pull a pilot of 10 to 20 accounts (config pilot.accounts_size, default 15) -> enrich company signals ->
                 qualify them -> STOP. The user marks every pilot account approve or reject (+ optional note) in the
                 sheet ("2 Accounts" columns pilot, pilot_review, pilot_note) or in chat. Claude summarises the patterns
                 in the rejections and proposes brief, signal or prompt adjustments. Only after the user's EXPLICIT
                 approval does the full account pull run. Approved pilot accounts become seeds (column is_seed) for
                 future lookalike expansion. A human decision beats the AI: a rejected account is flagged drop (rows are
                 never deleted), an approved account the AI dropped is put back to keep.
  PEOPLE gate    after /iv-people and /iv-tier: a pilot of 10 to 20 people (config pilot.people_size) is reviewed by hand
                 BEFORE any enrichment credit is spent. Same columns on "4 People". Rejected pilot people are never enriched.

State machine (derived from files, like every stage; nothing is a hidden flag). Per gate, in the run folder `pilot/`:
  <kind>.json                the pilot: ids, size, when, how it was chosen
  <kind>.review.jsonl        append-only review decisions {id, review, note, source: sheet|chat, simulated, at}; last wins
  <kind>.review-requested.json   written by `request-review` (sheet columns pushed, the user was asked)
  <kind>.approval.json       the explicit approval {approved_at, note, simulated, review_sha, counts}
  <kind>.skipped.json        the user chose to skip the gate (a recorded decision)
  seeds.csv                  approved pilot accounts (seeds for lookalikes)
States: not_started -> selected -> (accounts: enriched ->) scored -> awaiting_review -> reviewed -> approved
        | skipped | stale (a review changed after the approval) | legacy (the work was already done before the gates existed)
An approval is bound to a hash of the review decisions: change a mark after approving and the gate is open again.
`--simulated` labels reviews and approvals nobody gave (tests): allowed on a TEST brief only, a real run refuses to treat it as done.
"""
from __future__ import annotations

import hashlib
import json
import random

import brief as briefmod
import config
import schema
from util import (append_jsonl, now_iso, read_csv, read_json, read_jsonl, write_csv, write_json)

ACCOUNTS, PEOPLE = "accounts", "people"
KINDS = (ACCOUNTS, PEOPLE)


class PilotError(RuntimeError):
    pass


def _brief(run):
    """The run's brief, or {} when it is missing or unreadable (a gate must never crash the status display)."""
    try:
        return run.brief()
    except Exception:
        return {}


# ---- pure helpers --------------------------------------------------------------------------------
def norm_review(text):
    """'Approved', 'y', 'keep' -> 'approve'; 'No', 'reject', 'drop' -> 'reject'; blank -> ''; anything else -> None
    (invalid, the caller reports it). Words come from config pilot.approve_words / reject_words."""
    t = " ".join(str(text or "").strip().lower().split())
    if not t:
        return ""
    if t in [w.lower() for w in config.get("pilot.approve_words", [])]:
        return "approve"
    if t in [w.lower() for w in config.get("pilot.reject_words", [])]:
        return "reject"
    return None


def check_size(size):
    lo, hi = config.get("pilot.min_size", 10), config.get("pilot.max_size", 20)
    if isinstance(size, bool) or not isinstance(size, int) or not lo <= size <= hi:
        raise PilotError("pilot size must be a whole number from %d to %d (got %r)" % (lo, hi, size))
    return size


def default_size(brief, kind):
    k = "accounts_size" if kind == ACCOUNTS else "people_size"
    return int(((brief or {}).get("pilot") or {}).get(k) or config.get("pilot." + k, 15))


def gate_enabled(brief):
    """The gate applies unless config pilot.enabled is false or the brief says pilot.enabled false."""
    if not config.get("pilot.enabled", True):
        return False
    return ((brief or {}).get("pilot") or {}).get("enabled", True) is not False


def review_hash(ids, reviews):
    rows = [(i, (reviews.get(i) or {}).get("review", "")) for i in sorted(ids)]
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:12]


def pick_people(rows, size, seed):
    """Choose `size` selected people for the pilot: spread over companies first, then keep the T1 / T2 mix of the whole
    list. Deterministic for a seed. rows: dicts with person_id, org_id, tier. Returns person ids."""
    rng = random.Random(seed)
    pool = sorted(rows, key=lambda r: r["person_id"])
    rng.shuffle(pool)
    total = len(pool)
    share = {}
    for r in pool:
        t = r.get("tier") or "T2"
        share[t] = share.get(t, 0) + 1.0 / total
    chosen, orgs, tiers = [], set(), {}
    for k in range(min(size, total)):
        best, best_score = None, None
        for r in pool:
            if r in chosen:
                continue
            t = r.get("tier") or "T2"
            score = (2 if r["org_id"] not in orgs else 0) + (share[t] * (k + 1) - tiers.get(t, 0))
            if best is None or score > best_score:
                best, best_score = r, score
        chosen.append(best)
        orgs.add(best["org_id"])
        t = best.get("tier") or "T2"
        tiers[t] = tiers.get(t, 0) + 1
    return [r["person_id"] for r in chosen]


# ---- the gate ------------------------------------------------------------------------------------
class Gate:
    def __init__(self, run, kind):
        if kind not in KINDS:
            raise PilotError("gate must be accounts or people")
        self.run, self.kind = run, kind
        self.dir = run.dir / "pilot"
        self.dir.mkdir(exist_ok=True)
        k = kind
        self.sel_path = self.dir / (k + ".json")
        self.review_path = self.dir / (k + ".review.jsonl")
        self.requested_path = self.dir / (k + ".review-requested.json")
        self.approval_path = self.dir / (k + ".approval.json")
        self.skipped_path = self.dir / (k + ".skipped.json")
        self.id_col = "org_id" if kind == ACCOUNTS else "person_id"
        self.tab = schema.TAB_ACCOUNTS if kind == ACCOUNTS else schema.TAB_PEOPLE

    # -- files
    def selection(self):
        return read_json(self.sel_path, None)

    def ids(self):
        s = self.selection()
        return list(s["ids"]) if s else []

    def reviews(self):
        out = {}
        for r in read_jsonl(self.review_path):
            if r.get("id"):
                out[r["id"]] = r
        return out

    def approval(self):
        return read_json(self.approval_path, None)

    def skipped(self):
        return read_json(self.skipped_path, None)

    def is_test(self):
        return bool((_brief(self.run).get("idea") or {}).get("test"))

    # -- review
    def counts(self):
        ids, rv = self.ids(), self.reviews()
        c = {"size": len(ids), "approve": 0, "reject": 0, "pending": 0}
        for i in ids:
            r = (rv.get(i) or {}).get("review", "")
            c[r if r in ("approve", "reject") else "pending"] += 1
        return c

    def record(self, ident, review, note="", source="chat", simulated=False):
        """Record one decision (last wins). review: approve | reject | '' (clears). Returns True when it changed."""
        if ident not in set(self.ids()):
            raise PilotError("%s is not in the %s pilot" % (ident, self.kind))
        r = norm_review(review)
        if r is None:
            raise PilotError("review must be approve or reject (got %r)" % review)
        cur = self.reviews().get(ident) or {}
        if cur.get("review", "") == r and (note or "") == cur.get("note", "") and bool(cur.get("simulated")) == bool(simulated):
            return False
        if simulated and not self.is_test():
            raise PilotError("a simulated review is only allowed on a TEST run")
        append_jsonl(self.review_path, {"id": ident, "review": r, "note": note or "", "source": source,
                                        "simulated": bool(simulated), "at": now_iso()})
        return True

    def merge_sheet_rows(self, records):
        """records: sheet rows (dicts) of the tab. Takes pilot_review and pilot_note of pilot rows (pilot == yes) from the
        sheet. A blank sheet cell never erases a decision made in chat. Returns {changed, invalid:[ids]}."""
        ids = set(self.ids())
        changed, invalid = 0, []
        for r in records:
            i = str(r.get(self.id_col, ""))
            if i not in ids:
                continue
            raw = r.get("pilot_review", "")
            norm = norm_review(raw)
            if norm is None:
                invalid.append(i)
                continue
            if norm == "":
                continue
            cur = self.reviews().get(i) or {}
            note = str(r.get("pilot_note", "") or "") or cur.get("note", "")
            if self.record(i, norm, note, source="sheet"):
                changed += 1
        return {"changed": changed, "invalid": invalid}

    def pull_from_sheet(self, sc=None):
        """Read the tab through the bridge and merge the reviews. No-op without a sheet."""
        sid = self.run.sheet_id()
        if not sid:
            return {"changed": 0, "invalid": [], "note": "no sheet"}
        import sheet as sheetmod
        sc = sc or sheetmod.SheetClient()
        return self.merge_sheet_rows(sc.read_records(sid, self.tab))

    # -- approval
    def approval_valid(self):
        a = self.approval()
        return bool(a) and a.get("review_sha") == review_hash(self.ids(), self.reviews()) and a.get("size") == len(self.ids())

    def approve(self, note, simulated=False):
        """The user's explicit approval. Refuses while any pilot row has no decision."""
        if not self.selection():
            raise PilotError("no %s pilot yet" % self.kind)
        if not (note or "").strip():
            raise PilotError("--note is required: record what the user said when approving")
        if simulated and not self.is_test():
            raise PilotError("a simulated approval is only allowed on a TEST run")
        c = self.counts()
        if c["pending"]:
            raise PilotError("%d of %d pilot rows have no approve or reject yet. Every row needs a decision." % (c["pending"], c["size"]))
        sim_rows = any(r.get("simulated") for i, r in self.reviews().items() if i in set(self.ids()))
        a = {"approved_at": now_iso(), "note": note, "simulated": bool(simulated or sim_rows), "counts": c,
             "size": c["size"], "review_sha": review_hash(self.ids(), self.reviews())}
        a.update(self.spec_snapshot())
        write_json(self.approval_path, a)
        self.after_approval(a)
        return a

    def skip(self, note):
        if not (note or "").strip():
            raise PilotError("--note is required: say why the %s pilot gate is skipped (a user decision)" % self.kind)
        write_json(self.skipped_path, {"skipped_at": now_iso(), "note": note})

    def spec_snapshot(self):
        b = _brief(self.run)
        if self.kind == ACCOUNTS:
            blob = json.dumps({"signals": b.get("signals"), "qualify": b.get("qualify")}, sort_keys=True)
        else:
            blob = json.dumps(b.get("tier_rules"), sort_keys=True)
        return {"spec_sha": hashlib.sha1(blob.encode()).hexdigest()[:10]}

    def after_approval(self, a):
        if self.kind == ACCOUNTS:
            write_seeds(self.run, a)

    def requested(self):
        return read_json(self.requested_path, None)

    def mark_requested(self, extra=None):
        d = {"requested_at": now_iso(), "ids": len(self.ids())}
        d.update(extra or {})
        write_json(self.requested_path, d)


# ---- accounts ------------------------------------------------------------------------------------
def account_ids(run):
    return Gate(run, ACCOUNTS).ids()


def _accounts_ledger(run):
    return read_json(run.ledger_path, None)


def accounts_legacy(run):
    """True when the accounts were pulled before the gate existed (a started full pull, or accounts.csv without a ledger
    at all) and no pilot was ever selected: the gate does not apply, there is nothing to review before."""
    g = Gate(run, ACCOUNTS)
    if g.selection():
        return False
    led = _accounts_ledger(run)
    if led:
        return not led.get("limit")
    return run.accounts_csv.exists()


def scope_ids(run):
    """While the accounts pilot is open (drawn, not yet approved or skipped) qualify works on the pilot accounts ONLY, so
    nothing outside the pilot is scored before the user's review. Returns a set of org ids, or None (no restriction)."""
    g = Gate(run, ACCOUNTS)
    if not g.selection():
        return None
    if accounts_state(run)["state"] in ("approved", "skipped", "legacy"):
        return None
    return set(g.ids())


def seeds(run):
    """{org_id: 'yes' | 'yes (SIMULATED)'} for approved pilot accounts, only while the approval is valid."""
    g = Gate(run, ACCOUNTS)
    a = g.approval()
    if not a or not g.approval_valid():
        return {}
    tag = "yes (SIMULATED)" if a.get("simulated") else "yes"
    return {i: tag for i, r in g.reviews().items() if i in set(g.ids()) and r.get("review") == "approve"}


def write_seeds(run, approval=None):
    """pilot/seeds.csv: the approved pilot accounts (seeds for lookalike expansion). Returns the rows."""
    s = seeds(run)
    rows = []
    for r in read_csv(run.accounts_csv):
        if r["org_id"] in s:
            rows.append({"org_id": r["org_id"], "domain": r["domain"], "name": r["name"], "is_seed": s[r["org_id"]],
                         "approved_at": (approval or Gate(run, ACCOUNTS).approval() or {}).get("approved_at", "")})
    write_csv(run.dir / "pilot" / "seeds.csv", rows, ["org_id", "domain", "name", "is_seed", "approved_at"])
    return rows


def account_overrides(run):
    """Human decisions on pilot accounts, applied by qualify.finalize: {org_id: {review, note, simulated}}."""
    g = Gate(run, ACCOUNTS)
    ids = set(g.ids())
    return {i: r for i, r in g.reviews().items() if i in ids and r.get("review") in ("approve", "reject")}


def apply_override(flag, ov, reason):
    """(flag, qualified, reason) after a human review. reject -> drop. approve -> an AI drop becomes keep (the human
    decides fit); dead and parked sites, errors and keep/review stay as they are."""
    if not ov:
        return flag, None, reason
    note = (" (%s)" % ov["note"]) if ov.get("note") else ""
    tag = "SIMULATED " if ov.get("simulated") else ""
    if ov["review"] == "reject":
        return schema.FLAG_DROP, False, ("pilot review %srejected%s" % (tag, note) + ("; AI: " + reason if reason else ""))[:240]
    if flag == schema.FLAG_DROP:
        return schema.FLAG_KEEP, True, ("pilot review %sapproved%s; AI had dropped: %s" % (tag, note, reason))[:240]
    return flag, None, reason


def accounts_state(run):
    """Derived state of the accounts gate: {state, detail, ...}."""
    g = Gate(run, ACCOUNTS)
    brief = _brief(run)
    if g.skipped():
        return {"state": "skipped", "detail": "accounts pilot skipped by the user (%s)" % g.skipped().get("note", "")}
    if not gate_enabled(brief):
        return {"state": "skipped", "detail": "pilot gate disabled (config pilot.enabled or brief.pilot.enabled false)"}
    if accounts_legacy(run):
        return {"state": "legacy", "detail": "accounts were pulled before the pilot gate existed, gate not applicable"}
    sel = g.selection()
    if not sel:
        return {"state": "not_started", "detail": "no pilot yet"}
    ids = set(g.ids())
    import signals as signalsmod
    if signalsmod.needs_apollo(brief):
        sg = signalsmod.Signals(run)
        rows = [r for r in read_csv(run.accounts_csv) if r["org_id"] in ids]
        c = sg.summary(rows)
        if c["pending"] or c["error"]:
            return {"state": "selected", "detail": "pilot of %d accounts pulled, signals not enriched yet (%d to do)"
                    % (len(ids), c["pending"] + c["error"])}
    res = {}
    for r in read_jsonl(run.qdir / "results.jsonl"):
        res[r.get("org_id")] = r
    scored = [i for i in ids if i in res and res[i].get("flag") != schema.FLAG_ERROR]
    if len(scored) < len(ids):
        return {"state": "enriched", "detail": "pilot of %d accounts pulled%s, %d of %d qualified" % (
            len(ids), " and enriched" if signalsmod.needs_apollo(brief) else "", len(scored), len(ids))}
    return _review_state(g, "accounts", len(ids))


def _review_state(g, label, n):
    c = g.counts()
    if g.approval() and g.approval_valid():
        a = g.approval()
        if a.get("simulated") and not g.is_test():
            return {"state": "simulated", "detail": "%s pilot approval is SIMULATED, a real user must approve" % label, "counts": c}
        return {"state": "approved", "detail": "%s pilot approved (%d approve, %d reject)%s" % (
            label, c["approve"], c["reject"], " SIMULATED" if a.get("simulated") else ""), "counts": c}
    if g.approval():
        return {"state": "stale", "detail": "%s pilot review changed after the approval, approve again" % label, "counts": c}
    if not g.requested():
        return {"state": "scored", "detail": "%s pilot ready, review not requested yet" % label, "counts": c}
    if c["pending"]:
        return {"state": "awaiting_review", "detail": "%s pilot waiting for the user's review (%d of %d marked)" % (
            label, c["size"] - c["pending"], c["size"]), "counts": c}
    return {"state": "reviewed", "detail": "%s pilot fully reviewed (%d approve, %d reject), waiting for the explicit approval" % (
        label, c["approve"], c["reject"]), "counts": c}


# ---- people --------------------------------------------------------------------------------------
def people_legacy(run):
    """Enrichment already happened before the people gate existed (nothing to gate any more)."""
    g = Gate(run, PEOPLE)
    if g.selection():
        return False
    import people as peoplemod
    return bool(read_jsonl(peoplemod.Files(run).enrich_results))


def people_state(run):
    g = Gate(run, PEOPLE)
    brief = _brief(run)
    if g.skipped():
        return {"state": "skipped", "detail": "people pilot skipped by the user (%s)" % g.skipped().get("note", "")}
    if not gate_enabled(brief):
        return {"state": "skipped", "detail": "pilot gate disabled (config pilot.enabled or brief.pilot.enabled false)"}
    if people_legacy(run):
        return {"state": "legacy", "detail": "people were enriched before the pilot gate existed, gate not applicable"}
    if not g.selection():
        return {"state": "not_started", "detail": "no people pilot yet"}
    return _review_state(g, "people", len(g.ids()))


def people_view(run):
    """{person_id: {pilot, pilot_review, pilot_note, simulated}} for people.build_rows (derived, so a rebuild keeps it)."""
    g = Gate(run, PEOPLE)
    ids = set(g.ids())
    rv = g.reviews()
    return {i: {"pilot": "yes", "pilot_review": (rv.get(i) or {}).get("review", ""), "pilot_note": (rv.get(i) or {}).get("note", "")}
            for i in ids}


def start_people(run, brief, size=None, seed=None):
    import people as peoplemod
    g = Gate(run, PEOPLE)
    if g.selection():
        raise PilotError("a people pilot already exists (%d people). It is never re-drawn." % len(g.ids()))
    size = check_size(size or default_size(brief, PEOPLE))
    rows = [r for r in peoplemod.rebuild(run, brief) if r["cap_status"] == schema.CAP_SELECTED]
    if not rows:
        raise PilotError("nobody is selected yet (finish /iv-people and /iv-tier first)")
    ids = pick_people(rows, size, seed or run.dir.name)
    write_json(g.sel_path, {"ids": ids, "size": len(ids), "requested_size": size, "created_at": now_iso(),
                            "how": "spread over companies, T1/T2 mix of the whole list, seeded random"})
    return ids


# ---- accounts: start -----------------------------------------------------------------------------
def start_accounts(run, brief, size=None, from_existing=False, client=None, push=True, seed=None):
    """Select (and, unless from_existing, pull from Apollo) the account pilot. Returns the org ids."""
    import accounts
    g = Gate(run, ACCOUNTS)
    if g.selection():
        raise PilotError("an accounts pilot already exists (%d accounts). It is never re-drawn." % len(g.ids()))
    size = check_size(size or default_size(brief, ACCOUNTS))
    led = _accounts_ledger(run)
    if from_existing:
        rows = [r for r in read_csv(run.accounts_csv) if r.get("domain")]
        if len(rows) < size:
            raise PilotError("only %d accounts with a domain exist, need %d" % (len(rows), size))
        rng = random.Random(seed or run.dir.name)
        rng.shuffle(rows)
        ids = [r["org_id"] for r in rows[:size]]
        how = "sampled from the accounts already pulled (no Apollo call)"
    else:
        if led and not led.get("limit"):
            raise PilotError("a full account pull already exists; use --from-existing to draw a pilot from it")
        accounts.execute(run, brief, limit=size, push=push, client=client)
        rows = read_csv(run.accounts_csv)
        ids = [r["org_id"] for r in rows[:size]]
        how = "first %d companies of a limit pull spread over the filter sets" % size
    write_json(g.sel_path, {"ids": ids, "size": len(ids), "requested_size": size, "created_at": now_iso(), "how": how,
                            "brief_sha": briefmod.sha(brief)})
    return ids


# ---- sheet sync and review request ---------------------------------------------------------------
def sync_accounts_sheet(run, sc=None):
    """Push pilot, pilot_review, pilot_note and is_seed of the pilot accounts to '2 Accounts' (add_columns first). Blank
    review cells are not sent, so a mark the user typed in the sheet is never overwritten."""
    import sheet as sheetmod
    sid = run.sheet_id()
    if not sid:
        return {"pushed": 0, "note": "no sheet for this run"}
    sc = sc or sheetmod.SheetClient()
    g = Gate(run, ACCOUNTS)
    sc.add_columns(sid, schema.TAB_ACCOUNTS, schema.ACCOUNT_COLS)
    rv, sd = g.reviews(), seeds(run)
    recs = []
    for i in g.ids():
        rec = {"org_id": i, "pilot": "yes"}
        r = rv.get(i)
        if r and r.get("review"):
            rec["pilot_review"] = r["review"]
            if r.get("note"):
                rec["pilot_note"] = r["note"]
        if i in sd:
            rec["is_seed"] = sd[i]
        recs.append(rec)
    up = sc.upsert(sid, schema.TAB_ACCOUNTS, "org_id", recs) if recs else {}
    return {"pushed": len(recs), "unknown_columns": (up or {}).get("unknown_columns", [])}


def request_review(run, kind, sc=None, push=True):
    """Make the pilot reviewable: finalize qualify (accounts) or rebuild people, push the pilot columns, remember that the
    user was asked. Returns a report. Does NOT approve anything."""
    g = Gate(run, kind)
    if not g.selection():
        raise PilotError("no %s pilot yet" % kind)
    rep = {}
    if kind == ACCOUNTS:
        import qualify as qmod
        rep["qualify"] = qmod.Qualify(run).finalize(push=push and bool(run.sheet_id()))
        if push and run.sheet_id():
            rep["sheet"] = sync_accounts_sheet(run, sc)
    else:
        import people as peoplemod
        rows, srep = peoplemod.sync(run, push=push and bool(run.sheet_id()), sc=sc)
        rep["sheet"] = srep
    g.mark_requested({"sheet": bool(push and run.sheet_id())})
    return rep


# ---- summaries (for Claude to read and explain) --------------------------------------------------
def _stat(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    return {"n": len(vals), "min": vals[0], "median": vals[len(vals) // 2], "max": vals[-1]}


def accounts_summary(run):
    """Pilot accounts with AI verdict, signal values and the human mark, plus the patterns: agreement between the AI and
    the human, signal ranges of approved versus rejected, the notes of the rejections."""
    import signals as signalsmod
    g = Gate(run, ACCOUNTS)
    ids = g.ids()
    rv = g.reviews()
    by = {r["org_id"]: r for r in read_csv(run.accounts_csv)}
    res = {}
    for r in read_jsonl(run.qdir / "results.jsonl"):
        res[r.get("org_id")] = r
    sg = signalsmod.Signals(run)
    recs = sg.records()
    brief = run.brief()
    rows = []
    for i in ids:
        a = by.get(i, {})
        x = res.get(i, {})
        vals = sg.values(a, recs)
        ev = signalsmod.evaluate(brief.get("signals"), recs.get(a.get("domain") or ""))
        rows.append({"org_id": i, "name": a.get("name", ""), "domain": a.get("domain", ""), "country": a.get("country", ""),
                     "ai_flag": x.get("flag", ""), "ai_confidence": x.get("confidence", ""), "ai_reason": x.get("reason", ""),
                     "employees": vals["employees"], "engineering": vals.get("engineering", ""),
                     "operations": vals.get("operations", ""), "sales": vals.get("sales", ""),
                     "signals": [e["detail"] for e in ev if e["result"] in ("fail", "unknown")],
                     "review": (rv.get(i) or {}).get("review", ""), "note": (rv.get(i) or {}).get("note", "")})
    agree = {"ai_keep_human_approve": 0, "ai_keep_human_reject": 0, "ai_drop_human_approve": 0, "ai_drop_human_reject": 0}
    for r in rows:
        if r["review"] not in ("approve", "reject"):
            continue
        ai = "keep" if r["ai_flag"] in schema.POOL_FLAGS else "drop"
        agree["ai_%s_human_%s" % (ai, r["review"])] += 1
    stats = {}
    for f in ("employees", "engineering", "operations", "sales"):
        for grp in ("approve", "reject"):
            s = _stat([r[f] for r in rows if r["review"] == grp and r[f] != ""])
            if s:
                stats.setdefault(f, {})[grp] = s
    rej = [r for r in rows if r["review"] == "reject"]
    return {"pilot_size": len(ids), "counts": g.counts(), "agreement": agree, "signal_ranges_by_review": stats,
            "rejected": [{k: r[k] for k in ("name", "domain", "ai_flag", "ai_reason", "employees", "engineering", "operations", "sales", "note")}
                         for r in rej],
            "rows": rows}


def format_accounts_summary(s):
    L = ["Accounts pilot: %(size)d accounts, %(approve)d approved, %(reject)d rejected, %(pending)d not marked" % s["counts"], ""]
    a = s["agreement"]
    L.append("AI versus human: AI keep + approved %d, AI keep + REJECTED %d (AI too loose), AI drop + APPROVED %d (AI too strict), "
             "AI drop + rejected %d" % (a["ai_keep_human_approve"], a["ai_keep_human_reject"], a["ai_drop_human_approve"],
                                         a["ai_drop_human_reject"]))
    for f, d in s["signal_ranges_by_review"].items():
        L.append("  %s: approved %s | rejected %s" % (f, d.get("approve"), d.get("reject")))
    L += ["", "Rejected accounts (what to learn from):"]
    for r in s["rejected"]:
        L.append("  - %s (%s): AI %s, employees %s, eng %s, ops %s, sales %s. Note: %s" % (
            r["name"], r["domain"], r["ai_flag"], r["employees"], r["engineering"], r["operations"], r["sales"], r["note"] or "(none)"))
    return "\n".join(L)


def people_summary(run):
    import people as peoplemod
    g = Gate(run, PEOPLE)
    ids = set(g.ids())
    rv = g.reviews()
    rows = [r for r in peoplemod.load_table(run) if r["person_id"] in ids]
    out = []
    by_tier = {}
    for r in rows:
        rev = (rv.get(r["person_id"]) or {}).get("review", "")
        out.append({"person_id": r["person_id"], "company": r["company"], "title": r["title"], "tier": r["tier"],
                    "tier_reason": r["tier_reason"], "review": rev, "note": (rv.get(r["person_id"]) or {}).get("note", "")})
        d = by_tier.setdefault(r["tier"] or "?", {"approve": 0, "reject": 0})
        if rev in d:
            d[rev] += 1
    return {"counts": g.counts(), "by_tier": by_tier, "rows": out,
            "rejected": [o for o in out if o["review"] == "reject"]}


def format_people_summary(s):
    L = ["People pilot: %(size)d people, %(approve)d approved, %(reject)d rejected, %(pending)d not marked" % s["counts"], ""]
    for t, d in sorted(s["by_tier"].items()):
        L.append("  tier %s: approved %d, rejected %d" % (t, d["approve"], d["reject"]))
    L += ["", "Rejected people (what to learn from):"]
    for r in s["rejected"]:
        L.append("  - %s, %s (tier %s: %s). Note: %s" % (r["company"], r["title"], r["tier"], r["tier_reason"], r["note"] or "(none)"))
    return "\n".join(L)


# ---- stage statuses and the orchestrator's next action ------------------------------------------
def stage_status(run, kind):
    """{status, detail} for the stage registry (pending | partial | done | skipped)."""
    st = accounts_state(run) if kind == ACCOUNTS else people_state(run)
    s = st["state"]
    status = {"skipped": "skipped", "legacy": "done", "approved": "done", "not_started": "pending"}.get(s, "partial")
    return {"status": status, "detail": st["detail"], "state": s}


def next_action(run, kind):
    """What the orchestrator does at this gate: {state, kind: auto|claude|user|done, instruction, cmds}. cmds are
    (script, args...) tuples run with python3 -I from bin/."""
    r = run.dir.name
    st = accounts_state(run) if kind == ACCOUNTS else people_state(run)
    s = st["state"]
    done = {"state": s, "kind": "done", "instruction": st["detail"], "cmds": []}
    if s in ("skipped", "legacy", "approved"):
        return done
    if kind == ACCOUNTS:
        if s == "not_started":
            return {"state": s, "kind": "auto", "cmds": [("pilot_run.py", "accounts", "start", r)],
                    "instruction": "pull the account pilot (a small Apollo pull)"}
        if s == "selected":
            return {"state": s, "kind": "auto", "cmds": [("signals_run.py", "run", r, "--scope", "pilot")],
                    "instruction": "enrich the pilot accounts with company signals (1 credit per company)"}
        if s == "enriched":
            return {"state": s, "kind": "claude", "cmds": [],
                    "instruction": "Qualify the pilot with /iv-qualify (tune the prompt on samples of 10 with the user, score the pilot, finalize), "
                                   "then run /iv-run again. This is the pilot only, the full pull has not happened."}
    else:
        if s == "not_started":
            return {"state": s, "kind": "auto", "cmds": [("pilot_run.py", "people", "start", r)],
                    "instruction": "draw the people pilot (no credits)"}
    if s == "scored":
        return {"state": s, "kind": "auto", "cmds": [("pilot_run.py", kind, "request-review", r)],
                "instruction": "push the pilot columns to the sheet and ask for the review"}
    if s == "awaiting_review":
        return {"state": s, "kind": "user", "cmds": [],
                "instruction": ("STOP, human review: the user marks each pilot %s approve or reject (and a note) in the sheet's %s tab "
                                "(columns pilot_review, pilot_note) or tells Claude in chat (pilot_run.py %s record). Then run "
                                "pilot_run.py %s pull-review, show `summary`, propose adjustments." % (
                                    "account" if kind == ACCOUNTS else "person", g_tab(kind), kind, kind))}
    if s in ("reviewed", "stale", "simulated"):
        return {"state": s, "kind": "user", "cmds": [],
                "instruction": "STOP, the user must approve explicitly: show `pilot_run.py %s summary`, propose brief/signal/prompt adjustments "
                               "from the rejections, and only after the user says go run `pilot_run.py %s approve --note \"...\"`%s." % (
                                   kind, kind, " (a real user, not simulated)" if s == "simulated" else "")}
    return {"state": s, "kind": "user", "cmds": [], "instruction": st["detail"]}


def g_tab(kind):
    return schema.TAB_ACCOUNTS if kind == ACCOUNTS else schema.TAB_PEOPLE


def gate_open_for_full_pull(run):
    """True when the full account pull may run: approved, skipped, disabled, or legacy."""
    return accounts_state(run)["state"] in ("approved", "skipped", "legacy")


def gate_open_for_enrich(run):
    return people_state(run)["state"] in ("approved", "skipped", "legacy")
