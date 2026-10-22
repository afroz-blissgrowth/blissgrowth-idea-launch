"""Apollo REST client for Idea Launch (organization search and people search only).

Endpoints (docs.apollo.io, checked 2026-10-21):
  POST /api/v1/mixed_companies/search     1 credit per page (max 100 per page, 500 pages, 50,000 display cap)
  POST /api/v1/mixed_people/api_search    0 credits, no emails or phones in the response
  POST /api/v1/people/bulk_match          up to 10 people per call, 1 credit per revealed email (+8 per mobile),
                                          real cost read from `credits_consumed`
  POST /api/v1/organizations/bulk_enrich  up to 10 domains per call (`domains[]` in the query), 1 credit per matched
                                          company, 0 if not found. Gives estimated_num_employees and
                                          departmental_head_count {engineering, operations, sales, ...} (company signals)
  GET  /api/v1/organizations/enrich       one company by `domain`, 1 credit if found (single fallback)
  Auth: x-api-key header. Params go in the query string with name[] for lists, name[min]/name[max]
  for ranges. Rate limit headers on every response: x-minute-requests-left, x-hourly-requests-left,
  x-24-hour-requests-left. 429 bodies may carry error_details.retry_after_seconds.

Quirks learned the hard way (verified live):
  * Organization search returns companies in TWO arrays: `organizations` (not yet in your Apollo
    CRM) and `accounts` (already saved in your team's CRM). Both must be read. Account records carry
    the Apollo organization id in `organization_id` (their own `id` is the CRM account id).
  * Records have no industry, headcount or description. Headcount is only known from the filter band.

The result-cap sharding idea (split by location, then size band, then keywords when a filter
exceeds Apollo's 50,000 display cap) is ported from GrowthEngine coldoutboundskills
list-expander/pull.ts (MIT, copyright 2026 GrowthEngineX), re-implemented in Python for Apollo.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse

import brief as briefmod
import config
import net
from util import append_jsonl, norm_domain, now_iso

ORG_ENDPOINT = "mixed_companies/search"
PEOPLE_ENDPOINT = "mixed_people/api_search"
BULK_MATCH_ENDPOINT = "people/bulk_match"
ORG_BULK_ENRICH_ENDPOINT = "organizations/bulk_enrich"
ORG_ENRICH_ENDPOINT = "organizations/enrich"
MAX_QUERY_CHARS = 6000


class ApolloError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


_default_transport = net.fetch


class ApolloClient:
    def __init__(self, api_key=None, usage_log=None, transport=None, sleep=time.sleep, label=""):
        self.cfg = config.get("apollo")
        self.api_key = api_key or config.env("APOLLO_API_KEY", required=True)
        self.usage_log = usage_log
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.label = label
        self.limits = {}
        self.totals = {"calls": 0, "credits": 0, "retries": 0}
        self._last = 0.0

    # ---- transport with retries, backoff, rate limiting -------------------------------------
    def _throttle(self):
        wait = self.cfg["min_interval_s"] - (time.time() - self._last)
        if wait > 0:
            self.sleep(wait)
        left = self.limits.get("minute_left")
        if left is not None and left < self.cfg["minute_floor"]:
            self.sleep(62)  # the per-minute window resets; wait it out rather than eat a 429
            self.limits["minute_left"] = None

    def _record_limits(self, headers):
        for key, name in (("minute_left", "x-minute-requests-left"), ("hour_left", "x-hourly-requests-left"),
                          ("day_left", "x-24-hour-requests-left")):
            if name in headers:
                try:
                    self.limits[key] = int(headers[name])
                except ValueError:
                    pass

    def hour_budget_low(self):
        """True when the hourly request budget is nearly used (stop cleanly, resume later)."""
        left = self.limits.get("hour_left")
        return left is not None and left < self.cfg.get("hour_floor", 40)

    def _log(self, endpoint, status, credits, extra):
        self.totals["calls"] += 1
        self.totals["credits"] += credits
        if self.usage_log:
            rec = {"ts": now_iso(), "endpoint": endpoint, "status": status, "credits": credits,
                   "label": self.label, "limits": dict(self.limits)}
            rec.update(extra or {})
            append_jsonl(self.usage_log, rec)

    def request(self, endpoint, params, credits_per_call=0, extra=None, body=None, credits_from=None, method="POST"):
        """POST with query params (or a JSON body when the query would be too long). Returns parsed JSON.
        body: explicit JSON body (params then stay in the query string). credits_from(response) -> real credits
        for endpoints whose cost varies (bulk_match); otherwise credits_per_call is logged.
        method GET (organizations/enrich) sends the params in the query string and no body."""
        qs = urllib.parse.urlencode(params)
        url = "%s/%s" % (self.cfg["base_url"].rstrip("/"), endpoint)
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json",
                   "Cache-Control": "no-cache", "Accept": "application/json"}
        data = None
        if method == "GET":
            url += ("?" + qs) if qs else ""
        elif body is not None:
            url += ("?" + qs) if qs else ""
            data = json.dumps(body).encode()
        elif len(qs) > MAX_QUERY_CHARS:
            body = {}
            for k, v in params:
                if k.endswith("[]"):
                    body.setdefault(k[:-2], []).append(v)
                elif "[" in k:
                    base, sub = k.rstrip("]").split("[", 1)
                    body.setdefault(base, {})[sub] = v
                else:
                    body[k] = v
            data = json.dumps(body).encode()
        else:
            url += "?" + qs
            data = b"{}"
        attempt = 0
        while True:
            self._throttle()
            try:
                status, rh, raw = self.transport(method, url, headers, data, self.cfg["timeout_s"])
            except Exception as e:  # network errors, timeouts
                status, rh, raw = 0, {}, str(e).encode()
            self._last = time.time()
            self._record_limits(rh)
            if status == 200:
                try:
                    out = json.loads(raw)
                except json.JSONDecodeError:
                    raise ApolloError("Apollo returned non-JSON 200", status, raw[:200])
                credits = credits_per_call
                if credits_from:
                    try:
                        credits = credits_from(out)
                    except Exception:
                        credits = credits_per_call
                self._log(endpoint, 200, credits, extra)
                return out
            text = raw.decode("utf-8", "replace")[:300]
            if status in (400, 401, 402, 403, 404, 422):
                self._log(endpoint, status, 0, extra)
                raise ApolloError("Apollo %s on %s: %s" % (status, endpoint, text), status, text)
            attempt += 1
            self.totals["retries"] += 1
            if attempt > self.cfg["max_retries"]:
                self._log(endpoint, status, 0, extra)
                raise ApolloError("Apollo gave up after %d attempts (%s): %s" % (attempt - 1, status, text), status, text)
            if status == 429:
                wait = 60
                try:
                    wait = int(json.loads(raw).get("error_details", {}).get("retry_after_seconds") or wait)
                except Exception:
                    if rh.get("retry-after", "").isdigit():
                        wait = int(rh["retry-after"])
                self._log(endpoint, 429, 0, extra)
                self.sleep(min(max(wait, 1), 900))
            else:  # 5xx or network error: exponential backoff
                self.sleep(min(2 ** attempt, 60))

    # ---- normalisation ----------------------------------------------------------------------
    @staticmethod
    def normalize_org(rec, filters=None):
        """Turn an organization or CRM-account record into one flat account row."""
        in_crm = "organization_id" in rec
        org_id = rec.get("organization_id") or rec.get("id") or ""
        website = rec.get("website_url") or ""
        domain = norm_domain(rec.get("primary_domain") or rec.get("domain") or website)
        locs = (filters or {}).get("organization_locations") or []
        return {
            "org_id": org_id,
            "domain": domain,
            "name": rec.get("name") or "",
            "website": website,
            "linkedin_url": rec.get("linkedin_url") or "",
            "country": rec.get("country") or rec.get("organization_country") or "",
            "state": rec.get("state") or rec.get("organization_state") or "",
            "city": rec.get("city") or rec.get("organization_city") or "",
            "filter_location": "; ".join(locs) if len(locs) == 1 else "",
            "revenue": rec.get("organization_revenue_printed") or "",
            "founded_year": rec.get("founded_year") or "",
            "naics": ",".join(rec.get("naics_codes") or []),
            "sic": ",".join(rec.get("sic_codes") or []),
            "phone": rec.get("sanitized_phone") or rec.get("phone") or "",
            "apollo_crm": "yes" if in_crm else "",
        }

    # ---- organization search ----------------------------------------------------------------
    def org_page(self, filters, page=1, per_page=None):
        per_page = per_page or self.cfg["per_page"]
        params = briefmod.to_params(filters, page=page, per_page=per_page)
        d = self.request(ORG_ENDPOINT, params, self.cfg["credits_per_org_search_page"],
                         {"page": page, "per_page": per_page})
        recs = list(d.get("organizations") or []) + list(d.get("accounts") or [])
        pag = d.get("pagination") or {}
        return {"orgs": [self.normalize_org(r, filters) for r in recs],
                "total_entries": int(pag.get("total_entries") or 0),
                "total_pages": int(pag.get("total_pages") or 0),
                "n_records": len(recs)}

    def org_count(self, filters):
        """Total matches. Costs 1 credit (one page of 1)."""
        return self.org_page(filters, page=1, per_page=1)["total_entries"]

    @staticmethod
    def split_filters(filters):
        """Return a list of narrower filter dicts that together cover `filters`, or None."""
        def sub(key, vals):
            return [dict(filters, **{key: [v]}) for v in vals]
        loc = filters.get("organization_locations") or []
        if len(loc) > 1:
            return sub("organization_locations", loc)
        rng = filters.get("organization_num_employees_ranges") or []
        if len(rng) > 1:
            return sub("organization_num_employees_ranges", rng)
        if len(rng) == 1:
            lo, hi = [int(x) for x in rng[0].split(",")]
            if hi > lo:
                mid = lo + (hi - lo) // 2
                return [dict(filters, organization_num_employees_ranges=["%d,%d" % (lo, mid)]),
                        dict(filters, organization_num_employees_ranges=["%d,%d" % (mid + 1, hi)])]
        for key in ("q_organization_keyword_tags", "organization_industry_tag_ids", "organization_naics_codes"):
            vals = filters.get(key) or []
            if len(vals) > 1:
                return sub(key, vals)
        return None

    def plan(self, filters, cap=None, depth=0):
        """Count-first sizing. Returns leaves [{filters, total, truncated}] each under the cap
        (or unsplittable, then truncated=True). Costs 1 credit per count call."""
        cap = cap or self.cfg["display_cap"]
        total = self.org_count(filters)
        if total > cap and depth < 12:
            parts = self.split_filters(filters)
            if parts:
                leaves = []
                for p in parts:
                    leaves.extend(self.plan(p, cap, depth + 1))
                return leaves
            return [{"filters": filters, "total": total, "truncated": True}]
        return [{"filters": filters, "total": total, "truncated": total > cap}]

    def iter_leaf(self, filters, total, start_page=1, limit=None, per_page=None, on_page=None):
        """Yield account rows for one leaf, page by page. on_page(page, rows) after each page."""
        per_page = per_page or self.cfg["per_page"]
        pages = min(int(math.ceil(total / float(per_page))), self.cfg["max_pages"])
        got = 0
        for page in range(start_page, pages + 1):
            res = self.org_page(filters, page, per_page)
            rows = res["orgs"]
            if limit is not None and got + len(rows) > limit:
                rows = rows[: limit - got]
            got += len(rows)
            if on_page:
                on_page(page, rows)
            for r in rows:
                yield r
            if not res["n_records"] or (limit is not None and got >= limit):
                break

    # ---- people search (no credits, no emails) ----------------------------------------------
    def people_page(self, titles, org_ids=None, domains=None, seniorities=None, locations=None,
                    include_similar_titles=True, page=1, per_page=100, extra=None):
        params = [("page", str(page)), ("per_page", str(per_page)),
                  ("include_similar_titles", "true" if include_similar_titles else "false")]
        for t in titles or []:
            params.append(("person_titles[]", t))
        for o in org_ids or []:
            params.append(("organization_ids[]", o))
        for d in domains or []:
            params.append(("q_organization_domains_list[]", d))
        for s in seniorities or []:
            params.append(("person_seniorities[]", s))
        for loc in locations or []:
            params.append(("person_locations[]", loc))
        for k, v in (extra or {}).items():
            params.append((k, str(v)))
        d = self.request(PEOPLE_ENDPOINT, params, self.cfg["credits_per_people_search_page"],
                         {"page": page, "per_page": per_page})
        return {"people": d.get("people") or [], "total_entries": int(d.get("total_entries") or 0)}

    # ---- enrichment (credits) ---------------------------------------------------------------
    @staticmethod
    def _real_email(e):
        e = (e or "").strip().lower()
        if not e or "email_not_unlocked" in e or e.endswith("@domain.com"):
            return ""
        return e

    @classmethod
    def normalize_match(cls, m):
        """A bulk_match person record -> flat dict (empty strings for missing values)."""
        org = m.get("organization") or {}
        return {"person_id": m.get("id") or "", "first_name": m.get("first_name") or "",
                "last_name": m.get("last_name") or "", "title": m.get("title") or "",
                "seniority": m.get("seniority") or "", "linkedin_url": m.get("linkedin_url") or "",
                "email": cls._real_email(m.get("email")), "email_status": m.get("email_status") or "",
                "country": m.get("country") or "", "city": m.get("city") or "",
                "match_confidence": m.get("match_confidence") or "",
                "headline": m.get("headline") or "",
                "employment_history": cls.compact_employment(m.get("employment_history")),
                "org_name": org.get("name") or "", "org_domain": norm_domain(org.get("primary_domain") or "")}

    @staticmethod
    def compact_employment(history, max_entries=None):
        """employment_history -> short list [{org, title, current, start, end}] (newest first as Apollo sends it).
        Kept in enrich.jsonl so the employment exclusions (lib/exclusions.py) can be re-evaluated without paying again.
        Apollo entry keys (docs.apollo.io people enrichment): current, start_date, end_date, organization_name, title."""
        max_entries = max_entries or config.get("exclusions.employment_history_max_entries", 8)
        out = []
        for e in (history or [])[:max_entries]:
            if not isinstance(e, dict):
                continue
            out.append({"org": e.get("organization_name") or "", "title": e.get("title") or "",
                        "current": bool(e.get("current")), "start": e.get("start_date") or "",
                        "end": e.get("end_date") or ""})
        return out

    def bulk_match(self, details, reveal_personal_emails=False, reveal_phone=False, webhook_url=None, extra=None):
        """people/bulk_match for up to 10 people. details: [{id, first_name, organization_name, domain, ...}].
        Returns {'matches': [normalized or None, one per detail in order], 'credits': float,
                 'missing': int, 'request_id': ..., 'phone_status': ..., 'raw_phone_enrichment': ...}.
        Credits are logged from `credits_consumed` (1 per revealed email, plus 8 per mobile)."""
        n = self.cfg.get("bulk_match_batch", 10)
        if not details or len(details) > n:
            raise ApolloError("bulk_match takes 1 to %d people per call" % n)
        params = []
        if reveal_personal_emails:
            params.append(("reveal_personal_emails", "true"))
        if reveal_phone:
            if not webhook_url:
                raise ApolloError("reveal_phone needs a webhook_url")
            params += [("reveal_phone_number", "true"), ("webhook_url", webhook_url)]
        d = self.request(BULK_MATCH_ENDPOINT, params, self.cfg.get("credits_per_bulk_match_person", 1) * len(details),
                         dict({"people": len(details), "phone": bool(reveal_phone)}, **(extra or {})),
                         body={"details": details}, credits_from=lambda r: float(r.get("credits_consumed") or 0))
        raw = d.get("matches") or []
        matches = [self.normalize_match(m) if isinstance(m, dict) else None for m in raw]
        matches += [None] * (len(details) - len(matches))
        pe = d.get("phone_enrichment") or {}
        return {"matches": matches[:len(details)], "credits": float(d.get("credits_consumed") or 0),
                "missing": int(d.get("missing_records") or 0), "request_id": d.get("request_id"),
                "phone_status": pe.get("status", ""), "raw_phone_enrichment": pe}

    def webhook_result(self, request_id):
        """GET /webhook_result/{request_id} (Apollo's poll endpoint). Returns (status, json). Free."""
        url = "%s/webhook_result/%s" % (self.cfg["base_url"].rstrip("/"), request_id)
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        self._throttle()
        st, rh, raw = self.transport("GET", url, headers, None, self.cfg["timeout_s"])
        self._last = time.time()
        self._record_limits(rh)
        try:
            return st, json.loads(raw or b"{}")
        except ValueError:
            return st, {"raw": raw[:300].decode("utf-8", "replace")}

    # ---- organization enrichment: company signals (credits) ----------------------------------
    @staticmethod
    def normalize_org_enrichment(o):
        """An organizations/enrich record -> flat dict. departments: {key: int} exactly as Apollo spells the keys.
        employees is None (not 0) when Apollo has no estimate, so a missing value never reads as 'no employees'."""
        dh = o.get("departmental_head_count") or {}
        depts = {}
        for k, v in dh.items():
            try:
                depts[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        emp = o.get("estimated_num_employees")
        try:
            emp = int(emp) if emp not in (None, "") else None
        except (TypeError, ValueError):
            emp = None
        techs = list(o.get("technology_names") or [])
        if not techs:
            techs = [t.get("name") for t in (o.get("current_technologies") or []) if isinstance(t, dict) and t.get("name")]
        return {"org_id": o.get("id") or "", "name": o.get("name") or "",
                "domain": norm_domain(o.get("primary_domain") or o.get("website_url") or ""),
                "employees": emp, "departments": depts, "industry": o.get("industry") or "",
                "technologies": techs[: config.get("signals.max_technologies", 60)]}

    def org_bulk_enrich(self, domains, extra=None):
        """organizations/bulk_enrich for up to 10 domains. Returns {'orgs': [normalized, matched only], 'aligned': [...] or None, 'credits',
        'missing': int}. Credits are logged from `credits_consumed` when Apollo sends it, else 1 per matched company."""
        n = config.get("signals.batch", 10)
        if not domains or len(domains) > n:
            raise ApolloError("organizations/bulk_enrich takes 1 to %d domains per call" % n)
        per = config.get("signals.credits_per_matched_org", 1)

        def credits(out):
            if out.get("credits_consumed") is not None:
                return float(out["credits_consumed"])
            return float(per * len([o for o in (out.get("organizations") or []) if isinstance(o, dict)]))

        d = self.request(ORG_BULK_ENRICH_ENDPOINT, [("domains[]", x) for x in domains], per * len(domains),
                         dict({"domains": len(domains)}, **(extra or {})), body={}, credits_from=credits)
        raw = d.get("organizations") or []
        orgs = [self.normalize_org_enrichment(o) for o in raw if isinstance(o, dict)]
        # Apollo does not document that the answer keeps the input order (unmatched entries may be null or absent), so
        # `aligned` (one entry per requested domain, None when unmatched) is given only when the lengths agree.
        aligned = [self.normalize_org_enrichment(o) if isinstance(o, dict) else None for o in raw] \
            if len(raw) == len(domains) else None
        return {"orgs": orgs, "aligned": aligned, "credits": credits(d), "missing": int(d.get("missing_records") or 0)}

    def org_enrich(self, domain, extra=None):
        """GET organizations/enrich for one domain (1 credit if found). Returns the normalized record or None."""
        d = self.request(ORG_ENRICH_ENDPOINT, [("domain", domain)], config.get("signals.credits_per_matched_org", 1),
                         dict({"domains": 1}, **(extra or {})), method="GET",
                         credits_from=lambda out: float(config.get("signals.credits_per_matched_org", 1)) if out.get("organization") else 0.0)
        o = d.get("organization")
        return self.normalize_org_enrichment(o) if isinstance(o, dict) else None

    def usage_stats(self):
        """Plan rate-limit and usage numbers (free). Returns raw JSON or {'error': ...}."""
        try:
            return self.request("usage_stats/api_usage_stats", [])
        except ApolloError as e:
            return {"error": str(e)}
