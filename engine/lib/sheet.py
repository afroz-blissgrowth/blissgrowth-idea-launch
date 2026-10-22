"""Google Sheets client. All sheet access goes through the n8n workflow "Idea Launch | Sheets Bridge"
(webhook POST idea-launch-sheets, header X-Idea-Launch-Secret), which uses the n8n credential
"Google Sheets (Afroz)". No Google keys live on this machine.

Actions: create, read, append, upsert, format. Values are written RAW.
Retry policy: read and upsert are idempotent and retried; create and append are NOT retried after
an ambiguous failure (a retry could duplicate a sheet or rows). They raise, and the caller re-checks.
"""
from __future__ import annotations

import json
import time

import config
import net
import schema


class SheetError(RuntimeError):
    pass


def col_letter(i):
    s, i = "", i + 1
    while i > 0:
        i, m = divmod(i - 1, 26)
        s = chr(65 + m) + s
    return s


class SheetClient:
    def __init__(self, url=None, secret=None, transport=None, sleep=time.sleep):
        if url is None or secret is None:
            u, s = config.bridge_settings()
            url, secret = url or u, secret or s
        self.url, self.secret = url, secret
        self.transport = transport or net.fetch
        self.sleep = sleep
        self.cfg = config.get("sheet")
        header = (config.cfg().get("sheets_bridge") or {}).get("header", "X-Idea-Launch-Secret")
        self.header = header

    def call(self, payload, retries=0):
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", self.header: self.secret}
        last = None
        for attempt in range(retries + 1):
            try:
                st, _, raw = self.transport("POST", self.url, headers, data, self.cfg["timeout_s"])
            except Exception as e:
                last = "network: %s" % e
                if attempt < retries:
                    self.sleep(2 ** attempt * 2)
                    continue
                raise SheetError(last)
            if st in (502, 503, 504, 429) and attempt < retries:
                self.sleep(2 ** attempt * 2)
                continue
            if st == 403:
                raise SheetError("bridge refused the secret (403). Check IDEA_LAUNCH_BRIDGE_SECRET (or config.local.json sheets_bridge.secret)")
            if st == 404:
                raise SheetError("bridge webhook not found (404). Is the workflow 'Idea Launch | Sheets Bridge' active?")
            try:
                out = json.loads(raw)
            except ValueError:
                raise SheetError("bridge returned non-JSON (%s): %s" % (st, raw[:200].decode("utf-8", "replace")))
            if not out.get("ok"):
                raise SheetError("bridge error on %s: %s" % (payload.get("action"), out.get("error") or out))
            return out
        raise SheetError(last or "bridge failed")

    # ---- actions -----------------------------------------------------------------------------
    def create(self, title, tabs=None):
        """tabs: {title: [headers]} (default: the nine Idea Launch tabs). Returns {spreadsheetId, url, tabs}."""
        tabs = tabs or schema.TABS
        return self.call({"action": "create", "title": title,
                          "tabs": [{"title": t, "headers": h} for t, h in tabs.items()]})

    def read(self, sheet_id, tab, raw=False):
        out = self.call({"action": "read", "sheet_id": sheet_id, "tab": tab, "raw": raw}, retries=2)
        return out.get("values", [])

    def read_records(self, sheet_id, tab):
        vals = self.read(sheet_id, tab, raw=True)
        if not vals:
            return []
        head = [str(h) for h in vals[0]]
        return [dict(zip(head, list(r) + [""] * (len(head) - len(r)))) for r in vals[1:]]

    def append(self, sheet_id, tab, rows):
        n = 0
        size = self.cfg["append_chunk"]
        for i in range(0, len(rows), size):
            out = self.call({"action": "append", "sheet_id": sheet_id, "tab": tab, "values": rows[i:i + size]})
            n += out.get("appended", len(rows[i:i + size]))
        return n

    def append_records(self, sheet_id, tab, records, headers=None):
        headers = headers or schema.TABS[tab]
        return self.append(sheet_id, tab, [[r.get(h, "") for h in headers] for r in records])

    def upsert(self, sheet_id, tab, key, records):
        tot = {"updated": 0, "appended": 0, "skipped": 0, "unknown_columns": []}
        size = self.cfg["upsert_chunk"]
        for i in range(0, len(records), size):
            out = self.call({"action": "upsert", "sheet_id": sheet_id, "tab": tab, "key": key,
                             "records": records[i:i + size]}, retries=2)
            for k in ("updated", "appended", "skipped"):
                tot[k] += out.get(k, 0)
            tot["unknown_columns"] = sorted(set(tot["unknown_columns"]) | set(out.get("unknown_columns") or []))
        return tot

    def format(self, sheet_id, tabs=None):
        return self.call({"action": "format", "sheet_id": sheet_id, "tabs": tabs}, retries=2)

    def add_columns(self, sheet_id, tab, headers):
        """Append the headers missing from row 1 of an existing tab (never reorders or renames). Idempotent.
        Returns {'added': [...], 'existing': n}."""
        out = self.call({"action": "add_columns", "sheet_id": sheet_id, "tab": tab, "headers": list(headers)}, retries=2)
        return {"added": out.get("added") or [], "existing": out.get("existing", 0)}

    def ensure_schema(self, sheet_id, tabs=None):
        """Migrate an existing sheet to the current lib/schema.py headers (adds new columns only)."""
        res = {}
        for tab in tabs or schema.TAB_ORDER:
            r = self.add_columns(sheet_id, tab, schema.TABS[tab])
            if r["added"]:
                res[tab] = r["added"]
        return res

    def share(self, sheet_id, domain=None, emails=None, role="writer", notify=False):
        """Share the sheet through Drive permissions. domain: anyone in that Google Workspace domain gets `role`.
        Returns the bridge answer {'ok', 'shared': [{target, ok, id, error}]}. Raises SheetError with a
        readable hint if Google refuses (for example a missing Drive scope)."""
        payload = {"action": "share", "sheet_id": sheet_id, "role": role, "notify": bool(notify)}
        if domain:
            payload["domain"] = domain
        if emails:
            payload["emails"] = list(emails)
        try:
            return self.call(payload, retries=0)
        except SheetError as e:
            msg = str(e)
            if "scope" in msg.lower() or "insufficient" in msg.lower() or "403" in msg:
                msg += (" | Hint: the n8n Google credential has no Drive permission for this file. Share by hand "
                        "(Share button) or re-authorise the credential 'Google Sheets (Afroz)' with the Drive scope.")
            raise SheetError(msg)
