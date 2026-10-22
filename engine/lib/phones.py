"""Stage 8: phone numbers for T1 people only, through Apollo's asynchronous phone reveal.

How it works (verified against Apollo's docs, 2026-10-21):
  1. people/bulk_match with reveal_phone_number=true and a webhook_url. The HTTP answer carries no numbers, only
     phone_enrichment {status: pending|skipped, request_id}. Cost: 8 credits per mobile found (nothing if none).
  2. Apollo POSTs the numbers some seconds or minutes later to our n8n receiver "Idea Launch | Apollo Phone Webhook"
     (workflows/deploy_phone_webhook.py), which stores one row per person in the n8n data table "IL Phone Results".
  3. This module polls that table through the n8n API (rows are keyed by person id) and writes phones/phones.jsonl.
Per-person state in phones.jsonl (last record wins): requested -> received | none | not_available. People already
requested or resolved are never sent again, so a re-run never pays twice; a request that did not arrive within the
timeout stays `requested` and the next run only polls it (re-request with --rerequest-stale after checking Apollo).
Apollo also offers `poll_only=true` plus GET /webhook_result/{request_id} (ApolloClient.webhook_result) as an
alternative that needs no receiver; the receiver is used because the plan asks for it and it also catches late results.
Prospeo and Amplemarket fallbacks are hooks only (waterfall.py). Only T1 people are ever sent.
"""
from __future__ import annotations

import json
import time

import apollo
import config
import n8n
import people as peoplemod
import schema
from util import append_jsonl, now_iso, read_jsonl

FINAL = ("received", "none", "not_available")


class PhoneError(RuntimeError):
    pass


def receiver():
    """(webhook_url, data_table_id). Webhook path: env IDEA_LAUNCH_PHONE_WEBHOOK_PATH or config.local.json (secret).
    Data table id: env IDEA_LAUNCH_PHONE_DATA_TABLE_ID, config.local.json or the committed config.json."""
    ph = config.get("phones") or {}
    missing = []
    if not ph.get("webhook_path") or config.is_placeholder(ph.get("webhook_path")):
        missing.append("IDEA_LAUNCH_PHONE_WEBHOOK_PATH")
    if not ph.get("data_table_id") or config.is_placeholder(ph.get("data_table_id")):
        missing.append("IDEA_LAUNCH_PHONE_DATA_TABLE_ID")
    if missing:
        raise PhoneError("missing environment variable(s): %s. Set them in the Claude web environment (locally: config.local.json "
                         "phones.*). If the phone receiver was never deployed, run python3 -I engine/workflows/"
                         "deploy_phone_webhook.py once." % ", ".join(missing))
    return n8n.webhook_url(ph["webhook_path"]), ph["data_table_id"]


def extract_phones(phones):
    """phones: list of dicts from Apollo. Returns (best_number, type). Mobile first, then the first with a number."""
    best, best_type = "", ""
    for p in phones or []:
        if not isinstance(p, dict):
            continue
        num = p.get("sanitized_number") or p.get("raw_number") or p.get("number") or ""
        typ = str(p.get("type_cd") or p.get("type") or "").lower()
        if not num:
            continue
        if not best or (typ == "mobile" and best_type != "mobile"):
            best, best_type = num, typ
    return best, best_type


def parse_row(row):
    """One data table row -> list of (person_id, status, phone, type, request_id). Tolerates unparsed payloads."""
    out = []
    rid = str(row.get("request_id") or "")
    pid = row.get("person_id") or ""
    people = []
    if pid:
        try:
            phones = json.loads(row.get("phones_json") or "[]")
        except ValueError:
            phones = []
        people.append({"id": pid, "phone_numbers": phones, "status": row.get("status")})
    else:
        try:
            raw = json.loads(row.get("raw_json") or "{}")
            people = raw.get("people") or raw.get("matches") or []
        except ValueError:
            people = []
    for p in people:
        num, typ = extract_phones(p.get("phone_numbers") or p.get("phones") or [])
        out.append((str(p.get("id") or p.get("person_id") or ""), "received" if num else "none", num, typ, rid))
    return out


def state(run):
    out = {}
    for r in read_jsonl(peoplemod.Files(run).phones_log):
        out[r.get("person_id")] = r
    return out


def candidates(rows, st, rerequest_stale=False):
    """Selected T1 people, enriched, with no phone request yet."""
    out = []
    for r in rows:
        if r["cap_status"] != schema.CAP_SELECTED or r["tier"] != schema.TIER_T1 or r["enrich_status"] != "matched" \
                or r.get("exclusion_reason"):
            continue
        cur = st.get(r["person_id"])
        if cur and (cur["status"] in FINAL or (cur["status"] == "requested" and not rerequest_stale)):
            continue
        out.append(r)
    return out


def table_rows(table_id):
    out, cursor = [], ""
    while True:
        st, d = n8n.api("GET", "/data-tables/%s/rows?limit=200%s" % (table_id, "&cursor=" + cursor if cursor else ""))
        if st != 200:
            raise PhoneError("could not read the data table (%s): %s" % (st, str(d)[:200]))
        out += d.get("data", [])
        cursor = d.get("nextCursor") or ""
        if not cursor:
            return out


def _log_webhook_credits(run, row):
    """The webhook payload carries its own credits_consumed (the phone part of the cost; the synchronous answer only
    shows the email part). Log it once, when the first of its people is collected."""
    try:
        raw = json.loads(row.get("raw_json") or "{}")
        credits = float(raw.get("credits_consumed") or 0)
    except (ValueError, TypeError):
        return
    if credits:
        append_jsonl(run.usage_log, {"ts": now_iso(), "endpoint": "phone_webhook", "status": 200, "credits": credits,
                                     "label": "phones", "people": raw.get("total_requested_enrichments")})


def collect(run, table_id=None, rows=None):
    """Read the receiver table and record results for people still `requested`. Returns counts."""
    f = peoplemod.Files(run)
    table_id = table_id or receiver()[1]
    st = state(run)
    waiting = {pid for pid, r in st.items() if r["status"] == "requested"}
    got = {"received": 0, "none": 0}
    for row in (rows if rows is not None else table_rows(table_id)):
        parsed = parse_row(row)
        if any(p[0] in waiting for p in parsed):
            _log_webhook_credits(run, row)
        for pid, status, num, typ, rid in parsed:
            if pid in waiting:
                waiting.discard(pid)
                append_jsonl(f.phones_log, {"person_id": pid, "status": status, "phone": num, "phone_type": typ,
                                            "source": "apollo", "request_id": rid, "received_at": now_iso()})
                got[status] += 1
    got["still_waiting"] = len(waiting)
    return got


def run_phones(run, client, limit=None, poll=True, rerequest_stale=False, sleep=time.sleep, progress=print):
    f = peoplemod.Files(run)
    rows = peoplemod.rebuild(run)
    url, table_id = receiver()
    pcfg = config.get("phones")
    st = state(run)
    todo = candidates(rows, st, rerequest_stale)
    if limit:
        todo = todo[:limit]
    rep = {"to_request": len(todo), "requested": 0, "skipped_no_phone": 0, "credits": 0.0, "received": 0, "none": 0,
           "still_waiting": 0, "errors": 0, "note": ""}
    send = []
    for r in todo:
        if pcfg.get("skip_if_apollo_says_no", True) and r.get("apollo_has_phone", "").strip().lower() == "no":
            append_jsonl(f.phones_log, {"person_id": r["person_id"], "status": "not_available", "phone": "",
                                        "source": "apollo", "received_at": now_iso(),
                                        "note": "Apollo search says no direct phone"})
            rep["skipped_no_phone"] += 1
        else:
            send.append(r)
    size = config.get("apollo.bulk_match_batch", 10)
    for i in range(0, len(send), size):
        chunk = send[i:i + size]
        client.label = "phones"
        try:
            res = client.bulk_match([{"id": r["person_id"], "first_name": r["first_name"],
                                      "organization_name": r["company"], "domain": r["domain"]} for r in chunk],
                                    reveal_phone=True, webhook_url=url)
        except apollo.ApolloError as e:
            rep["errors"] += 1
            rep["note"] = "Apollo error, stopped: %s" % e
            break
        rep["credits"] += res["credits"]
        rid = str(res.get("request_id") or "")
        for r in chunk:
            append_jsonl(f.phones_log, {"person_id": r["person_id"], "status": "requested", "request_id": rid,
                                        "requested_at": now_iso(), "apollo_phone_status": res.get("phone_status", ""),
                                        "source": "apollo"})
            rep["requested"] += 1
        if res.get("phone_status") == "skipped":
            rep["note"] = "Apollo said an enrichment was already in progress for some people (no new webhook)"
    if poll:
        end = time.time() + pcfg["timeout_min"] * 60
        while True:
            c = collect(run, table_id)
            rep["received"] += c["received"]
            rep["none"] += c["none"]
            rep["still_waiting"] = c["still_waiting"]
            if not c["still_waiting"] or time.time() >= end:
                break
            if progress:
                progress("  waiting for Apollo to deliver %d phone result(s)..." % c["still_waiting"])
            sleep(pcfg["poll_interval_s"])
    rep["credits"] = round(rep["credits"], 2)
    return rep
