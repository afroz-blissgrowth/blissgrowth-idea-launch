#!/usr/bin/env python3
"""One-time, idempotent patch of the live n8n workflow "LinkedIn Activity Checker" (id NrweLKOV7gMu54bD) so that a
caller can point ONE run at its own spreadsheet and tabs through the webhook body (contract marker IL_CONTRACT_V1):

    {"sheet_id": "...", "leads_tab": "...", "runs_tab": "..."}     (all optional, validated, default = the Config node)

Everything else (name, id, nodes, verdict rules, webhook path, INACTIVE state) is left untouched. The live workflow is
backed up first, to workflows/backups/ (gitignored).
The same three lines are in vendor/activity-checker/build_workflow_v21.py so a rebuild keeps the contract.

    python3 -I workflows/patch_activity_checker.py            (patch if needed)
    python3 -I workflows/patch_activity_checker.py --check    (report only)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import n8n  # noqa: E402

WID = "NrweLKOV7gMu54bD"
MARK = "IL_CONTRACT_V1"
ANCHOR = "return [{ json: { cfg, action: String(body.action || 'run')"
PATCH = """// IL_CONTRACT_V1: a caller (Idea Launch) may point one run at its own sheet and tabs. Validated, optional.
if (body.sheet_id && /^[A-Za-z0-9_-]{20,60}$/.test(String(body.sheet_id))) cfg.SHEET_ID = String(body.sheet_id);
if (body.leads_tab && /^[A-Za-z0-9 _.:-]{1,90}$/.test(String(body.leads_tab))) cfg.LEADS_TAB = String(body.leads_tab);
if (body.runs_tab && /^[A-Za-z0-9 _.:-]{1,90}$/.test(String(body.runs_tab))) cfg.RUNS_TAB = String(body.runs_tab);
"""


def patched(js):
    if MARK in js:
        return js, False
    if js.count(ANCHOR) != 1:
        raise SystemExit("Config node has an unexpected shape (anchor not found once). Not patching.")
    return js.replace(ANCHOR, PATCH + ANCHOR), True


def main():
    wf = n8n.get_workflow(WID)
    node = next((n for n in wf["nodes"] if n["name"] == "Config"), None)
    if not node:
        sys.exit("no Config node")
    new_js, changed = patched(node["parameters"]["jsCode"])
    print("workflow: %r active=%s contract_patched=%s" % (wf["name"], wf.get("active"), not changed))
    if "--check" in sys.argv or not changed:
        return
    b = n8n.backup_workflow(WID, "before-idea-launch-contract")
    print("backup:", b)
    node["parameters"]["jsCode"] = new_js
    try:
        n8n.put_workflow(WID, wf)
    except n8n.N8nError as e:
        # some n8n versions reject unknown settings keys: retry with the documented ones only
        wf["settings"] = {k: v for k, v in (wf.get("settings") or {}).items() if k in ("executionOrder", "callerPolicy")}
        print("retrying with reduced settings:", str(e)[:120])
        n8n.put_workflow(WID, wf)
    after = n8n.get_workflow(WID)
    print("patched. name=%r id=%s active=%s" % (after["name"], after["id"], after.get("active")))


if __name__ == "__main__":
    main()
