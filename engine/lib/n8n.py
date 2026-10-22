"""Minimal n8n REST helper (stdlib only) for deploy scripts and the activity/phone stages.

Uses BLISSGROWTH_N8N_API_KEY and BLISSGROWTH_N8N_INSTANCE_URL from <repo>/.env (never printed).
Every function that changes a workflow takes a backup first via backup_workflow().
"""
from __future__ import annotations

import json
import os
import time

import config
import net
from util import now_iso

BACKUP_DIR = config.IDEA_LAUNCH_DIR / "workflows" / "backups"


class N8nError(RuntimeError):
    pass


def base():
    return config.env("BLISSGROWTH_N8N_INSTANCE_URL", True).rstrip("/")


def api(method, path, body=None, timeout=60):
    """Return (status, parsed json or {'raw': ...})."""
    h = {"X-N8N-API-KEY": config.env("BLISSGROWTH_N8N_API_KEY", True), "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    st, _, raw = net.fetch(method, base() + "/api/v1" + path, h, data, timeout)
    try:
        return st, json.loads(raw or b"{}")
    except ValueError:
        return st, {"raw": raw[:300].decode("utf-8", "replace")}


def list_workflows():
    out, cursor = [], ""
    while True:
        st, d = api("GET", "/workflows?limit=250" + ("&cursor=" + cursor if cursor else ""))
        if st != 200:
            raise N8nError("could not list workflows (%s): %s" % (st, str(d)[:200]))
        out += d.get("data", [])
        cursor = d.get("nextCursor") or ""
        if not cursor:
            return out


def get_workflow(wid):
    st, d = api("GET", "/workflows/%s" % wid)
    if st != 200:
        raise N8nError("get workflow %s failed (%s): %s" % (wid, st, str(d)[:200]))
    return d


def backup_workflow(wid, label):
    """Save the live workflow JSON to workflows/backups/<id>-<label>-<timestamp>.json. Returns the path."""
    wf = get_workflow(wid)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    p = BACKUP_DIR / ("%s-%s-%s.json" % (wid, label, now_iso().replace(":", "")))
    p.write_text(json.dumps(wf, indent=2), encoding="utf-8")
    return str(p)


def put_workflow(wid, wf):
    """Update a workflow (name, nodes, connections, settings only). Raises on failure."""
    body = {k: wf[k] for k in ("name", "nodes", "connections", "settings") if k in wf}
    st, d = api("PUT", "/workflows/%s" % wid, body)
    if st != 200:
        raise N8nError("update workflow %s failed (%s): %s" % (wid, st, str(d)[:300]))
    return d


def set_active(wid, active):
    st, d = api("POST", "/workflows/%s/%s" % (wid, "activate" if active else "deactivate"))
    if st != 200:
        raise N8nError("%s workflow %s failed (%s): %s" % ("activate" if active else "deactivate", wid, st, str(d)[:300]))
    return bool(d.get("active"))


def webhook_url(path, test=False):
    return "%s/%s/%s" % (base(), "webhook-test" if test else "webhook", path)


def wait_until(fn, timeout_s, interval_s=10, sleep=time.sleep):
    """Poll fn() until it returns a truthy value or the timeout passes. Returns the value or None."""
    end = time.time() + timeout_s
    while time.time() < end:
        v = fn()
        if v:
            return v
        sleep(interval_s)
    return None
