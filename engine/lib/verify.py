"""Stage 6b: MillionVerifier on the enriched emails (single API), cached per email.

Docs: developer.millionverifier.com. GET https://api.millionverifier.com/api/v3?api=KEY&email=...&timeout=20
-> {result, subresult, quality, resultcode, free, role, didyoumean, credits, error}. A browser User-Agent is
required (403 otherwise, learned in production). Rules (from GrowthEngine list-builder guidance, MIT):
  * `ok` is the ONLY pass. catch_all is recorded as "catch_all" (kept, marked for a later secondary verifier),
    unknown and invalid and disposable fail, `error` is retried on the next run.
  * the provider's own "verified" (Apollo email_status) is a hint, never the gate.
  * results are cached per email in verify/mv.jsonl: a re-run never re-checks or re-pays.
The bulk file API (POST bulkapi/v2/upload, fileinfo, download) is not used: at 2,000 to 3,000 emails the single
API with 5 workers is fast enough, and it needs no file round trip. Swap it in here if volumes grow.
The key lives in <repo>/.env as MILLIONVERIFIER_API_KEY and is never printed or logged.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import config
import net
import people as peoplemod
import schema
from util import append_jsonl, now_iso, read_jsonl


class MVError(RuntimeError):
    """Fatal MillionVerifier problem (bad key, no credits, blocked)."""


def key_available():
    return bool(config.env("MILLIONVERIFIER_API_KEY"))


class MillionVerifier:
    def __init__(self, api_key=None, transport=None, sleep=time.sleep):
        self.cfg = config.get("verify")
        self.api_key = api_key or config.env("MILLIONVERIFIER_API_KEY")
        if not self.api_key:
            raise MVError("MILLIONVERIFIER_API_KEY is not in <repo>/.env. Add it and re-run (nothing is lost).")
        self.transport = transport or net.fetch
        self.sleep = sleep

    def verify(self, email):
        """Return a result dict. Raises MVError on fatal problems; transient failures become result 'error'."""
        qs = urllib.parse.urlencode({"api": self.api_key, "email": email, "timeout": self.cfg["mv_api_timeout_param_s"]})
        url = self.cfg["mv_base_url"] + "?" + qs
        headers = {"User-Agent": self.cfg["user_agent"], "Accept": "application/json"}
        last = ""
        for attempt in range(self.cfg["max_retries"]):
            try:
                st, _, raw = self.transport("GET", url, headers, None, self.cfg["mv_timeout_s"])
            except Exception as e:
                last = "network: %s" % str(e).replace(self.api_key, "***")[:120]
                self.sleep(2 ** attempt)
                continue
            if st in (401, 403):
                raise MVError("MillionVerifier refused the request (%d). Check MILLIONVERIFIER_API_KEY and that a "
                              "browser User-Agent is sent." % st)
            if st == 429 or st >= 500:
                last = "http %d" % st
                self.sleep(2 ** (attempt + 1))
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                last = "non-JSON answer (%d)" % st
                self.sleep(2 ** attempt)
                continue
            err = str(d.get("error") or "")
            if err:
                low = err.lower()
                # fatal for every email (checked live with MillionVerifier's demo keys): "Apikey not found",
                # "Insufficient credits", "IP address blocked". Retrying them would only burn time.
                if "key" in low or "credit" in low or "api" in low or "blocked" in low:
                    raise MVError("MillionVerifier error: %s" % err)
                last = err  # "Internal error" and similar: back off, then retry
                self.sleep(2 ** attempt)
                continue
            res = str(d.get("result") or "").lower()
            if not res:
                last = "empty result"
                continue
            return {"email": email.lower(), "result": res, "subresult": str(d.get("subresult") or "").lower(),
                    "quality": d.get("quality") or "", "resultcode": d.get("resultcode"), "role": d.get("role"),
                    "free": d.get("free"), "credits_left": d.get("credits"), "checked_at": now_iso()}
        return {"email": email.lower(), "result": "error", "subresult": last, "quality": "", "checked_at": now_iso()}


def todo_emails(rows, cache):
    """Unique emails of selected people that have no final MV result yet (errors are retried)."""
    seen, out = set(), []
    for r in rows:
        e = (r.get("email") or "").lower()
        if r["cap_status"] != schema.CAP_SELECTED or not e or e in seen:
            continue
        c = cache.get(e)
        if c and c.get("result") != "error":
            continue
        seen.add(e)
        out.append(e)
    return out


def cache(run):
    out = {}
    for r in read_jsonl(peoplemod.Files(run).mv):
        out[r.get("email")] = r
    return out


def run_verify(run, mv=None, limit=None, progress=print):
    f = peoplemod.Files(run)
    rows = peoplemod.rebuild(run)
    todo = todo_emails(rows, cache(run))
    if limit:
        todo = todo[:limit]
    rep = {"to_check": len(todo), "checked": 0, "results": {}, "fatal": ""}
    if not todo:
        return rep
    mv = mv or MillionVerifier()
    workers = config.get("verify.concurrency", 5)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(mv.verify, e) for e in todo]
        for fut in futs:
            try:
                r = fut.result()
            except MVError as e:
                rep["fatal"] = str(e)
                for g in futs:
                    g.cancel()
                break
            append_jsonl(f.mv, r)
            rep["checked"] += 1
            rep["results"][r["result"]] = rep["results"].get(r["result"], 0) + 1
            if progress and rep["checked"] % 100 == 0:
                progress("  verified %d of %d" % (rep["checked"], len(todo)))
    return rep
