#!/usr/bin/env python3
"""Create or update the small n8n receiver "Idea Launch | Apollo Phone Webhook" and its data table "IL Phone Results".

Why: Apollo delivers phone numbers ASYNCHRONOUSLY. A phone reveal request (people/bulk_match with
reveal_phone_number=true) carries a webhook_url and Apollo POSTs the numbers there some seconds or minutes later.
This receiver stores every POST as rows in the n8n data table "IL Phone Results" (one row per person, keyed by
person_id, plus the request_id and the raw payload), and lib/phones.py polls that table through the n8n API.

Security: Apollo cannot send custom headers, so the webhook path carries a random secret suffix. It is generated
once and saved in config.local.json (gitignored) under phones.webhook_path. The workflow only stores data.
It stays ACTIVE permanently (unlike the LinkedIn checker): it is tiny and idle until Apollo calls it.

    python3 -I workflows/deploy_phone_webhook.py            (idempotent: finds table and workflow by exact name)
"""
import json
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import config  # noqa: E402
import n8n  # noqa: E402

NAME = "Idea Launch | Apollo Phone Webhook"
TABLE = "IL Phone Results"
COLUMNS = ["person_id", "request_id", "status", "phones_json", "raw_json", "received_at"]

FLATTEN_JS = r"""
const b = $input.first().json.body || {};
const rcv = new Date().toISOString();
const rid = String(b.request_id || '');
const raw = JSON.stringify(b).slice(0, 60000);
const people = Array.isArray(b.people) ? b.people : (Array.isArray(b.matches) ? b.matches : []);
if (!people.length) {
  return [{ json: { person_id: '', request_id: rid, status: String(b.status || 'unparsed'), phones_json: '', raw_json: raw, received_at: rcv } }];
}
return people.map((p, i) => ({ json: {
  person_id: String(p.id || p.person_id || ''),
  request_id: String(p.request_id || rid),
  status: String(p.status || b.status || ''),
  phones_json: JSON.stringify(p.phone_numbers || p.phones || []),
  raw_json: i === 0 ? raw : '',
  received_at: rcv } }));
"""


def build(table_id, path):
    return {"name": NAME, "settings": {"executionOrder": "v1"}, "nodes": [
        {"parameters": {"httpMethod": "POST", "path": path, "responseMode": "onReceived", "options": {}},
         "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
         "webhookId": "idea-launch-apollo-phones"},
        {"parameters": {"jsCode": FLATTEN_JS.strip()}, "name": "Flatten", "type": "n8n-nodes-base.code",
         "typeVersion": 2, "position": [240, 0]},
        {"parameters": {"operation": "insert", "dataTableId": {"__rl": True, "mode": "id", "value": table_id},
                        "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [], "schema": [],
                                    "attemptToConvertTypes": False, "convertFieldsToString": False}, "options": {}},
         "name": "Store Result", "type": "n8n-nodes-base.dataTable", "typeVersion": 1.1, "position": [480, 0]}],
        "connections": {"Webhook": {"main": [[{"node": "Flatten", "type": "main", "index": 0}]]},
                        "Flatten": {"main": [[{"node": "Store Result", "type": "main", "index": 0}]]}}}


def ensure_table():
    st, d = n8n.api("GET", "/data-tables")
    if st != 200:
        sys.exit("could not list data tables (%s): %s" % (st, str(d)[:200]))
    rows = [t for t in d.get("data", []) if t["name"] == TABLE]
    if rows:
        return rows[0]["id"]
    st, d = n8n.api("POST", "/data-tables", {"name": TABLE, "columns": [{"name": c, "type": "string"} for c in COLUMNS]})
    if st not in (200, 201):
        sys.exit("could not create data table (%s): %s" % (st, str(d)[:300]))
    print("created data table", TABLE, d.get("id"))
    return d["id"]


def save_local(path, table_id, wid):
    p = config.IDEA_LAUNCH_DIR / "config.local.json"
    cur = json.loads(p.read_text()) if p.exists() else {}
    ph = cur.setdefault("phones", {})
    ph.update({"webhook_path": path, "data_table_id": table_id, "workflow_id": wid})
    p.write_text(json.dumps(cur, indent=2) + "\n")
    os.chmod(p, 0o600)


def main():
    cfg_path = (config.cfg(True).get("phones") or {}).get("webhook_path", "")
    path = cfg_path if cfg_path.startswith("idea-launch-apollo-phones-") else "idea-launch-apollo-phones-" + secrets.token_hex(12)
    table_id = ensure_table()
    existing = [w for w in n8n.list_workflows() if w["name"] == NAME]
    if len(existing) > 1:
        sys.exit("more than one workflow named %s, resolve by hand" % NAME)
    wf = build(table_id, path)
    if existing:
        wid = existing[0]["id"]
        print("backup:", n8n.backup_workflow(wid, "before-deploy"))
        n8n.put_workflow(wid, wf)
        print("updated", wid)
    else:
        st, r = n8n.api("POST", "/workflows", wf)
        if st not in (200, 201):
            sys.exit("create failed (%s): %s" % (st, str(r)[:300]))
        wid = r["id"]
        print("created", wid)
    print("active:", n8n.set_active(wid, True))
    save_local(path, table_id, wid)
    print("workflow id:", wid, "table id:", table_id, "(webhook path saved in config.local.json)")


if __name__ == "__main__":
    main()
