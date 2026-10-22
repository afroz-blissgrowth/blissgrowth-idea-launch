"""Stage 9: channel assignment and the three Ready tabs.

Channels per person (people.channels_for, computed into people.csv column `channels`):
  T1  LinkedIn + email + call      T2  LinkedIn + email        (tier unknown after skipped tiering: as T2)
  minus: LinkedIn when the profile is not Active (Inactive, Shell, unknown), email when the address is not a
         MillionVerifier `ok`, call when there is no phone. Only selected (capped, non-duplicate) people qualify.
Tabs (rows are upserted by person_id and never deleted; a person who later stops qualifying gets status `withdrawn`):
  5 Ready: LinkedIn   people with the linkedin channel
  6 Ready: Email      people with the email channel (verdict valid)
  7 Ready: Calls      T1 people with a phone, laid out for the cold caller (Mansi): name, title, company, phone,
                      LinkedIn, email, idea, notes
Local copies: ready/linkedin.csv, ready/email.csv, ready/calls.csv. Also writes the list quality report
(lib/quality.py) and ready/built.json, which is what marks the stage done.
"""
from __future__ import annotations

import hashlib
import json

import people as peoplemod
import quality
import schema
from util import now_iso, read_json, write_csv, write_json


def _has(r, ch):
    return ch in (r.get("channels") or "").split("+")


def records(rows, idea_name=""):
    """Return {tab: [records]} for the three tabs (pure)."""
    li, em, calls = [], [], []
    for r in rows:
        base = {"person_id": r["person_id"], "tier": r["tier"] or "T2", "first_name": r["first_name"],
                "last_name": r["last_name"], "title": r["title"], "company": r["company"], "country": r["country"],
                "domain": r["domain"], "linkedin_url": r["linkedin_url"], "email": r["email"], "status": "ready"}
        if _has(r, "linkedin"):
            li.append(dict(base, linkedin_active=r["linkedin_active"]))
        if _has(r, "email"):
            em.append(dict(base, email_verdict=r["email_verdict"]))
        if _has(r, "call"):
            notes = "; ".join(x for x in (r["tier_reason"], "also reachable by: " + r["channels"].replace("+", ", ")) if x)
            calls.append(dict(base, phone=r["phone"], idea=idea_name, call_notes=notes))
    return {schema.TAB_READY_LI: li, schema.TAB_READY_EMAIL: em, schema.TAB_READY_CALLS: calls}


def _h(rec):
    return hashlib.sha1(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:12]


def build(run, push=True, sc=None):
    """Rebuild people, write local CSVs, push the three tabs (only changes), grade the list. Returns a report."""
    brief = run.brief()
    f = peoplemod.Files(run)
    rows = peoplemod.rebuild(run, brief)
    recs = records(rows, (brief.get("idea") or {}).get("name", ""))
    names = {schema.TAB_READY_LI: "linkedin", schema.TAB_READY_EMAIL: "email", schema.TAB_READY_CALLS: "calls"}
    for tab, items in recs.items():
        write_csv(f.ready / (names[tab] + ".csv"), items, schema.TABS[tab])
    rep = {"linkedin": len(recs[schema.TAB_READY_LI]), "email": len(recs[schema.TAB_READY_EMAIL]),
           "calls": len(recs[schema.TAB_READY_CALLS]), "withdrawn": 0, "sheet": None}
    q = quality.write_report(run, rows, brief)
    rep["grade"], rep["score"] = q["grade"], q["score"]
    if push and run.sheet_id():
        import sheet as sheetmod
        sc = sc or sheetmod.SheetClient()
        sid = run.sheet_id()
        sc.ensure_schema(sid)
        peoplemod.push_to_sheet(run, rows, sc=sc)
        pushed = read_json(f.ready / "pushed.json", {})
        rep["sheet"] = {}
        for tab, items in recs.items():
            prev = pushed.get(tab, {})
            now = {i["person_id"]: _h(i) for i in items}
            changed = [i for i in items if prev.get(i["person_id"]) != now[i["person_id"]]]
            gone = [{"person_id": pid, "status": "withdrawn"} for pid in prev if pid not in now and prev[pid] != "withdrawn"]
            send = changed + gone
            if send:
                sc.upsert(sid, tab, "person_id", send)
            rep["withdrawn"] += len(gone)
            rep["sheet"][tab] = {"upserted": len(send)}
            pushed[tab] = dict(now, **{g["person_id"]: "withdrawn" for g in gone})
        write_json(f.ready / "pushed.json", pushed)
    write_json(f.ready_meta, {"built_at": now_iso(), "linkedin": rep["linkedin"], "email": rep["email"],
                              "calls": rep["calls"], "grade": rep["grade"], "score": rep["score"]})
    return rep
