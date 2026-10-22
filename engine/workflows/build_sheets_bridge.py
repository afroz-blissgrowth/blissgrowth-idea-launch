#!/usr/bin/env python3
"""Builds workflows/idea-launch-sheets-bridge.json (the n8n workflow "Idea Launch | Sheets Bridge").

Run:   python3 -I build_sheets_bridge.py            (writes the JSON next to this file)
Deploy: python3 -I deploy_sheets_bridge.py          (creates or updates the workflow, activates it)

Design notes
  * One webhook, POST /webhook/idea-launch-sheets, header auth (credential "Idea Launch Sheets
    Bridge Secret", header X-Idea-Launch-Secret). A wrong or missing secret gets 403 from n8n.
  * Every Google call is an HTTP Request node using the predefined credential
    googleSheetsOAuth2Api ("Google Sheets (Afroz)") against Sheets API v4. All values are RAW.
  * Request bodies are built inside Code nodes and passed as one JSON string, so no object
    literal ever sits inside a ={{ }} expression (the n8n "}}" parsing bug).
  * Actions: create, read, append, upsert, format, add_columns, share. Body {action, ...}; answer {ok, ...}.
  * add_columns {sheet_id, tab, headers[]}: appends the headers missing from row 1 (never reorders or
    renames), widening the grid when needed. Idempotent.
  * share {sheet_id, domain?, emails?[], role? (default writer), notify?}: Drive API permissions through the
    same Google credential. Works only if the credential carries a Drive scope for this file (n8n's Google
    Sheets OAuth credential includes drive.file, which covers files this credential created).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CRED_SHEETS = {"googleSheetsOAuth2Api": {"id": "gPjk4vAgrRfrNcPV", "name": "Google Sheets (Afroz)"}}
CRED_SECRET_ID = os.environ.get("IL_SECRET_CRED_ID", "IIY1lK9iiH18FoWR")
CRED_SECRET = {"httpHeaderAuth": {"id": CRED_SECRET_ID, "name": "Idea Launch Sheets Bridge Secret"}}
API = "https://sheets.googleapis.com/v4/spreadsheets"

PLAN_JS = r"""
const b = $input.first().json.body || {};
const action = b.action;
const fail = (msg) => [{ json: { action: 'error', error: msg } }];
const API = 'https://sheets.googleapis.com/v4/spreadsheets';
const enc = encodeURIComponent;
const quote = (t) => "'" + String(t).replace(/'/g, "''") + "'";
const valid = ['create', 'read', 'append', 'upsert', 'format', 'add_columns', 'share'];
if (!valid.includes(action)) return fail('unknown action: ' + action + ' (expected one of ' + valid.join(', ') + ')');
if (action !== 'create' && !b.sheet_id) return fail('missing sheet_id');
const clean = (v) => (v === null || v === undefined) ? '' : (typeof v === 'object' ? JSON.stringify(v) : v);

if (action === 'create') {
  if (!b.title) return fail('missing title');
  if (!Array.isArray(b.tabs) || !b.tabs.length) return fail('missing tabs [{title, headers}]');
  const sheets = b.tabs.map((t) => ({ properties: { title: t.title, gridProperties: { rowCount: t.rows || 1000, columnCount: Math.max((t.headers || []).length, 10), frozenRowCount: 1 } } }));
  return [{ json: { action, tabs: b.tabs, bodyStr: JSON.stringify({ properties: { title: b.title }, sheets }) } }];
}
if (action === 'read') {
  if (!b.tab) return fail('missing tab');
  const range = quote(b.tab) + '!' + (b.range || 'A:ZZ');
  const render = b.raw ? 'UNFORMATTED_VALUE' : 'FORMATTED_VALUE';
  return [{ json: { action, sheet_id: b.sheet_id, url: API + '/' + b.sheet_id + '/values/' + enc(range) + '?valueRenderOption=' + render } }];
}
if (action === 'append') {
  if (!b.tab) return fail('missing tab');
  if (!Array.isArray(b.values)) return fail('missing values (array of rows)');
  const values = b.values.map((r) => r.map(clean));
  const range = quote(b.tab) + '!A1';
  return [{ json: { action, sheet_id: b.sheet_id, count: values.length,
    url: API + '/' + b.sheet_id + '/values/' + enc(range) + ':append?valueInputOption=RAW&insertDataOption=INSERT_ROWS',
    bodyStr: JSON.stringify({ majorDimension: 'ROWS', values }) } }];
}
if (action === 'upsert') {
  if (!b.tab) return fail('missing tab');
  if (!b.key) return fail('missing key (header name of the unique column)');
  if (!Array.isArray(b.records)) return fail('missing records (array of objects keyed by header)');
  const range = quote(b.tab) + '!A:ZZ';
  return [{ json: { action, sheet_id: b.sheet_id, tab: b.tab, key: b.key, records: b.records,
    url: API + '/' + b.sheet_id + '/values/' + enc(range) + '?valueRenderOption=UNFORMATTED_VALUE' } }];
}
if (action === 'add_columns') {
  if (!b.tab) return fail('missing tab');
  if (!Array.isArray(b.headers) || !b.headers.length) return fail('missing headers (array of column names)');
  return [{ json: { action, sheet_id: b.sheet_id, tab: b.tab, headers: b.headers.map(String),
    propsUrl: API + '/' + b.sheet_id + '?fields=sheets.properties',
    headerUrl: API + '/' + b.sheet_id + '/values/' + enc(quote(b.tab) + '!1:1') + '?valueRenderOption=UNFORMATTED_VALUE' } }];
}
if (action === 'share') {
  const role = b.role || 'writer';
  if (!['reader', 'commenter', 'writer'].includes(role)) return fail('role must be reader, commenter or writer');
  const emails = Array.isArray(b.emails) ? b.emails.map(String).filter((e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) : [];
  const domain = b.domain ? String(b.domain).toLowerCase() : '';
  if (domain && !/^[a-z0-9.-]+\.[a-z]{2,}$/.test(domain)) return fail('invalid domain');
  if (!domain && !emails.length) return fail('share needs a domain and/or emails[]');
  const notify = b.notify === true ? 'true' : 'false';
  const base = 'https://www.googleapis.com/drive/v3/files/' + b.sheet_id + '/permissions?supportsAllDrives=true&sendNotificationEmail=' + notify;
  const items = [];
  if (domain) items.push({ json: { action, sheet_id: b.sheet_id, target: 'domain:' + domain, url: base, bodyStr: JSON.stringify({ type: 'domain', role, domain }) } });
  emails.forEach((e) => items.push({ json: { action, sheet_id: b.sheet_id, target: e, url: base, bodyStr: JSON.stringify({ type: 'user', role, emailAddress: e }) } }));
  return items;
}
// format
return [{ json: { action, sheet_id: b.sheet_id, tabs: b.tabs || null,
  url: API + '/' + b.sheet_id + '?fields=sheets.properties' } }];
"""

POST_CREATE_JS = r"""
const plan = $('Plan').first().json;
const r = $input.first().json;
if (r.error) return [{ json: { failed: true, error: r.error } }];
const API = 'https://sheets.googleapis.com/v4/spreadsheets';
const quote = (t) => "'" + String(t).replace(/'/g, "''") + "'";
const byTitle = {};
(r.sheets || []).forEach((s) => { byTitle[s.properties.title] = s.properties.sheetId; });
const data = [];
const requests = [];
const tabs = [];
for (const t of plan.tabs) {
  const sid = byTitle[t.title];
  tabs.push({ title: t.title, sheetId: sid });
  const headers = t.headers || [];
  data.push({ range: quote(t.title) + '!A1', values: [headers] });
  requests.push({ repeatCell: { range: { sheetId: sid, startRowIndex: 0, endRowIndex: 1 },
    cell: { userEnteredFormat: { textFormat: { bold: true }, backgroundColor: { red: 0.9, green: 0.9, blue: 0.9 } } },
    fields: 'userEnteredFormat(textFormat,backgroundColor)' } });
  requests.push({ updateSheetProperties: { properties: { sheetId: sid, gridProperties: { frozenRowCount: 1 } }, fields: 'gridProperties.frozenRowCount' } });
  requests.push({ autoResizeDimensions: { dimensions: { sheetId: sid, dimension: 'COLUMNS', startIndex: 0, endIndex: Math.max(headers.length, 1) } } });
}
return [{ json: {
  created: { spreadsheetId: r.spreadsheetId, url: r.spreadsheetUrl, tabs },
  headersUrl: API + '/' + r.spreadsheetId + '/values:batchUpdate',
  headersBody: JSON.stringify({ valueInputOption: 'RAW', data }),
  formatUrl: API + '/' + r.spreadsheetId + ':batchUpdate',
  formatBody: JSON.stringify({ requests }) } }];
"""

PLAN_UPSERT_JS = r"""
const plan = $('Plan').first().json;
const API = 'https://sheets.googleapis.com/v4/spreadsheets';
const enc = encodeURIComponent;
const quote = (t) => "'" + String(t).replace(/'/g, "''") + "'";
const resp = $input.first().json;
const bad = (msg) => [{ json: { failed: true, error: msg, hasUpdates: false, hasAppends: false } }];
if (resp.error) return bad('read failed: ' + (resp.error.message || JSON.stringify(resp.error)));
const vals = resp.values || [];
const headers = (vals[0] || []).map(String);
if (!headers.length) return bad('tab "' + plan.tab + '" has no header row');
const keyIdx = headers.indexOf(plan.key);
if (keyIdx < 0) return bad('key column "' + plan.key + '" not in headers of "' + plan.tab + '"');
const colLetter = (i) => { let s = ''; i += 1; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; };
const lastCol = colLetter(headers.length - 1);
const clean = (v) => (v === null || v === undefined) ? '' : (typeof v === 'object' ? JSON.stringify(v) : v);
const rowIndex = {};
for (let r = 1; r < vals.length; r++) {
  const k = String((vals[r] || [])[keyIdx] === undefined ? '' : vals[r][keyIdx]);
  if (k !== '' && !(k in rowIndex)) rowIndex[k] = r + 1;   // 1-based sheet row number
}
const unknown = new Set();
let skipped = 0;
const updRows = {};   // sheet row -> full row array
const newRows = [];   // arrays
const newIdx = {};    // key -> index in newRows
for (const rec of plan.records) {
  const k = String(rec[plan.key] === undefined || rec[plan.key] === null ? '' : rec[plan.key]);
  if (k === '') { skipped++; continue; }
  const cols = Object.keys(rec).filter((c) => { if (headers.indexOf(c) < 0) { unknown.add(c); return false; } return true; });
  if (k in rowIndex) {
    const rn = rowIndex[k];
    if (!updRows[rn]) { const base = (vals[rn - 1] || []).slice(); while (base.length < headers.length) base.push(''); updRows[rn] = base; }
    cols.forEach((c) => { updRows[rn][headers.indexOf(c)] = clean(rec[c]); });
  } else if (k in newIdx) {
    cols.forEach((c) => { newRows[newIdx[k]][headers.indexOf(c)] = clean(rec[c]); });
  } else {
    const row = headers.map(() => '');
    cols.forEach((c) => { row[headers.indexOf(c)] = clean(rec[c]); });
    newIdx[k] = newRows.length; newRows.push(row);
  }
}
const data = Object.keys(updRows).map((rn) => ({ range: quote(plan.tab) + '!A' + rn + ':' + lastCol + rn, values: [updRows[rn]] }));
return [{ json: {
  hasUpdates: data.length > 0, hasAppends: newRows.length > 0,
  updated: data.length, appended: newRows.length, skipped, unknown_columns: Array.from(unknown),
  updateUrl: API + '/' + plan.sheet_id + '/values:batchUpdate',
  updateBody: JSON.stringify({ valueInputOption: 'RAW', data }),
  appendUrl: API + '/' + plan.sheet_id + '/values/' + enc(quote(plan.tab) + '!A1') + ':append?valueInputOption=RAW&insertDataOption=INSERT_ROWS',
  appendBody: JSON.stringify({ majorDimension: 'ROWS', values: newRows }) } }];
"""

BUILD_FORMAT_JS = r"""
const plan = $('Plan').first().json;
const API = 'https://sheets.googleapis.com/v4/spreadsheets';
const r = $input.first().json;
if (r.error) return [{ json: { failed: true, error: r.error } }];
const want = plan.tabs ? plan.tabs.map((t) => (typeof t === 'string' ? { title: t } : t)) : null;
const requests = [];
const done = [];
for (const s of (r.sheets || [])) {
  const p = s.properties;
  const spec = want ? want.find((t) => t.title === p.title) : { title: p.title };
  if (!spec) continue;
  const cols = p.gridProperties.columnCount;
  requests.push({ repeatCell: { range: { sheetId: p.sheetId, startRowIndex: 0, endRowIndex: 1 },
    cell: { userEnteredFormat: { textFormat: { bold: true }, backgroundColor: { red: 0.9, green: 0.9, blue: 0.9 } } },
    fields: 'userEnteredFormat(textFormat,backgroundColor)' } });
  requests.push({ updateSheetProperties: { properties: { sheetId: p.sheetId, gridProperties: { frozenRowCount: 1 } }, fields: 'gridProperties.frozenRowCount' } });
  if (spec.widths) {
    for (const idx of Object.keys(spec.widths)) {
      requests.push({ updateDimensionProperties: { range: { sheetId: p.sheetId, dimension: 'COLUMNS', startIndex: Number(idx), endIndex: Number(idx) + 1 },
        properties: { pixelSize: spec.widths[idx] }, fields: 'pixelSize' } });
    }
  }
  done.push(p.title);
}
if (!requests.length) return [{ json: { failed: true, error: 'no matching tabs to format' } }];
return [{ json: { formatted: done, formatUrl: API + '/' + plan.sheet_id + ':batchUpdate', formatBody: JSON.stringify({ requests }) } }];
"""


COLS_PLAN_JS = r"""
const plan = $('Plan').first().json;
const API = 'https://sheets.googleapis.com/v4/spreadsheets';
const enc = encodeURIComponent;
const quote = (t) => "'" + String(t).replace(/'/g, "''") + "'";
const bad = (msg) => [{ json: { failed: true, error: msg, hasWork: false } }];
const props = $('Cols Get Props').first().json;
if (props.error) return bad('props: ' + (props.error.message || JSON.stringify(props.error)));
const sh = (props.sheets || []).find((s) => s.properties.title === plan.tab);
if (!sh) return bad('tab "' + plan.tab + '" not found');
const hr = $input.first().json;
if (hr.error) return bad('header read: ' + (hr.error.message || JSON.stringify(hr.error)));
const header = ((hr.values || [])[0] || []).map((h) => String(h).trim());
const have = new Set(header);
const missing = [];
plan.headers.forEach((h) => { if (!have.has(h) && !missing.includes(h)) missing.push(h); });
if (!missing.length) return [{ json: { hasWork: false, added: [], existing: header.length } }];
const colLetter = (i) => { let s = ''; i += 1; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; };
const sid = sh.properties.sheetId;
const width = (sh.properties.gridProperties && sh.properties.gridProperties.columnCount) || 26;
const need = header.length + missing.length;
const requests = [];
if (need > width) requests.push({ appendDimension: { sheetId: sid, dimension: 'COLUMNS', length: need - width } });
requests.push({ repeatCell: { range: { sheetId: sid, startRowIndex: 0, endRowIndex: 1, startColumnIndex: header.length, endColumnIndex: need },
  cell: { userEnteredFormat: { textFormat: { bold: true }, backgroundColor: { red: 0.9, green: 0.9, blue: 0.9 } } },
  fields: 'userEnteredFormat(textFormat,backgroundColor)' } });
return [{ json: { hasWork: true, added: missing, existing: header.length,
  structUrl: API + '/' + plan.sheet_id + ':batchUpdate', structBody: JSON.stringify({ requests }),
  writeUrl: API + '/' + plan.sheet_id + '/values/' + enc(quote(plan.tab) + '!' + colLetter(header.length) + '1') + '?valueInputOption=RAW',
  writeBody: JSON.stringify({ majorDimension: 'ROWS', values: [missing] }) } }];
"""

BUILD_RESPONSE_JS = r"""
const plan = $('Plan').first().json;
if ($('Plan').first().json.action === 'share') {
  const items = $input.all().map((i) => i.json);
  const plans = $('Plan').all().map((i) => i.json);
  const shared = items.map((r, idx) => ({ target: (plans[idx] || {}).target, ok: !r.error && !!r.id,
    id: r.id || null, error: r.error ? (r.error.message || JSON.stringify(r.error)) : null }));
  return [{ json: { ok: shared.every((x) => x.ok), action: 'share', shared,
    error: shared.every((x) => x.ok) ? undefined : shared.filter((x) => !x.ok).map((x) => x.target + ': ' + x.error).join(' | ') } }];
}
const j = $input.first().json;
const errText = (e) => (e && (e.message || (typeof e === 'string' ? e : JSON.stringify(e)))) || 'unknown error';
if (plan.action === 'error') return [{ json: { ok: false, error: plan.error } }];
if (j.failed) return [{ json: { ok: false, action: plan.action, error: errText(j.error) } }];
if (j.error) return [{ json: { ok: false, action: plan.action, error: errText(j.error) } }];
const tryNode = (name) => { try { return $(name).first().json; } catch (e) { return null; } };
if (plan.action === 'create') {
  const pc = tryNode('Post Create');
  const wh = tryNode('Write Headers');
  if (wh && wh.error) return [{ json: { ok: false, action: 'create', error: 'headers: ' + errText(wh.error), spreadsheetId: pc.created.spreadsheetId } }];
  return [{ json: { ok: true, action: 'create', spreadsheetId: pc.created.spreadsheetId, url: pc.created.url, tabs: pc.created.tabs } }];
}
if (plan.action === 'read') {
  const v = j.values || [];
  return [{ json: { ok: true, action: 'read', range: j.range, rows: v.length, values: v } }];
}
if (plan.action === 'append') {
  const u = j.updates || {};
  return [{ json: { ok: true, action: 'append', appended: u.updatedRows || plan.count, range: u.updatedRange } }];
}
if (plan.action === 'upsert') {
  const pu = tryNode('Plan Upsert');
  const wu = tryNode('Write Updates');
  if (wu && wu.error) return [{ json: { ok: false, action: 'upsert', error: 'update: ' + errText(wu.error) } }];
  return [{ json: { ok: true, action: 'upsert', updated: pu.updated, appended: pu.appended, skipped: pu.skipped, unknown_columns: pu.unknown_columns } }];
}
if (plan.action === 'format') {
  const bf = tryNode('Build Format');
  return [{ json: { ok: true, action: 'format', formatted: bf.formatted } }];
}
if (plan.action === 'add_columns') {
  const cp = tryNode('Cols Plan');
  const wr = tryNode('Cols Write Header');
  const st = tryNode('Cols Structure');
  if (cp && cp.hasWork) {
    if (st && st.error) return [{ json: { ok: false, action: 'add_columns', error: 'grid: ' + errText(st.error) } }];
    if (wr && (wr.error || !wr.updatedCells)) return [{ json: { ok: false, action: 'add_columns', error: 'header write: ' + errText(wr && wr.error ? wr.error : 'unexpected response') } }];
  }
  return [{ json: { ok: true, action: 'add_columns', added: (cp && cp.added) || [], existing: cp ? cp.existing : 0 } }];
}
return [{ json: { ok: false, error: 'unhandled action' } }];
"""


def code(name, js, pos):
    return {"parameters": {"jsCode": js.strip()}, "name": name, "type": "n8n-nodes-base.code",
            "typeVersion": 2, "position": pos}


def http(name, method, url_expr, body_expr, pos):
    p = {"method": method, "url": url_expr, "authentication": "predefinedCredentialType",
         "nodeCredentialType": "googleSheetsOAuth2Api",
         "options": {"response": {"response": {"neverError": True}}}}
    if body_expr:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body_expr})
    return {"parameters": p, "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
            "position": pos, "credentials": CRED_SHEETS}


def if_true(name, expr, pos):
    return {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                                          "conditions": [{"id": name.replace(" ", "-").lower(), "leftValue": expr, "rightValue": "",
                                                          "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                                          "combinator": "and"}, "options": {}},
            "name": name, "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": pos}


def switch_rule(action):
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                           "conditions": [{"id": "act-" + action, "leftValue": "={{ $json.action }}", "rightValue": action,
                                           "operator": {"type": "string", "operation": "equals"}}],
                           "combinator": "and"}, "renameOutput": True, "outputKey": action}


def build():
    nodes = [
        {"parameters": {"httpMethod": "POST", "path": "idea-launch-sheets", "authentication": "headerAuth",
                        "responseMode": "responseNode", "options": {}},
         "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 300],
         "webhookId": "idea-launch-sheets-bridge", "credentials": CRED_SECRET},
        code("Plan", PLAN_JS, [220, 300]),
        {"parameters": {"rules": {"values": [switch_rule(a) for a in ("create", "read", "append", "upsert", "format", "add_columns", "share")]},
                        "options": {"fallbackOutput": "extra", "renameFallbackOutput": "error"}},
         "name": "Route", "type": "n8n-nodes-base.switch", "typeVersion": 3.2, "position": [440, 300]},
        # create
        http("Create Spreadsheet", "POST", API, "={{ $json.bodyStr }}", [700, 0]),
        code("Post Create", POST_CREATE_JS, [920, 0]),
        http("Write Headers", "POST", "={{ $json.headersUrl }}", "={{ $json.headersBody }}", [1140, 0]),
        http("Format New Tabs", "POST", "={{ $('Post Create').first().json.formatUrl }}",
             "={{ $('Post Create').first().json.formatBody }}", [1360, 0]),
        # read
        http("Read Values", "GET", "={{ $json.url }}", None, [700, 160]),
        # append
        http("Append Rows", "POST", "={{ $json.url }}", "={{ $json.bodyStr }}", [700, 320]),
        # upsert
        http("Read Tab", "GET", "={{ $json.url }}", None, [700, 480]),
        code("Plan Upsert", PLAN_UPSERT_JS, [920, 480]),
        if_true("Has Updates?", "={{ $json.hasUpdates }}", [1140, 480]),
        http("Write Updates", "POST", "={{ $('Plan Upsert').first().json.updateUrl }}",
             "={{ $('Plan Upsert').first().json.updateBody }}", [1360, 420]),
        if_true("Has Appends?", "={{ $('Plan Upsert').first().json.hasAppends }}", [1580, 480]),
        http("Append New", "POST", "={{ $('Plan Upsert').first().json.appendUrl }}",
             "={{ $('Plan Upsert').first().json.appendBody }}", [1800, 420]),
        # format
        http("Get Props", "GET", "={{ $json.url }}", None, [700, 700]),
        code("Build Format", BUILD_FORMAT_JS, [920, 700]),
        http("Apply Format", "POST", "={{ $json.formatUrl }}", "={{ $json.formatBody }}", [1140, 700]),
        # add_columns
        http("Cols Get Props", "GET", "={{ $json.propsUrl }}", None, [700, 860]),
        http("Cols Get Header", "GET", "={{ $('Plan').first().json.headerUrl }}", None, [920, 860]),
        code("Cols Plan", COLS_PLAN_JS, [1140, 860]),
        if_true("Cols Has Work?", "={{ $json.hasWork }}", [1360, 860]),
        http("Cols Structure", "POST", "={{ $('Cols Plan').first().json.structUrl }}",
             "={{ $('Cols Plan').first().json.structBody }}", [1580, 800]),
        http("Cols Write Header", "PUT", "={{ $('Cols Plan').first().json.writeUrl }}",
             "={{ $('Cols Plan').first().json.writeBody }}", [1800, 800]),
        # share (one Drive permission call per Plan item)
        http("Share Permission", "POST", "={{ $json.url }}", "={{ $json.bodyStr }}", [700, 1020]),
        # response
        code("Build Response", BUILD_RESPONSE_JS, [2040, 300]),
        {"parameters": {"respondWith": "firstIncomingItem", "options": {}}, "name": "Respond",
         "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [2260, 300]},
    ]
    c = {}

    def link(a, b, out=0):
        c.setdefault(a, {"main": []})
        while len(c[a]["main"]) <= out:
            c[a]["main"].append([])
        c[a]["main"][out].append({"node": b, "type": "main", "index": 0})

    link("Webhook", "Plan"); link("Plan", "Route")
    for i, tgt in enumerate(["Create Spreadsheet", "Read Values", "Append Rows", "Read Tab", "Get Props",
                             "Cols Get Props", "Share Permission", "Build Response"]):
        link("Route", tgt, i)
    link("Create Spreadsheet", "Post Create")
    link("Post Create", "Write Headers"); link("Write Headers", "Format New Tabs"); link("Format New Tabs", "Build Response")
    link("Read Values", "Build Response"); link("Append Rows", "Build Response")
    link("Read Tab", "Plan Upsert"); link("Plan Upsert", "Has Updates?")
    link("Has Updates?", "Write Updates", 0); link("Has Updates?", "Has Appends?", 1)
    link("Write Updates", "Has Appends?")
    link("Has Appends?", "Append New", 0); link("Has Appends?", "Build Response", 1)
    link("Append New", "Build Response")
    link("Get Props", "Build Format"); link("Build Format", "Apply Format"); link("Apply Format", "Build Response")
    link("Cols Get Props", "Cols Get Header"); link("Cols Get Header", "Cols Plan"); link("Cols Plan", "Cols Has Work?")
    link("Cols Has Work?", "Cols Structure", 0); link("Cols Has Work?", "Build Response", 1)
    link("Cols Structure", "Cols Write Header"); link("Cols Write Header", "Build Response")
    link("Share Permission", "Build Response")
    link("Build Response", "Respond")
    return {"name": "Idea Launch | Sheets Bridge", "nodes": nodes, "connections": c,
            "settings": {"executionOrder": "v1"}}


if __name__ == "__main__":
    out = os.path.join(HERE, "idea-launch-sheets-bridge.json")
    with open(out, "w") as f:
        json.dump(build(), f, indent=2)
    print("wrote", out)
