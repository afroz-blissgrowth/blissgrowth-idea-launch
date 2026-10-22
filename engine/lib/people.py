"""Phase 2 core: the People table, Apollo people search per company, caps, channels, sheet push.

One row per Apollo person id lives in `people.csv` (run folder). It is REBUILT from append-only stage
artifacts every time a stage finishes (the same pattern as stage status: files are the truth), so a
crash never loses work and every stage can resume:

  people/search.stream.jsonl    people found by Apollo search (one record per person, per company searched)
  people/search.ledger.jsonl    one record per company searched (found | none | error); last wins; resume source
  people/search.meta.json       the query hash; a changed query needs --accept-query-change
  tier/results.jsonl            Claude tier decisions (T1 | T2 | X) with a reason
  enrich/enrich.jsonl           Apollo bulk_match results (name, LinkedIn URL, email)
  verify/mv.jsonl               MillionVerifier results, cached per email
  activity/cache.jsonl          LinkedIn activity per profile URL (cache)
  phones/phones.jsonl           phone reveal requests and results
  people.csv                    the merged table (columns: schema.PEOPLE_COLS + LOCAL_COLS)
  people/pushed.json            row hashes already pushed to the sheet (push only what changed)

Search design (decision, documented in README):
  * ONE company per call (Apollo returns no org id per person), filtered by organization_ids (domain as a
    fallback), with all T1 and T2 titles in the same call, so the call count equals the company count.
  * Search is free (0 credits) but limited to 200 per minute and 6,000 per hour on this key. The per-org ledger
    makes the run resumable; the client stops cleanly when the hourly budget is nearly used.

Cap design (decision):
  * Caps (T1 5, T2 3; brief.people.caps overrides config.people_caps, see brief.people_caps) are applied
    AFTER tiering. Before tiering, title priority only limits the TIERING POOL (the best
    `people.tier_pool_per_company` people per company by the order of the titles in the brief: all T1 titles
    first, then T2 titles, earlier in each list is better). Inside a tier the same title priority picks who
    stays under the cap, so the best-titled people are kept and the rest become `over_cap` (rows are never deleted).
  * If the user skips tiering (tier/skipped.json), the tier is unknown: the top (T1 cap + T2 cap) people by title
    priority are selected, tier stays blank and they get the T2 channels (LinkedIn + email, no call).
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import brief as briefmod
import config
import exclusions as exclusionsmod
import schema
from util import (append_jsonl, atomic_write, norm_domain, now_iso, read_csv, read_json, read_jsonl, write_csv,
                  write_json)

LOCAL_COLS = ["last_name_obf", "apollo_has_email", "apollo_has_phone", "title_hint", "mv_checked_at"]
TABLE_COLS = schema.PEOPLE_COLS + LOCAL_COLS


class PeopleError(RuntimeError):
    pass


class Files:
    """Every Phase 2 path in one place."""

    def __init__(self, run):
        d = run.dir
        self.run = run
        self.people = d / "people"
        self.stream = self.people / "search.stream.jsonl"
        self.ledger = self.people / "search.ledger.jsonl"
        self.meta = self.people / "search.meta.json"
        self.pushed = self.people / "pushed.json"
        self.table = d / "people.csv"
        self.tier = d / "tier"
        self.tier_results = self.tier / "results.jsonl"
        self.tier_skipped = self.tier / "skipped.json"
        self.enrich = d / "enrich"
        self.enrich_results = self.enrich / "enrich.jsonl"
        self.verify = d / "verify"
        self.mv = self.verify / "mv.jsonl"
        self.quality = d / "list-quality.md"
        self.quality_json = self.verify / "quality.json"
        self.activity = d / "activity"
        self.activity_cache = self.activity / "cache.jsonl"
        self.activity_state = self.activity / "state.json"
        self.activity_skipped = self.activity / "skipped.json"
        self.phones = d / "phones"
        self.phones_log = self.phones / "phones.jsonl"
        self.phones_skipped = self.phones / "skipped.json"
        self.ready = d / "ready"
        self.ready_meta = self.ready / "built.json"
        for p in (self.people, self.tier, self.enrich, self.verify, self.activity, self.phones, self.ready):
            p.mkdir(exist_ok=True)


# ---- titles ------------------------------------------------------------------------------------
def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (t or "").lower())).strip()


def title_lists(brief):
    ppl = brief.get("people") or {}
    return list((ppl.get("T1") or {}).get("titles") or []), list((ppl.get("T2") or {}).get("titles") or [])


def title_rank(title, brief):
    """Lower is better. Exact match on a T1 title 0,2,4..., word-boundary match 1,3,5...; T2 titles start at 100;
    no match 1000. Order inside each list in the brief is the priority order."""
    t = _norm(title)
    t1, t2 = title_lists(brief)
    best = 1000
    for base, lst in ((0, t1), (100, t2)):
        for i, x in enumerate(lst):
            n = _norm(x)
            if not n or not t:
                continue
            if t == n:
                best = min(best, base + i * 2)
            elif re.search(r"\b" + re.escape(n) + r"\b", t):
                best = min(best, base + i * 2 + 1)
    return best


def rank_of(v):
    """title_rank from a row (int or csv string). Rank 0 is the BEST rank, so never use `or 1000` on it."""
    return 1000 if v in (None, "") else int(v)


def title_hint(rank):
    return schema.TIER_T1 if rank < 100 else (schema.TIER_T2 if rank < 1000 else "")


def search_query(brief):
    """The one query used for every company: all T1 and T2 titles in a single call."""
    t1, t2 = title_lists(brief)
    seen, titles = set(), []
    for t in t1 + t2:
        if t.lower() not in seen:
            seen.add(t.lower())
            titles.append(t)
    ppl = brief.get("people") or {}
    sens = []
    if config.get("people.seniority_filter", "union") == "union":
        for k in ("T1", "T2"):
            sens += list((ppl.get(k) or {}).get("seniorities") or [])
    sens = sorted(set(sens))
    # Apollo ANDs titles with seniorities, so the union is used (a seniority list that only fits T1 would hide T2)
    q = {"titles": titles, "seniorities": sens, "include_similar_titles": bool(ppl.get("include_similar_titles", True))}
    q["sha"] = hashlib.sha1(json.dumps(q, sort_keys=True).encode()).hexdigest()[:10]
    return q


# ---- the pool of companies ---------------------------------------------------------------------
def pool_accounts(run):
    """Qualified companies (keep + review) from qualify/qualified.csv. Raises if qualify was not finalized."""
    rows = read_csv(run.qdir / "qualified.csv")
    if not rows:
        raise PeopleError("qualify/qualified.csv is missing. Run qualify_run.py finalize first.")
    return [r for r in rows if r.get("flag") in schema.POOL_FLAGS and r.get("org_id")]


# ---- ledger ------------------------------------------------------------------------------------
def ledger(run):
    out = {}
    for r in read_jsonl(Files(run).ledger):
        out[r.get("org_id")] = r
    return out


def _phone_hint(v):
    """Apollo search's has_direct_phone: "Yes", "Maybe: please request direct dial via people/bulk_match" (seen live),
    or false/missing. False becomes "no" so phones.skip_if_apollo_says_no can act on it; missing stays blank."""
    if v is False or str(v).strip().lower() in ("no", "false"):
        return "no"
    return "" if v is None else str(v)


def person_record(p, org, brief, added_at):
    pid = p.get("id") or ""
    rank = title_rank(p.get("title"), brief)
    return {"person_id": pid, "org_id": org["org_id"], "domain": org.get("domain", ""), "company": org.get("name", ""),
            "first_name": p.get("first_name") or "", "last_name_obf": p.get("last_name_obfuscated") or "",
            "title": p.get("title") or "", "title_rank": rank, "title_hint": title_hint(rank),
            "apollo_has_email": "yes" if p.get("has_email") else "no",
            "apollo_has_phone": _phone_hint(p.get("has_direct_phone")), "country": org.get("country", ""),
            "source": "apollo_search", "added_at": added_at}


def search_org(client, org, query, brief, per_page=None, max_pages=None):
    """All people Apollo finds at one company for the T1+T2 query. Returns (records, total_entries, truncated)."""
    per_page = per_page or config.get("people.per_page", 100)
    max_pages = max_pages or config.get("people.max_pages_per_org", 3)
    got, total, page = [], 0, 1
    added_at = now_iso()
    while page <= max_pages:
        kw = {"org_ids": [org["org_id"]]} if org.get("org_id") else {"domains": [org["domain"]]}
        res = client.people_page(query["titles"], seniorities=query["seniorities"],
                                 include_similar_titles=query["include_similar_titles"], page=page,
                                 per_page=per_page, **kw)
        total = res["total_entries"]
        got += [person_record(p, org, brief, added_at) for p in res["people"] if p.get("id")]
        if len(res["people"]) < per_page or len(got) >= total:
            break
        page += 1
    return got, total, total > len(got)


def run_search(run, brief, client, limit_orgs=None, accept_query_change=False, progress=print, max_consecutive_errors=5):
    """Search every pool company not yet in the ledger. Resumable. Returns a report dict.
    limit_orgs: only search this many NEW companies (test runs)."""
    f = Files(run)
    q = search_query(brief)
    meta = read_json(f.meta, None)
    if meta and meta.get("query_sha") != q["sha"] and ledger(run):
        if not accept_query_change:
            raise PeopleError("the T1/T2 titles or seniorities changed since people were searched. Re-run with "
                              "--accept-query-change to archive the old search and start again.")
        stamp = now_iso().replace(":", "")
        for p in (f.stream, f.ledger):
            if p.exists():
                p.rename(p.with_name(p.name + ".old-" + stamp))
    write_json(f.meta, {"query_sha": q["sha"], "titles": q["titles"], "seniorities": q["seniorities"],
                        "include_similar_titles": q["include_similar_titles"], "updated_at": now_iso()})
    pool = pool_accounts(run)
    done = ledger(run)
    seen_people = {r.get("person_id") for r in read_jsonl(f.stream)}
    todo = [o for o in pool if done.get(o["org_id"], {}).get("status") not in ("found", "none")]
    if limit_orgs:
        todo = todo[:limit_orgs]
    rep = {"pool": len(pool), "already_done": len(pool) - len([o for o in pool if done.get(o["org_id"], {}).get("status") not in ("found", "none")]),
           "searched": 0, "found": 0, "none": 0, "errors": 0, "people": 0, "truncated_orgs": 0, "paused": "",
           "duplicates_skipped": 0}
    consecutive = 0
    import apollo
    for i, org in enumerate(todo):
        if client.hour_budget_low():
            rep["paused"] = ("hourly Apollo request budget nearly used (%s left). Nothing is lost: re-run the same "
                             "command in about an hour." % client.limits.get("hour_left"))
            break
        client.label = "people:" + (org.get("domain") or org["org_id"])
        try:
            recs, total, trunc = search_org(client, org, q, brief)
        except apollo.ApolloError as e:
            rep["errors"] += 1
            consecutive += 1
            append_jsonl(f.ledger, {"org_id": org["org_id"], "domain": org.get("domain", ""), "name": org.get("name", ""),
                                    "status": "error", "found": 0, "error": str(e)[:200], "searched_at": now_iso(),
                                    "query_sha": q["sha"]})
            if e.status in (401, 402, 403, 422) or consecutive >= max_consecutive_errors:
                rep["paused"] = "stopped after repeated or fatal Apollo errors: %s" % e
                break
            continue
        consecutive = 0
        new = []
        for r in recs:
            if r["person_id"] in seen_people:
                rep["duplicates_skipped"] += 1
                continue
            seen_people.add(r["person_id"])
            new.append(r)
        for r in new:
            append_jsonl(f.stream, r)  # stream first, ledger second: a crash in between only repeats this company
        status = "found" if recs else "none"
        append_jsonl(f.ledger, {"org_id": org["org_id"], "domain": org.get("domain", ""), "name": org.get("name", ""),
                                "status": status, "found": len(recs), "total_entries": total, "truncated": trunc,
                                "searched_at": now_iso(), "query_sha": q["sha"]})
        rep["searched"] += 1
        rep[status] += 1
        rep["people"] += len(new)
        rep["truncated_orgs"] += 1 if trunc else 0
        if progress and (i + 1) % 25 == 0:
            progress("  searched %d of %d companies, %d people so far (minute budget left %s, hour %s)"
                     % (i + 1, len(todo), rep["people"], client.limits.get("minute_left"), client.limits.get("hour_left")))
    return rep


# ---- caps (pure, tested) -----------------------------------------------------------------------
def apply_caps(rows, caps, tiers, tier_skipped=False, pool_size=None):
    """Return {person_id: cap_status}. rows: dicts with person_id, org_id, title_rank. tiers: {pid: 'T1'|'T2'|'X'}."""
    pool_size = pool_size if pool_size is not None else config.get("people.tier_pool_per_company", 10)
    by_org = {}
    for r in rows:
        by_org.setdefault(r["org_id"], []).append(r)
    out = {}
    for members in by_org.values():
        members.sort(key=lambda r: (rank_of(r.get("title_rank")), r["person_id"]))
        used = {schema.TIER_T1: 0, schema.TIER_T2: 0}
        left_untiered = caps["T1"] + caps["T2"]
        for i, r in enumerate(members):
            pid = r["person_id"]
            if i >= pool_size:
                out[pid] = schema.CAP_OVER
            elif tier_skipped:
                if left_untiered > 0:
                    out[pid] = schema.CAP_SELECTED
                    left_untiered -= 1
                else:
                    out[pid] = schema.CAP_OVER
            else:
                t = tiers.get(pid)
                if t is None:
                    out[pid] = schema.CAP_CANDIDATE
                elif t == schema.TIER_X:
                    out[pid] = schema.CAP_NOT_TIERED
                elif t in used and used[t] < caps[t]:
                    used[t] += 1
                    out[pid] = schema.CAP_SELECTED
                else:
                    out[pid] = schema.CAP_OVER
    return out


# ---- email verdict and channels (pure, tested) -------------------------------------------------
def email_verdict(email, mv, vcfg=None):
    """Return (verdict, waterfall_needed). verdict: valid | catch_all | role | invalid | unknown | error | missing |
    unverified. Only MillionVerifier 'ok' passes. waterfall_needed names why another source/verifier is needed."""
    vcfg = vcfg or config.get("verify", {})
    if not email:
        return "missing", "email_missing"
    if not mv:
        return "unverified", ""
    res = (mv.get("result") or "").lower()
    local = email.split("@")[0].lower()
    if res in vcfg.get("pass_results", ["ok"]):
        if local in set(vcfg.get("role_local_parts", [])) and vcfg.get("exclude_role_addresses", True):
            return "role", "email_role_address"
        return "valid", ""
    if res in vcfg.get("catch_all_results", ["catch_all"]):
        return "catch_all", "catch_all_secondary_verify"
    if res in ("invalid", "disposable"):
        return "invalid", "email_invalid"
    if res == "unknown":
        return "unknown", "email_unknown"
    return "error", ""


def linkedin_active_value(person, activity_rec, acfg=None):
    """yes | no | unknown | '' (not checked yet)."""
    acfg = acfg or config.get("activity", {})
    if not person.get("linkedin_url"):
        return ""
    if not activity_rec:
        return ""
    st = (activity_rec.get("activity_status") or "").strip()
    if st in acfg.get("active_values", ["Active"]):
        return "yes"
    if st in acfg.get("inactive_values", ["Inactive", "Shell"]):
        return "no"
    return "unknown"


def channels_for(p, activity_skipped=False):
    """Channel list for one person row (dict with the table columns). T1: LinkedIn + email + call. T2 (and unknown
    tier after a skipped tiering): LinkedIn + email. Inactive or unverified LinkedIn drops LinkedIn; no valid email
    drops email; call needs a phone."""
    if p.get("cap_status") != schema.CAP_SELECTED:
        return []
    if p.get("exclusion_reason"):  # not in a current job (or rejected in the pilot review): no channel, the row stays
        return []
    tier = p.get("tier") or schema.TIER_T2
    ch = []
    li_ok = p.get("linkedin_active") == "yes" or (activity_skipped and p.get("linkedin_url"))
    unknown_ok = config.get("activity.unknown_policy", "exclude") == "include" and p.get("linkedin_active") == "unknown"
    if p.get("linkedin_url") and (li_ok or unknown_ok):
        ch.append("linkedin")
    if p.get("email_verdict") == "valid":
        ch.append("email")
    if tier == schema.TIER_T1 and p.get("phone"):
        ch.append("call")
    return ch


# ---- merged table ------------------------------------------------------------------------------
def _last_by(records, key):
    out = {}
    for r in records:
        k = r.get(key)
        if k not in (None, ""):
            out[k] = r
    return out


def norm_url(u):
    u = (u or "").strip().lower().split("?")[0].rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u


def profile_key(u):
    """Cache key of a LinkedIn profile, the same one activity.py writes (linkedin.com/in/<slug>, extra path parts such
    as /en or /details dropped), so a URL with a suffix still finds its activity answer."""
    k = norm_url(u)
    m = re.match(r"linkedin\.com/in/([^/]+)", k)
    return "linkedin.com/in/%s" % m.group(1) if m else k


def dedupe_selected(rows):
    """After enrichment, two selected rows can be the same human (same LinkedIn URL or same email, for example a
    person listed under two Apollo ids). Keep the better-ranked row, mark the others `duplicate`. In place."""
    seen = {}
    for r in sorted((x for x in rows if x["cap_status"] == schema.CAP_SELECTED),
                    key=lambda x: (rank_of(x["title_rank"]), x["person_id"])):
        keys = [k for k in ("li:" + norm_url(r["linkedin_url"]) if r["linkedin_url"] else "",
                            "em:" + r["email"].lower() if r["email"] else "") if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit:
            r["cap_status"] = schema.CAP_DUP
            r["tier_reason"] = (r["tier_reason"] + " | " if r["tier_reason"] else "") + "duplicate of " + hit
        else:
            for k in keys:
                seen[k] = r["person_id"]


def build_rows(run, brief):
    """Merge every artifact into table rows (list of dicts keyed by TABLE_COLS). Pure read."""
    f = Files(run)
    base = _last_by(read_jsonl(f.stream), "person_id")
    tiers = {pid: r for pid, r in _last_by(read_jsonl(f.tier_results), "person_id").items()}
    enr = _last_by(read_jsonl(f.enrich_results), "person_id")
    mv = _last_by(read_jsonl(f.mv), "email")
    act = _last_by(read_jsonl(f.activity_cache), "linkedin_key")
    ph = _last_by(read_jsonl(f.phones_log), "person_id")
    skipped_tier = f.tier_skipped.exists()
    skipped_act = f.activity_skipped.exists()
    import pilot as pilotmod
    pv = pilotmod.people_view(run)
    caps = briefmod.people_caps(brief)
    tier_map = {pid: r["tier"] for pid, r in tiers.items() if r.get("tier") in schema.TIERS and pid in base}
    cap = apply_caps(list(base.values()), caps, tier_map, skipped_tier)
    rows = []
    for pid, b in base.items():
        r = {c: "" for c in TABLE_COLS}
        r.update({k: b.get(k, "") for k in ("person_id", "org_id", "domain", "company", "first_name", "title",
                                              "title_rank", "country", "source", "added_at", "last_name_obf",
                                              "apollo_has_email", "apollo_has_phone", "title_hint")})
        t = tiers.get(pid)
        if t and pid in tier_map:
            r["tier"], r["tier_reason"] = t["tier"], t.get("reason", "")
        r["cap_status"] = cap[pid]
        e = enr.get(pid)
        if e:
            for k in ("first_name", "last_name", "seniority", "linkedin_url", "email", "email_status"):
                if e.get(k):
                    r[k] = e[k]
            if e.get("title"):
                r["title"] = e["title"]
            if e.get("country") and not r["country"]:
                r["country"] = e["country"]
            r["enrich_status"] = e.get("status", "")
            r["email_source"] = "apollo" if r["email"] else ""
        m = mv.get((r["email"] or "").lower()) if r["email"] else None
        if m:
            r["mv_result"], r["mv_subresult"], r["mv_checked_at"] = m.get("result", ""), m.get("subresult", ""), m.get("checked_at", "")
        if r["enrich_status"] in ("matched", "no_match"):
            r["email_verdict"], r["waterfall_needed"] = email_verdict(r["email"], m)
        a = (act.get(profile_key(r["linkedin_url"])) or act.get(norm_url(r["linkedin_url"]))) if r["linkedin_url"] else None
        if pv.get(pid):
            r.update(pv[pid])
        ex = exclusionsmod.evaluate(r, e, a)
        r["exclusion_reason"] = ex["reason"]
        if pv.get(pid, {}).get("pilot_review") == "reject":
            note = pv[pid].get("pilot_note", "")
            r["exclusion_reason"] = "; ".join(x for x in (r["exclusion_reason"], "%s: pilot review rejected%s" % (
                exclusionsmod.PILOT_REJECTED, (" (%s)" % note) if note else "")) if x)
        if r["linkedin_url"] and a:
            r["activity_status"] = a.get("activity_status", "")
            r["linkedin_checked_at"] = a.get("checked_at", "")
        r["linkedin_active"] = linkedin_active_value(r, a)
        p = ph.get(pid)
        if p:
            r["phone"], r["phone_status"], r["phone_source"] = p.get("phone", ""), p.get("status", ""), p.get("source", "")
        rows.append(r)
    dedupe_selected(rows)
    for r in rows:
        r["channels"] = "+".join(channels_for(r, skipped_act))
    rows.sort(key=lambda r: (r["company"].lower(), rank_of(r["title_rank"]), r["person_id"]))
    return rows


def rebuild(run, brief=None):
    """Rebuild people.csv from the artifacts (writes only when the content changed, so mtime means 'changed')."""
    brief = brief or run.brief()
    f = Files(run)
    rows = build_rows(run, brief)
    import io
    import csv
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TABLE_COLS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in TABLE_COLS})
    text = buf.getvalue()
    try:
        same = f.table.read_text(encoding="utf-8") == text
    except FileNotFoundError:
        same = False
    if not same:
        atomic_write(f.table, text)
    return rows


def load_table(run):
    return read_csv(Files(run).table)


def counts(rows):
    c = {"people": len(rows), "by_cap": {}, "by_tier": {}, "channels": {"linkedin": 0, "email": 0, "call": 0}}
    for r in rows:
        c["by_cap"][r["cap_status"]] = c["by_cap"].get(r["cap_status"], 0) + 1
        if r.get("tier"):
            c["by_tier"][r["tier"]] = c["by_tier"].get(r["tier"], 0) + 1
        for ch in (r.get("channels") or "").split("+"):
            if ch in c["channels"]:
                c["channels"][ch] += 1
    return c


def log_exclusions(run, rows):
    """Run Log line for the employment exclusions (only when there are some and the number changed since the last line)."""
    c = exclusionsmod.category_counts(rows)
    if not c["total"]:
        return None
    last = [x for x in read_jsonl(run.runlog) if x.get("stage") == "exclusions"]
    if last and json.loads(last[-1].get("counts") or "{}") == c:
        return None
    detail = "%d people excluded (channel none, rows kept): %s" % (
        c["total"], ", ".join("%s %d" % kv for kv in sorted(c.items()) if kv[0] != "total"))
    return run.log("exclusions", "applied", detail, c)


# ---- No People rows ----------------------------------------------------------------------------
def no_people_rows(run):
    out = []
    for oid, r in ledger(run).items():
        if r.get("status") == "none":
            out.append({"org_id": oid, "domain": r.get("domain", ""), "name": r.get("name", ""),
                        "reason": "no_people_found: Apollo has no one with the T1/T2 titles at this company",
                        "checked_at": r.get("searched_at", "")})
        elif r.get("status") == "error":
            out.append({"org_id": oid, "domain": r.get("domain", ""), "name": r.get("name", ""),
                        "reason": "search_error: %s (will be retried on the next run)" % r.get("error", ""),
                        "checked_at": r.get("searched_at", "")})
    return out


# ---- sheet push --------------------------------------------------------------------------------
def _row_hash(rec):
    return hashlib.sha1(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:12]


def push_to_sheet(run, rows, sc=None, include_no_people=True, force=False):
    """Upsert the People tab (only rows that changed since the last push) and the No People tab. Migrates the
    sheet's columns first. Returns a report."""
    import sheet as sheetmod
    sid = run.sheet_id()
    if not sid:
        raise PeopleError("no sheet for this run yet (run /iv-brief first)")
    sc = sc or sheetmod.SheetClient()
    f = Files(run)
    added = sc.ensure_schema(sid)
    pushed = {} if force else read_json(f.pushed, {}) or {}
    recs, hashes = [], {}
    for r in rows:
        rec = {c: r.get(c, "") for c in schema.PEOPLE_COLS}
        h = _row_hash(rec)
        hashes[r["person_id"]] = h
        if pushed.get(r["person_id"]) != h:
            # a blank pilot review is not sent: the user may have typed a mark in the sheet that is not pulled yet
            for k in ("pilot_review", "pilot_note"):
                if not rec.get(k):
                    rec.pop(k, None)
            recs.append(rec)
    rep = {"schema_columns_added": added, "people_pushed": 0, "no_people_pushed": 0}
    if recs:
        up = sc.upsert(sid, schema.TAB_PEOPLE, "person_id", recs)
        rep["people_pushed"] = up["updated"] + up["appended"]
        rep["people_unknown_columns"] = up["unknown_columns"]
        pushed.update({rec["person_id"]: hashes[rec["person_id"]] for rec in recs})
        write_json(f.pushed, pushed)
    if include_no_people:
        npr = no_people_rows(run)
        if npr:
            sc.upsert(sid, schema.TAB_NO_PEOPLE, "org_id", npr)
            rep["no_people_pushed"] = len(npr)
    return rep


def sync(run, brief=None, push=True, sc=None):
    """Rebuild the table and (optionally) push it. The standard last step of every Phase 2 command."""
    rows = rebuild(run, brief)
    rep = None
    if push and run.sheet_id():
        rep = push_to_sheet(run, rows, sc=sc)
    return rows, rep
