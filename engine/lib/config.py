"""Idea Launch config loader.

Loads (in order, later wins):
  1. <repo>/.env           (API keys; never printed)
  2. engine/config.json        (defaults, committed, edit freely)
  3. engine/config.local.json  (personal overrides and the Sheets Bridge secret, gitignored)

Use `get("apollo.per_page")` style dotted lookups or `cfg()` for the whole dict.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
IDEA_LAUNCH_DIR = LIB_DIR.parent
ROOT_MARKER = ".idea-launch-root"


def find_repo_root():
    """Repo root: IDEA_LAUNCH_ROOT env var if set, else the folder holding the marker file, else the folder containing engine/."""
    ov = os.environ.get("IDEA_LAUNCH_ROOT", "").strip()
    if ov:
        return Path(ov).expanduser().resolve()
    for d in [IDEA_LAUNCH_DIR] + list(IDEA_LAUNCH_DIR.parents):
        if (d / ROOT_MARKER).exists():
            return d
    return IDEA_LAUNCH_DIR.parent  # the folder containing engine/


REPO_ROOT = find_repo_root()
PROJECT_ROOT = REPO_ROOT  # legacy name used by older code and tests

_CACHE = {}


def load_env(path=None):
    """Parse a simple KEY=VALUE .env into os.environ (does not override existing vars)."""
    p = Path(path) if path else PROJECT_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if k and v and k not in os.environ:
            os.environ[k] = v


def _deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(p):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit("config file is not valid JSON: %s (%s)" % (p, e))


def cfg(reload=False):
    if reload or "cfg" not in _CACHE:
        load_env()
        merged = _deep_merge(_read_json(IDEA_LAUNCH_DIR / "config.json"),
                             _read_json(IDEA_LAUNCH_DIR / "config.local.json"))
        _CACHE["cfg"] = merged
    return _CACHE["cfg"]


def get(dotted, default=None):
    cur = cfg()
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def env(name, required=False):
    cfg()  # ensures .env loaded
    v = os.environ.get(name, "")
    if required and not v:
        raise SystemExit("Missing %s in <repo>/.env" % name)
    return v


def lists_dir():
    return PROJECT_ROOT / get("run.lists_dir", "runs")


def bridge_settings():
    """Return (url, secret) for the Sheets Bridge. Secret lives in config.local.json."""
    base = env("BLISSGROWTH_N8N_INSTANCE_URL", required=True).rstrip("/")
    secret = (cfg().get("sheets_bridge") or {}).get("secret", "")
    if not secret:
        raise SystemExit("No Sheets Bridge secret. Expected config.local.json -> sheets_bridge.secret "
                         "(see README, section 'Sheets Bridge').")
    url = base + "/" + get("sheet.bridge_path", "webhook/idea-launch-sheets")
    return url, secret
