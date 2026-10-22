"""HeyReach public API client (stdlib only, Bliss workspace key from .env HEYREACH_API_KEY, never printed).

Base https://api.heyreach.io/api/public, header X-API-KEY. Endpoints used (checked live 2026-10-21 where marked):
  READ (verified live, read only)
    POST campaign/GetAll {offset, limit, keyword, statuses, accountIds}   -> {totalCount, items[]}
    GET  campaign/GetById?campaignId=                                      -> campaign
    GET  campaign/GetCampaignSequence?campaignId=                          -> sequence tree (nodeType, payload, ...)
    POST stats/GetOverallStats {accountIds, campaignIds, startDate, endDate} -> {overallStats, byDayStats}
    POST list/GetAll {offset, limit, keyword, listType}                    -> {totalCount, items[]}
  WRITE (validation errors seen live with an empty body, a real create has NOT been run by the build agent)
    POST list/CreateEmptyList {name, type}              type USER_LIST. The HeyReach tool docs call them listName/listType, so both
                                                        spellings are sent (unknown keys are ignored); confirm on the first real launch
    POST list/AddLeadsToListV2 {listId, leads[<=100]}
    POST campaign/Create {name, linkedInUserListId, linkedInAccountIds, ...}   creates a DRAFT, never starts it
    POST campaign/UpdateSequence {campaignId, sequence}  (campaign must be DRAFT, SCHEDULED or PAUSED)

SAFETY: this module deliberately has NO method for campaign/Start, Resume, Pause or any delete. Starting a campaign
is a human action in the HeyReach app. tests assert that no such path exists in this file.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import config
import net

BASE = "https://api.heyreach.io/api/public"


class HeyReachError(RuntimeError):
    pass


class HeyReach:
    def __init__(self, key=None, transport=None, sleep=time.sleep, min_interval_s=0.25):
        self.key = key or config.env("HEYREACH_API_KEY")
        if not self.key:
            raise HeyReachError("Missing HEYREACH_API_KEY in <repo>/.env (Bliss workspace key)")
        self.transport = transport or net.fetch
        self.sleep = sleep
        self.min_interval_s = min_interval_s
        self._last = 0.0

    def _req(self, method, path, body=None, params=None, retries=4):
        url = BASE + "/" + path + ("?" + urlencode(params) if params else "")
        headers = {"X-API-KEY": self.key, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        for attempt in range(retries + 1):
            wait = self.min_interval_s - (time.time() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.time()
            try:
                st, hdr, raw = self.transport(method, url, headers, data, 60)
            except Exception as e:  # network error: reads may retry, writes must not (could duplicate)
                if method == "GET" or path.endswith("GetAll") or path.endswith("GetOverallStats"):
                    if attempt < retries:
                        self.sleep(2 ** attempt)
                        continue
                raise HeyReachError("network error on %s: %s" % (path, e))
            if st == 429 and attempt < retries:
                try:
                    ra = float(hdr.get("retry-after", 5))
                except ValueError:
                    ra = 5
                self.sleep(min(ra, 60))
                continue
            if st in (502, 503, 504) and method == "GET" and attempt < retries:
                self.sleep(2 ** attempt)
                continue
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            if st in (401, 403):
                raise HeyReachError("HeyReach refused the key (%s). Check HEYREACH_API_KEY (Bliss workspace)." % st)
            if st >= 400:
                raise HeyReachError("HeyReach %s %s failed (%s): %s" % (method, path, st, text[:400]))
            if not text.strip():
                return {}
            try:
                return json.loads(text)
            except ValueError:
                raise HeyReachError("HeyReach %s returned non-JSON (%s): %s" % (path, st, text[:200]))
        raise HeyReachError("HeyReach %s failed after retries" % path)

    # ---- reads -------------------------------------------------------------------------------
    def campaigns(self, keyword=""):
        out, off = [], 0
        while True:
            d = self._req("POST", "campaign/GetAll", {"offset": off, "limit": 100, "keyword": keyword,
                                                       "statuses": [], "accountIds": []})
            items = d.get("items") or []
            out += items
            off += len(items)
            if not items or off >= d.get("totalCount", 0):
                return out

    def campaign(self, cid):
        return self._req("GET", "campaign/GetById", params={"campaignId": cid})

    def sequence(self, cid):
        return self._req("GET", "campaign/GetCampaignSequence", params={"campaignId": cid})

    def stats(self, cid, start="2025-01-01T00:00:00Z", end="2027-12-31T00:00:00Z"):
        d = self._req("POST", "stats/GetOverallStats", {"accountIds": [], "campaignIds": [cid],
                                                         "startDate": start, "endDate": end})
        return d.get("overallStats") or {}

    def lists(self, keyword="", list_type="USER_LIST"):
        out, off = [], 0
        while True:
            d = self._req("POST", "list/GetAll", {"offset": off, "limit": 100, "keyword": keyword,
                                                   "listType": list_type})
            items = d.get("items") or []
            out += items
            off += len(items)
            if not items or off >= d.get("totalCount", 0):
                return out

    def find_list(self, name):
        """Exact-name lookup (idempotency: never create a list twice)."""
        return [x for x in self.lists(keyword=name) if x.get("name") == name]

    def find_campaign(self, name):
        return [x for x in self.campaigns(keyword=name) if x.get("name") == name]

    # ---- writes (create only, never start) -----------------------------------------------------
    def create_list(self, name):
        return self._req("POST", "list/CreateEmptyList", {"name": name, "type": "USER_LIST", "listName": name, "listType": "USER_LIST"}, retries=0)

    def add_leads(self, list_id, leads):
        if not 1 <= len(leads) <= 100:
            raise HeyReachError("AddLeadsToListV2 takes 1 to 100 leads per call")
        return self._req("POST", "list/AddLeadsToListV2", {"listId": list_id, "leads": leads}, retries=0)

    def create_campaign(self, name, list_id, account_ids, **flags):
        body = {"name": name, "linkedInUserListId": list_id, "linkedInAccountIds": list(account_ids)}
        body.update(flags)
        return self._req("POST", "campaign/Create", body, retries=0)

    def update_sequence(self, campaign_id, sequence):
        # The HeyReach tool docs name the field sequenceJson (a JSON string); the build agent's empty-body probe pointed at `sequence`.
        # Both are sent with the same tree (an unknown key is ignored). Confirm on the first real launch, then drop the wrong one.
        return self._req("POST", "campaign/UpdateSequence", {"campaignId": campaign_id, "sequence": sequence,
                                                             "sequenceJson": json.dumps(sequence)}, retries=0)
