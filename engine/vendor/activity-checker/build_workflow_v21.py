"""
Builds linkedin-activity-checker-v21.json, the concurrent v2.1 checker for the
Blissgrowth n8n instance. v1 and v2 (build_workflow.py, build_workflow_v2.py)
are untouched. Verdict rules (lib.js) and checkpoint helpers (lib_v2.js) are
the same files v2 uses; every Code node gets lib.js + lib_v2.js prepended.

    python3 build_workflow_v21.py                      # tabs "v21 test" / "v21 test runs"
    V21_LEADS_TAB=x V21_RUNS_TAB="x runs" python3 build_workflow_v21.py

What changed vs v2: v2 ran batches of 50 strictly one after another. v2.1
splits the pending leads into batches of 50 and deals the batches round-robin
onto up to CONCURRENCY "lanes". Every lane is its own sub-execution (dispatched
without waiting) that runs its batches one after another through the same v2
worker, so at most CONCURRENCY batches (= Apify runs) are in flight at once.
The orchestrator then polls the Runs tab until every lane has logged a
"lane_done" row (or LANE_TIMEOUT_MIN passes) and writes a run summary.

One workflow, three entry roles:
  * Orchestrator: Webhook (POST) or Manual Trigger -> Config -> ensure tabs and
    header -> Read Leads -> run lock -> Select Pending (cap) -> Apify limits ->
    Plan Lanes -> log run_start -> Dispatch Lanes (no wait) -> poll barrier ->
    Run Summary -> log run_end.
  * Lane ("Batch In" with _cfg.role = lane): unpack its leads, loop its batches
    (Run Lane Batch calls this workflow and waits), then log lane_done.
  * Worker ("Batch In", role batch): unchanged v2 worker. Per stage: build
    input -> Apify run -> log run ids -> fetch dataset -> checkpoint -> write
    rows (appendOrUpdate on linkedin_url).

Concurrency safety: each batch only updates its own rows (matched on
linkedin_url; leads are loaded before a run, so workers only update by row);
any append (Runs tab, or a lead row that was not found) uses the Sheets
values.append API (useAppend), which is atomic, so parallel writers never
land on the same row.

Webhook body (all optional):
  {"max_leads": 10}                      override MAX_LEADS_PER_RUN for this run
  {"batch_size": 10, "concurrency": 2}   override BATCH_SIZE / CONCURRENCY (capped)
  {"force": true}                        ignore the run lock (a run still in progress)
  {"action": "upsert", "rows": [{...}]}  add or edit rows (schema columns only)
  {"action": "read"}                     read the tab only (inspect via the execution)
  {"sheet_id": "...", "leads_tab": "...", "runs_tab": "..."}   point this one run at another sheet/tabs (IL_CONTRACT_V1)
"""
import json, os, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = open(os.path.join(HERE, "lib.js")).read()
LIB_V2 = open(os.path.join(HERE, "lib_v2.js")).read()

# ---------------- CONFIG: the one place to change settings ----------------
# Copied verbatim into the workflow's "Config" node; editing that node in the
# n8n UI changes the next run without a rebuild.
COLUMNS = [
    "linkedin_url", "activity_status", "active_via", "activity_reason", "activity_checked_at",
    "first_name", "last_name", "headline", "current_title", "current_company",
    "current_company_linkedin_url", "location", "country", "connections", "followers",
    "has_photo", "has_cover", "has_about", "has_headline", "jobs_count", "current_jobs_count",
    "sections_filled", "photo_changed_at", "cover_changed_at", "latest_job_start",
    "last_post_at", "last_post_url", "last_comment_at", "last_reaction_at",
    "stages_run", "scrape_error", "scrape_attempts", "batch_ref",
]
# ---- concurrency cap: 4, or less if the Apify account allows fewer runs ----
MAX_WORKERS = 4
CONCURRENCY = MAX_WORKERS
try:
    import urllib.request
    _tok = os.environ.get("APIFY_TOKEN")
    if _tok:
        _lim = json.load(urllib.request.urlopen(
            urllib.request.Request("https://api.apify.com/v2/users/me/limits",
                                   headers={"Authorization": "Bearer " + _tok}), timeout=20))["data"]
        CONCURRENCY = max(1, min(MAX_WORKERS, int(_lim["limits"]["maxConcurrentActorJobs"])))
        print(f"Apify maxConcurrentActorJobs={_lim['limits']['maxConcurrentActorJobs']} -> CONCURRENCY={CONCURRENCY}")
except Exception as e:  # build still works offline; the run-time check caps it too
    print("Apify limit check skipped:", e)

RUN_COLUMNS = ["logged_at", "batch_ref", "stage", "actor", "apify_run_id", "dataset_id",
               "status", "lead_count", "usage_usd"]
CONFIG = {
    "MAX_LEADS_PER_RUN": 500,      # leads taken per run; next run continues
    "BATCH_SIZE": 50,              # leads per batch (one worker sub-execution)
    # Batches in flight at once (= Apify runs at once). Capped at run time by
    # the Apify account's free concurrent-run slots (users/me/limits).
    "CONCURRENCY": CONCURRENCY,
    "POLL_S": 30,                  # barrier poll interval (keep under 65 s)
    "LANE_TIMEOUT_MIN": 180,       # stop waiting for lanes after this
    "LOCK_TTL_MIN": 240,           # an unfinished run_start younger than this blocks a new run
    "SHEET_ID": "1fuMaeXV-g-dy5nQ5iG1BPmI5eLYjfeuCNujc0xYjdJ4",
    # Tab pair is a build parameter: V21_LEADS_TAB / V21_RUNS_TAB env vars override.
    "LEADS_TAB": os.environ.get("V21_LEADS_TAB", "v21 test"),
    "RUNS_TAB": os.environ.get("V21_RUNS_TAB", "v21 test runs"),
    "POSTS_LIMIT_PER_SOURCE": 1,
    "POSTS_DEEP_SCRAPE": False,
    "COMMENTS_MAX_ITEMS": 1,
    "REACTIONS_MAX_ITEMS": 1,
    # 3 months (as v1): the actor filters on POST age, so a 1-month window
    # missed recent reactions to older posts. Path C still needs a reaction
    # dated within C_DAYS (30), so the verdict rule is unchanged.
    "REACTIONS_POSTED_LIMIT": "3months",   # actor enum: 24h, week, month, 3months, ...
    "APIFY_RUN_TIMEOUT_S": 3600,
    "COLUMNS": COLUMNS,
    "RUN_COLUMNS": RUN_COLUMNS,
}
# ---------------------------------------------------------------------------

GOOGLE_CRED = {"id": "gPjk4vAgrRfrNcPV", "name": "Google Sheets (Afroz)"}
APIFY_CRED = {"id": "4h7PJh6FsUfu59ag", "name": "Apify account"}
WEBHOOK_PATH = "afroz-activity-v21-8d4f2b61c7"

ACTORS = {
    "profile": ("LpVuK3Zozwuipa5bp", "LinkedIn Profile Scraper"),
    "posts": ("Wpp1BZ6yGWjySadk3", "LinkedIn Posts Scraper"),
    "comments": ("FiHYLewnJwS6GnRpo", "LinkedIn Comments Scraper"),
    "reactions": ("VMwB47uSx3g2wCcBK", "LinkedIn Profile Reactions (harvestapi)"),
}

nodes, connections = [], {}
CFG = "$('Config').first().json.cfg"          # orchestrator expressions
WCFG = "$('Batch In').first().json._cfg"      # worker expressions


def node(name, ntype, version, params, pos, **extra):
    n = {"parameters": params, "id": str(uuid.uuid4()), "name": name, "type": ntype,
         "typeVersion": version, "position": pos}
    n.update(extra)
    nodes.append(n)
    return name


def link(a, b, out=0):
    connections.setdefault(a, {"main": []})
    while len(connections[a]["main"]) <= out:
        connections[a]["main"].append([])
    connections[a]["main"][out].append({"node": b, "type": "main", "index": 0})


def code(name, body, pos, lib=True, **extra):
    js = (LIB + "\n\n" + LIB_V2 + "\n\n" if lib else "") + body.strip() + "\n"
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": js}, pos, **extra)


def if_true(name, expr, pos):
    return node(name, "n8n-nodes-base.if", 2.2, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": str(uuid.uuid4()), "leftValue": "={{ " + expr + " }}",
                            "rightValue": "", "operator": {"type": "boolean", "operation": "true",
                                                           "singleValue": True}}],
            "combinator": "and"},
        "options": {}}, pos)


def gapi(name, method, url, pos, body=None):
    p = {"method": method, "url": url, "authentication": "predefinedCredentialType",
         "nodeCredentialType": "googleSheetsOAuth2Api", "options": {}}
    if body:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    return node(name, "n8n-nodes-base.httpRequest", 4.2, p, pos,
                credentials={"googleSheetsOAuth2Api": GOOGLE_CRED})


def sheet_write(name, tab_expr, pos, operation="appendOrUpdate", doc_expr=None):
    p = {"operation": operation,
         "documentId": {"__rl": True, "mode": "id", "value": "={{ " + doc_expr + " }}"},
         "sheetName": {"__rl": True, "mode": "name", "value": "={{ " + tab_expr + " }}"},
         # Auto-map with an empty schema: the node writes only the keys each item
         # carries and skips the positional header check that broke v1
         # ("Column names were updated after the node's setup"). The header row
         # is created/extended from COLUMNS at the start of every run.
         "columns": {"mappingMode": "autoMapInputData", "value": {}, "schema": [],
                     "matchingColumns": ["linkedin_url"] if operation == "appendOrUpdate" else [],
                     "attemptToConvertTypes": False, "convertFieldsToString": False},
         # useAppend: new rows go through values.append (atomic), so parallel
         # batches never compute the same "next empty row".
         "options": {"cellFormat": "RAW", "handlingExtraData": "ignoreIt", "useAppend": True}}
    return node(name, "n8n-nodes-base.googleSheets", 4.7, p, pos,
                credentials={"googleSheetsOAuth2Api": GOOGLE_CRED}, retryOnFail=True,
                maxTries=3, waitBetweenTries=5000)


# =============================== orchestrator ===============================
node("Webhook", "n8n-nodes-base.webhook", 2, {
    "httpMethod": "POST", "path": WEBHOOK_PATH, "responseMode": "onReceived", "options": {}},
    [0, 200], webhookId=str(uuid.uuid4()))
node("Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 400])

code("Config", """
// ===== CONFIG (edit here; webhook body {"max_leads": N} overrides the cap for one run) =====
const CONFIG_V2 = %s;
// ==========================================================================================
let body = {};
try { body = $('Webhook').first().json.body || {}; } catch (e) {}
const cfg = { ...CONFIG_V2 };
if (body.max_leads !== undefined && body.max_leads !== '') cfg.MAX_LEADS_PER_RUN = Math.max(0, parseInt(body.max_leads, 10) || 0);
if (body.batch_size) cfg.BATCH_SIZE = Math.max(1, Math.min(100, parseInt(body.batch_size, 10) || cfg.BATCH_SIZE));
if (body.concurrency) cfg.CONCURRENCY = Math.max(1, Math.min(CONFIG_V2.CONCURRENCY, parseInt(body.concurrency, 10) || 1));
// IL_CONTRACT_V1: a caller (Idea Launch) may point one run at its own sheet and tabs. Validated, optional.
if (body.sheet_id && /^[A-Za-z0-9_-]{20,60}$/.test(String(body.sheet_id))) cfg.SHEET_ID = String(body.sheet_id);
if (body.leads_tab && /^[A-Za-z0-9 _.:-]{1,90}$/.test(String(body.leads_tab))) cfg.LEADS_TAB = String(body.leads_tab);
if (body.runs_tab && /^[A-Za-z0-9 _.:-]{1,90}$/.test(String(body.runs_tab))) cfg.RUNS_TAB = String(body.runs_tab);
return [{ json: { cfg, action: String(body.action || 'run'), rows: Array.isArray(body.rows) ? body.rows : [],
  force: body.force === true, exec: $execution.id, started_at: new Date().toISOString() } }];
""" % json.dumps(CONFIG, indent=2), [220, 300], lib=False)
link("Webhook", "Config")
link("Run Manually", "Config")

gapi("Get Sheet Info", "GET",
     "=https://sheets.googleapis.com/v4/spreadsheets/{{ " + CFG + ".SHEET_ID }}?fields=sheets.properties",
     [440, 300])
code("Plan Tabs", """
const cfg = $('Config').first().json.cfg;
const have = new Set(($input.first().json.sheets || []).map(s => s.properties.title));
const requests = [cfg.LEADS_TAB, cfg.RUNS_TAB].filter(t => !have.has(t))
  .map(title => ({ addSheet: { properties: { title, gridProperties: { rowCount: 1000, columnCount: 60 } } } }));
return [{ json: { skip: requests.length === 0, requests } }];
""", [660, 300], lib=False)
if_true("Tabs Exist?", "$json.skip", [880, 300])
gapi("Add Tabs", "POST",
     "=https://sheets.googleapis.com/v4/spreadsheets/{{ " + CFG + ".SHEET_ID }}:batchUpdate",
     [1100, 400], body="={{ JSON.stringify({ requests: $json.requests }) }}")
gapi("Get Headers", "GET",
     "=https://sheets.googleapis.com/v4/spreadsheets/{{ " + CFG + ".SHEET_ID }}/values:batchGet"
     "?ranges={{ encodeURIComponent(\"'\" + " + CFG + ".LEADS_TAB + \"'!1:1\") }}"
     "&ranges={{ encodeURIComponent(\"'\" + " + CFG + ".RUNS_TAB + \"'!1:1\") }}",
     [1320, 300])
code("Plan Headers", """
// Append any schema column missing from row 1 (never reorders or renames).
const cfg = $('Config').first().json.cfg;
const info = {};
for (const s of ($('Get Sheet Info').first().json.sheets || [])) info[s.properties.title] = s.properties;
try { for (const r of ($('Add Tabs').first().json.replies || [])) if (r.addSheet) info[r.addSheet.properties.title] = r.addSheet.properties; } catch (e) {}
const ranges = $input.first().json.valueRanges || [];
const colName = n => { let s = ''; for (n += 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s; return s; };
const data = [];
[[cfg.LEADS_TAB, cfg.COLUMNS, ranges[0]], [cfg.RUNS_TAB, cfg.RUN_COLUMNS, ranges[1]]].forEach(([tab, cols, vr]) => {
  const header = ((vr && vr.values && vr.values[0]) || []).map(h => String(h).trim());
  const missing = cols.filter(c => !header.includes(c));
  if (!missing.length) return;
  const width = (info[tab] && info[tab].gridProperties && info[tab].gridProperties.columnCount) || 26;
  if (header.length + missing.length > width)
    throw new Error(`Tab "${tab}" needs ${header.length + missing.length} columns but has ${width}. Add columns, then rerun.`);
  data.push({ range: `'${tab}'!${colName(header.length)}1`, values: [missing] });
});
return [{ json: { skip: data.length === 0, data } }];
""", [1540, 300], lib=False)
if_true("Header OK?", "$json.skip", [1760, 300])
gapi("Write Header", "POST",
     "=https://sheets.googleapis.com/v4/spreadsheets/{{ " + CFG + ".SHEET_ID }}/values:batchUpdate",
     [1980, 400], body="={{ JSON.stringify({ valueInputOption: 'RAW', data: $json.data }) }}")
if_true("Upsert?", "$('Config').first().json.action === 'upsert'", [2200, 300])

link("Config", "Get Sheet Info")
link("Get Sheet Info", "Plan Tabs")
link("Plan Tabs", "Tabs Exist?")
link("Tabs Exist?", "Get Headers", 0)
link("Tabs Exist?", "Add Tabs", 1)
link("Add Tabs", "Get Headers")
link("Get Headers", "Plan Headers")
link("Plan Headers", "Header OK?")
link("Header OK?", "Upsert?", 0)
link("Header OK?", "Write Header", 1)
link("Write Header", "Upsert?")

# --- upsert path (load leads / manual edits) ---
code("Upsert Rows", """
const { cfg, rows } = $('Config').first().json;
const cols = new Set(cfg.COLUMNS);
return rows.filter(r => r && String(r.linkedin_url || '').includes('linkedin.com/in/')).map(r => {
  const o = {};
  for (const [k, v] of Object.entries(r)) if (cols.has(k)) o[k] = v;
  return { json: o };
});
""", [2420, 100], lib=False)
sheet_write("Write Upserts", CFG + ".LEADS_TAB", [2640, 100], doc_expr=CFG + ".SHEET_ID")
link("Upsert?", "Upsert Rows", 0)
link("Upsert Rows", "Write Upserts")

# --- run path ---
node("Read Leads", "n8n-nodes-base.googleSheets", 4.7, {
    "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".SHEET_ID }}"},
    "sheetName": {"__rl": True, "mode": "name", "value": "={{ " + CFG + ".LEADS_TAB }}"},
    "options": {}}, [2420, 400], credentials={"googleSheetsOAuth2Api": GOOGLE_CRED},
    executeOnce=True, alwaysOutputData=True)
link("Upsert?", "Read Leads", 1)
code("Select Pending", """
// Pending = LinkedIn URL, blank activity_status, scrape_attempts < MAX_ATTEMPTS
// (lib.js pendingRows). Take at most MAX_LEADS_PER_RUN; the rest wait for the
// next run. action "read" stops here.
const { cfg, action, exec } = $('Config').first().json;
if (action === 'read') return [];
const cols = cfg.COLUMNS;
const pending = pendingRows().slice(0, cfg.MAX_LEADS_PER_RUN);
const slim = { ...cfg, COLUMNS: cols };
delete slim.RUN_COLUMNS;
return pending.map((r, i) => {
  const o = {};
  for (const c of cols) if (r[c] !== undefined && r[c] !== '') o[c] = r[c];
  o._cfg = { ...slim, role: 'batch', batch_ref: exec + '-b' + (Math.floor(i / cfg.BATCH_SIZE) + 1) };
  return { json: o };
});
""", [3080, 600])

def sheet_read(name, tab_expr, pos):
    return node(name, "n8n-nodes-base.googleSheets", 4.7, {
        "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".SHEET_ID }}"},
        "sheetName": {"__rl": True, "mode": "name", "value": "={{ " + tab_expr + " }}"},
        "options": {}}, pos, credentials={"googleSheetsOAuth2Api": GOOGLE_CRED},
        executeOnce=True, alwaysOutputData=True, retryOnFail=True, maxTries=3, waitBetweenTries=5000)


sheet_read("Read Runs Lock", CFG + ".RUNS_TAB", [2640, 600])
code("Check Lock", """
// One run at a time: a run_start with no run_end, younger than LOCK_TTL_MIN,
// blocks this run (two runs would scrape the same pending leads twice).
// Webhook body {"force": true} overrides.
const { cfg, action, force, exec } = $('Config').first().json;
if (action === 'read' || force) return [{ json: { ok: true } }];
const rows = $input.all().map(i => i.json);
const ended = new Set(rows.filter(r => r.stage === 'run_end').map(r => String(r.batch_ref)));
const open = rows.filter(r => r.stage === 'run_start' && !ended.has(String(r.batch_ref)) && String(r.batch_ref) !== String(exec)
  && Date.now() - Date.parse(r.logged_at) < cfg.LOCK_TTL_MIN * 60000);
if (open.length) throw new Error('Run ' + open[0].batch_ref + ' (started ' + open[0].logged_at + ') is still in progress. Wait for it, or send {"force": true}.');
return [{ json: { ok: true } }];
""", [2860, 600], lib=False)
link("Read Leads", "Read Runs Lock")
link("Read Runs Lock", "Check Lock")
link("Check Lock", "Select Pending")

node("Apify Limits", "n8n-nodes-base.httpRequest", 4.2, {
    "method": "GET", "url": "https://api.apify.com/v2/users/me/limits",
    "authentication": "predefinedCredentialType", "nodeCredentialType": "apifyApi", "options": {}},
    [3300, 600], credentials={"apifyApi": APIFY_CRED}, executeOnce=True, alwaysOutputData=True,
    onError="continueRegularOutput")
link("Select Pending", "Apify Limits")

code("Plan Lanes", """
// Batches of BATCH_SIZE, dealt round-robin onto L lanes. L = CONCURRENCY,
// capped by free Apify run slots (each batch runs one actor at a time) and by
// the number of batches. Each lane's leads stay in batch order, so the lane
// re-splits them into exactly these batches.
const { cfg, exec } = $('Config').first().json;
const leads = $('Select Pending').all().map(i => i.json);
const lim = ($input.first() || {}).json || {};
let free = Infinity;
try { free = lim.data.limits.maxConcurrentActorJobs - lim.data.current.activeActorJobCount; } catch (e) {}
const nBatches = Math.ceil(leads.length / cfg.BATCH_SIZE);
const L = Math.max(1, Math.min(cfg.CONCURRENCY, nBatches, isFinite(free) ? Math.max(1, free) : cfg.CONCURRENCY));
const lanes = Array.from({ length: L }, () => []);
leads.forEach((r, i) => lanes[Math.floor(i / cfg.BATCH_SIZE) % L].push(r));
return lanes.map((ls, l) => ({ json: {
  _cfg: { ...ls[0]._cfg, role: 'lane', lane_ref: exec + '-L' + (l + 1) },
  leads: ls, lanes: L, batches: Math.ceil(ls.length / cfg.BATCH_SIZE),
  apify_free_slots: isFinite(free) ? free : 'unknown' } }));
""", [3520, 600], lib=False)
link("Apify Limits", "Plan Lanes")

code("Run Start Row", """
const { exec, started_at } = $('Config').first().json;
const lanes = $input.all().map(i => i.json);
return [{ json: { logged_at: started_at, batch_ref: String(exec), stage: 'run_start', actor: '', apify_run_id: '', dataset_id: '',
  status: 'lanes=' + lanes.length + ' batches=' + lanes.reduce((a, l) => a + l.batches, 0),
  lead_count: lanes.reduce((a, l) => a + l.leads.length, 0), usage_usd: '' } }];
""", [3740, 600], lib=False)
sheet_write("Log Run Start", CFG + ".RUNS_TAB", [3960, 600], operation="append", doc_expr=CFG + ".SHEET_ID")
code("Lane Items", "return $('Plan Lanes').all().map(i => ({ json: { _cfg: i.json._cfg, leads: i.json.leads } }));",
     [4180, 600], lib=False)
node("Dispatch Lanes", "n8n-nodes-base.executeWorkflow", 1.2, {
    "source": "database",
    "workflowId": {"__rl": True, "mode": "id", "value": "={{ $workflow.id }}"},
    "mode": "each",
    "options": {"waitForSubWorkflow": False}}, [4400, 600], executeOnce=False)
link("Plan Lanes", "Run Start Row")
link("Run Start Row", "Log Run Start")
link("Log Run Start", "Lane Items")
link("Lane Items", "Dispatch Lanes")

node("Poll Wait", "n8n-nodes-base.wait", 1.1, {
    "resume": "timeInterval", "amount": "={{ " + CFG + ".POLL_S }}", "unit": "seconds"},
    [4620, 600], webhookId=str(uuid.uuid4()))
code("Poll Once", "return [{ json: { poll: true } }];", [4840, 600], lib=False)
sheet_read("Read Runs", CFG + ".RUNS_TAB", [5060, 600])
code("Check Barrier", """
// Done when every lane of this run has logged lane_done, or on timeout.
const { cfg, started_at } = $('Config').first().json;
const refs = $('Plan Lanes').all().map(i => i.json._cfg.lane_ref);
const done = new Set($input.all().map(i => i.json).filter(r => r.stage === 'lane_done').map(r => String(r.batch_ref)));
const missing = refs.filter(r => !done.has(r));
const elapsed = (Date.now() - Date.parse(started_at)) / 1000;
const timedOut = elapsed > cfg.LANE_TIMEOUT_MIN * 60;
return [{ json: { done: missing.length === 0 || timedOut, timed_out: missing.length > 0 && timedOut, missing, elapsed_s: Math.round(elapsed) } }];
""", [5280, 600], lib=False)
if_true("All Lanes Done?", "$json.done", [5500, 600])
link("Dispatch Lanes", "Poll Wait")
link("Poll Wait", "Poll Once")
link("Poll Once", "Read Runs")
link("Read Runs", "Check Barrier")
link("Check Barrier", "All Lanes Done?")
link("All Lanes Done?", "Poll Wait", 1)

sheet_read("Read Final", CFG + ".LEADS_TAB", [5720, 500])
code("Run Summary", """
const { exec, started_at } = $('Config').first().json;
const bar = $('Check Barrier').last().json;
const plan = $('Plan Lanes').all().map(i => i.json);
const mine = $input.all().map(i => i.json).filter(r => String(r.batch_ref || '').startsWith(exec + '-b'));
const counts = {};
for (const r of mine) { const s = r.activity_status || (r.scrape_error ? 'retry' : 'pending'); counts[s] = (counts[s] || 0) + 1; }
let runs = [];
try { runs = $('Read Runs').all().map(i => i.json); } catch (e) {}
const usd = runs.filter(r => String(r.batch_ref || '').startsWith(exec + '-b')).reduce((a, r) => a + (Number(r.usage_usd) || 0), 0);
const ended_at = new Date().toISOString();
return [{ json: { exec, started_at, ended_at, elapsed_s: Math.round((Date.parse(ended_at) - Date.parse(started_at)) / 1000),
  lanes: plan.length, batches: plan.reduce((a, l) => a + l.batches, 0), leads: plan.reduce((a, l) => a + l.leads.length, 0),
  written: mine.length, counts, usage_usd: Math.round(usd * 1000) / 1000, timed_out: bar.timed_out, missing_lanes: bar.missing,
  cap: $('Config').first().json.cfg.MAX_LEADS_PER_RUN } }];
""", [5940, 500], lib=False)
code("Run End Row", """
const s = $input.first().json;
return [{ json: { logged_at: s.ended_at, batch_ref: String(s.exec), stage: 'run_end', actor: '', apify_run_id: '', dataset_id: '',
  status: (s.timed_out ? 'TIMED OUT (lanes ' + s.missing_lanes.join(',') + ') ' : 'done ') + 'elapsed_s=' + s.elapsed_s + ' ' + JSON.stringify(s.counts),
  lead_count: s.leads, usage_usd: s.usage_usd } }];
""", [6160, 500], lib=False)
sheet_write("Log Run End", CFG + ".RUNS_TAB", [6380, 500], operation="append", doc_expr=CFG + ".SHEET_ID")
link("All Lanes Done?", "Read Final", 0)
link("Read Final", "Run Summary")
link("Run Summary", "Run End Row")
link("Run End Row", "Log Run End")

# ================================= worker =================================
node("Batch In", "n8n-nodes-base.executeWorkflowTrigger", 1.1, {"inputSource": "passthrough"}, [0, 900])
node("Lane?", "n8n-nodes-base.if", 2.2, {
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{"id": str(uuid.uuid4()), "leftValue": "={{ " + WCFG + ".role }}",
                        "rightValue": "lane", "operator": {"type": "string", "operation": "equals"}}],
        "combinator": "and"},
    "options": {}}, [110, 900], executeOnce=True)
link("Batch In", "Lane?")

# ---- lane: run this lane's batches one after another ----
LY = 600
code("Unpack Lane", """
// One lane item -> its leads (each carries its own _cfg with batch_ref).
return ($('Batch In').first().json.leads || []).map(r => ({ json: r }));
""", [220, LY], lib=False)
node("Lane Batches", "n8n-nodes-base.splitInBatches", 3,
     {"batchSize": "={{ " + WCFG + ".BATCH_SIZE }}", "options": {}}, [440, LY])
node("Run Lane Batch", "n8n-nodes-base.executeWorkflow", 1.2, {
    "source": "database",
    "workflowId": {"__rl": True, "mode": "id", "value": "={{ $workflow.id }}"},
    "mode": "once",
    "options": {"waitForSubWorkflow": True}}, [660, LY + 100], onError="continueRegularOutput")
code("Lane Done Row", """
const c = $('Batch In').first().json._cfg;
const res = $input.all().map(i => i.json);
const failed = res.filter(r => r.error).length;
return [{ json: { logged_at: new Date().toISOString(), batch_ref: c.lane_ref, stage: 'lane_done', actor: '', apify_run_id: '', dataset_id: '',
  status: failed ? failed + ' batch(es) errored' : 'ok', lead_count: ($('Batch In').first().json.leads || []).length, usage_usd: '' } }];
""", [660, LY - 100], lib=False)
sheet_write("Log Lane Done", WCFG + ".RUNS_TAB", [880, LY - 100], operation="append", doc_expr=WCFG + ".SHEET_ID")
link("Lane?", "Unpack Lane", 0)
link("Unpack Lane", "Lane Batches")
link("Lane Batches", "Lane Done Row", 0)
link("Lane Batches", "Run Lane Batch", 1)
link("Run Lane Batch", "Lane Batches")
link("Lane Done Row", "Log Lane Done")


def apify_run(name, actor, pos):
    aid, label = ACTORS[actor]
    return node(name, "@apify/n8n-nodes-apify.apify", 1, {
        "resource": "Actors", "operation": "Run actor",
        "actorId": {"__rl": True, "value": aid, "mode": "id", "cachedResultName": label},
        "customBody": "={{ $json.body }}",
        "waitForFinish": True,
        "timeout": "={{ " + WCFG + ".APIFY_RUN_TIMEOUT_S }}",
    }, pos, credentials={"apifyApi": APIFY_CRED}, alwaysOutputData=True,
        onError="continueRegularOutput")


def apify_items(name, run_node, pos):
    return node(name, "@apify/n8n-nodes-apify.apify", 1, {
        "resource": "Datasets", "operation": "Get items",
        "datasetId": "={{ $('" + run_node + "').first().json.defaultDatasetId }}",
        "offset": 0, "limit": 5000, "options": {},
    }, pos, credentials={"apifyApi": APIFY_CRED}, retryOnFail=True, maxTries=3,
        waitBetweenTries=5000, alwaysOutputData=True, onError="continueRegularOutput")


STAGE_DEF = [
    # stage, Label, lib stage number for the checkpoint, build body
    ("profile", "Profiles", 1, """
// Leads without a profile checkpoint yet.
const cfg = cfgV2();
const urls = batchRows().filter(r => !stagesOf(r).has('profile')).map(r => r.linkedin_url);
return stageBody(urls, q => ({ profileScraperMode: 'Profile details no email ($4 per 1k)', queries: q }));
"""),
    ("posts", "Posts", 1, """
// Posts for every floor-passing, non-Shell lead (A/B Actives included, as v1)
// whose posts stage has not run yet.
const cfg = cfgV2();
const { recs, ctx } = evaluateV2(1);
const done = ctx.doneKeys('posts');
const urls = recs.filter(r => (r.activity_status === 'Active' || r._decided === false) && !done.has(key(r.linkedin_url)))
  .map(r => r.linkedin_url);
const since = new Date(NOW - CONFIG.C_DAYS * DAY).toISOString().slice(0, 10);
return stageBody(urls, u => ({ urls: u, limitPerSource: cfg.POSTS_LIMIT_PER_SOURCE, scrapeUntil: since, deepScrape: cfg.POSTS_DEEP_SCRAPE }));
"""),
    ("comments", "Comments", 2, """
// Comments only for leads still undecided after posts.
const cfg = cfgV2();
const { recs, ctx } = evaluateV2(1);
const done = ctx.doneKeys('comments');
const urls = recs.filter(r => r._decided === false && !done.has(key(r.linkedin_url))).map(r => r.linkedin_url);
return stageBody(urls, p => ({ profiles: p, maxItems: cfg.COMMENTS_MAX_ITEMS }));
"""),
    ("reactions", "Reactions", 3, """
// Reactions only for leads still undecided after comments.
const cfg = cfgV2();
const { recs, ctx } = evaluateV2(2);
const done = ctx.doneKeys('reactions');
const urls = recs.filter(r => r._decided === false && !done.has(key(r.linkedin_url))).map(r => r.linkedin_url);
return stageBody(urls, p => ({ profiles: p, maxItems: cfg.REACTIONS_MAX_ITEMS, postedLimit: cfg.REACTIONS_POSTED_LIMIT }));
"""),
]

prev = "Batch In"
y = 900
FIRST = True
for i, (stage, label, lib_stage, build_js) in enumerate(STAGE_DEF):
    x = 220 + i * 1760
    b = code(f"Build {label}", build_js, [x, y])
    s = if_true(f"Skip {label}?", "$json.skip", [x + 220, y])
    r = apify_run(f"Run {label}", stage, [x + 440, y + 120])
    lg = code(f"Log {label} Run", f"return runLog('{stage}');", [x + 660, y + 120])
    ap = sheet_write(f"Append {label} Run", WCFG + ".RUNS_TAB", [x + 880, y + 120],
                     operation="append", doc_expr=WCFG + ".SHEET_ID")
    gi = apify_items(f"Get {label}", f"Run {label}", [x + 1100, y + 120])
    cp = code(f"Checkpoint {label}", f"return checkpoint('{stage}', {lib_stage});", [x + 1320, y])
    wr = sheet_write(f"Write {label}", WCFG + ".LEADS_TAB", [x + 1540, y], doc_expr=WCFG + ".SHEET_ID")
    if FIRST:
        link("Lane?", b, 1)
        FIRST = False
    else:
        link(prev, b)
    link(b, s)
    link(s, cp, 0)
    link(s, r, 1)
    link(r, lg)
    link(lg, ap)
    link(ap, gi)
    link(gi, cp)
    link(cp, wr)
    prev = wr

code("Batch Summary", """
// One small item back to the orchestrator (keeps the parent execution light).
const rows = rawSafe('Checkpoint Reactions');
const counts = {};
for (const r of rows) { const s = r.activity_status || (r.scrape_error ? 'retry' : 'pending'); counts[s] = (counts[s] || 0) + 1; }
return [{ json: { batch_ref: cfgV2().batch_ref, leads: rows.length, counts } }];
""", [220 + 4 * 1760, y])
link(prev, "Batch Summary")

wf = {
    "name": "[Afroz] LinkedIn Activity Checker v2.1",
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "callerPolicy": "workflowsFromSameOwner"},
}
out = os.path.join(HERE, "linkedin-activity-checker-v21.json")
json.dump(wf, open(out, "w"), indent=2)
print(f"wrote {out}: {len(nodes)} nodes")
