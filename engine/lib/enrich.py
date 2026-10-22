"""Stage 6a: Apollo bulk_match for the CAPPED people only (credits), to get full name, LinkedIn URL and email.

Search returns an obfuscated last name and no LinkedIn URL or email (see people.py), so enrichment is mandatory,
not a fallback. Only people with cap_status `selected` are sent (T1 up to 5, T2 up to 3 per company by default),
10 per call. The real cost of every call is read from Apollo's `credits_consumed` and logged to
apollo-usage.jsonl. Results are appended to enrich/enrich.jsonl (last record per person wins); people already
matched are never sent again, so a re-run never pays twice. Dedupe by Apollo person id happens at search time;
duplicates by LinkedIn URL or email are found after enrichment (people.dedupe_selected).
"""
from __future__ import annotations

import apollo
import config
import people as peoplemod
import schema
from util import append_jsonl, now_iso


def todo_people(rows):
    """Selected people not yet enriched (matched or no_match). Errors are retried."""
    todo = [r for r in rows if r["cap_status"] == schema.CAP_SELECTED and r["enrich_status"] not in ("matched", "no_match")
            and not r.get("exclusion_reason")]  # a person rejected in the pilot review is never paid for
    todo.sort(key=lambda r: r["tier"] != schema.TIER_T1)  # T1 first (stable), so a --limit run covers the most valuable people
    return todo


def align_matches(chunk, matches):
    """Pair each requested person with its match. Apollo keeps unmatched entries as null but does not document that
    the array keeps input order, so a match is paired by Apollo person id first; a match whose id is not one of the
    requested ids (a merged record) falls back to its position. Never assigns one match to two people."""
    ids = [r["person_id"] for r in chunk]
    by_id = {m["person_id"]: m for m in matches if m and m.get("person_id") in ids}
    out = []
    for i, pid in enumerate(ids):
        m = by_id.get(pid)
        if m is None and i < len(matches):
            pos = matches[i]
            if pos and pos.get("person_id") not in ids:
                m = pos
        out.append(m)
    return out


def estimate(rows):
    n = len(todo_people(rows))
    return {"people": n, "calls": -(-n // config.get("apollo.bulk_match_batch", 10)),
            "credits_expected_max": n * config.get("apollo.credits_per_bulk_match_person", 1),
            "note": "1 credit per person with a revealed email; people without an email cost 0 to 1. Mobile phones are separate (8 credits, /iv-phones)."}


def run_enrich(run, client, limit=None, progress=print):
    """Enrich selected people in batches of 10. Returns a report. Stops on fatal Apollo errors."""
    f = peoplemod.Files(run)
    rows = peoplemod.rebuild(run)
    todo = todo_people(rows)
    if limit:
        todo = todo[:limit]
    size = config.get("apollo.bulk_match_batch", 10)
    rep = {"requested": 0, "matched": 0, "no_match": 0, "with_email": 0, "credits": 0.0, "calls": 0, "errors": 0,
           "paused": ""}
    for i in range(0, len(todo), size):
        if client.hour_budget_low():
            rep["paused"] = "hourly Apollo request budget nearly used; re-run later (nothing is paid twice)"
            break
        chunk = todo[i:i + size]
        details = [{"id": r["person_id"], "first_name": r["first_name"], "organization_name": r["company"],
                    "domain": r["domain"]} for r in chunk]
        client.label = "enrich"
        try:
            res = client.bulk_match(details)
        except apollo.ApolloError as e:
            rep["errors"] += 1
            rep["paused"] = "Apollo error, stopped: %s" % e
            if e.status in (401, 402, 403, 422) or rep["errors"] >= 3:
                break
            continue
        rep["calls"] += 1
        rep["credits"] += res["credits"]
        for r, m in zip(chunk, align_matches(chunk, res["matches"])):
            rep["requested"] += 1
            ok = bool(m and m.get("person_id"))
            rec = {"person_id": r["person_id"], "status": "matched" if ok else "no_match", "enriched_at": now_iso(),
                   "batch_credits": res["credits"], "batch_size": len(chunk)}
            if ok:
                rec.update({k: m.get(k, "") for k in ("first_name", "last_name", "title", "seniority", "linkedin_url",
                                                      "email", "email_status", "country", "match_confidence",
                                                      "headline", "employment_history")})
                rep["matched"] += 1
                rep["with_email"] += 1 if m.get("email") else 0
            else:
                rep["no_match"] += 1
            append_jsonl(f.enrich_results, rec)
        if progress:
            progress("  enriched %d of %d (credits so far %.1f)" % (min(i + size, len(todo)), len(todo), rep["credits"]))
    rep["credits"] = round(rep["credits"], 2)
    return rep
