"""Idea Launch config loader.

Loads (in order, later wins):
  1. engine/config.json        (defaults and non-secret ids, committed, edit freely)
  2. engine/config.local.json  (personal overrides and secrets for local use, gitignored)
  3. environment variables     (ENV_OVERRIDES below; the only secret source on Claude web)
API keys come from the process environment, with <repo>/.env filling in anything not already set (never printed).

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
_DOTENV_KEYS = set()  # names that load_env() took from <repo>/.env (for the doctor's "source" report)

# env var -> (dotted config path, kind, secret). An env var that is set (non-empty) beats config.local.json and config.json.
ENV_OVERRIDES = {
    "IDEA_LAUNCH_BRIDGE_SECRET": ("sheets_bridge.secret", "str", True),
    "IDEA_LAUNCH_BRIDGE_HEADER": ("sheets_bridge.header", "str", False),
    "IDEA_LAUNCH_PHONE_WEBHOOK_PATH": ("phones.webhook_path", "str", True),
    "IDEA_LAUNCH_PHONE_DATA_TABLE_ID": ("phones.data_table_id", "str", False),
    "IDEA_LAUNCH_PHONE_WORKFLOW_ID": ("phones.workflow_id", "str", False),
    "IDEA_LAUNCH_SENDER_JAY": ("launch.senders.founders.jay", "int", False),
    "IDEA_LAUNCH_SENDER_MEELAN": ("launch.senders.founders.meelan", "int", False),
    "IDEA_LAUNCH_SENDER_ASSOCIATE": ("launch.senders.associate", "int", False),
    "IDEA_LAUNCH_MANSI_EMAIL": ("launch.mansi_email", "str", False),
}


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
            _DOTENV_KEYS.add(k)


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


def _set_dotted(d, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(d.get(part), dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value


def _apply_env_overrides(merged):
    for name, (dotted, kind, _secret) in ENV_OVERRIDES.items():
        v = os.environ.get(name, "").strip()
        if not v:
            continue
        if kind == "int":
            try:
                v = int(v)
            except ValueError:
                raise SystemExit("%s must be a whole number (a HeyReach LinkedIn account id)" % name)
        _set_dotted(merged, dotted, v)


def is_placeholder(v):
    return isinstance(v, str) and v.startswith("PASTE_")


def source_of(env_name):
    """Where the value for an ENV_OVERRIDES name comes from: 'env', '.env', 'config.local.json', 'config.json' or None (missing).
    Never returns or prints the value."""
    dotted = ENV_OVERRIDES[env_name][0]
    cfg()
    if os.environ.get(env_name, "").strip():
        return ".env" if env_name in _DOTENV_KEYS else "env"

    def look(p):
        cur = _read_json(p)
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return None if cur in (None, "") or is_placeholder(cur) else cur
    if look(IDEA_LAUNCH_DIR / "config.local.json") is not None:
        return "config.local.json"
    if look(IDEA_LAUNCH_DIR / "config.json") is not None:
        return "config.json"
    return None


def cfg(reload=False):
    if reload or "cfg" not in _CACHE:
        load_env()
        merged = _deep_merge(_read_json(IDEA_LAUNCH_DIR / "config.json"),
                             _read_json(IDEA_LAUNCH_DIR / "config.local.json"))
        _apply_env_overrides(merged)
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
        raise SystemExit("Missing environment variable %s (set it in the Claude web environment, or in <repo>/.env locally)" % name)
    return v


def lists_dir():
    return PROJECT_ROOT / get("run.lists_dir", "runs")


def bridge_settings():
    """Return (url, secret) for the Sheets Bridge. Secret: env IDEA_LAUNCH_BRIDGE_SECRET, else config.local.json."""
    base = env("BLISSGROWTH_N8N_INSTANCE_URL", required=True).rstrip("/")
    secret = (cfg().get("sheets_bridge") or {}).get("secret", "")
    if not secret or is_placeholder(secret):
        raise SystemExit("Missing environment variable IDEA_LAUNCH_BRIDGE_SECRET (the Sheets Bridge secret). "
                         "Locally you can use config.local.json -> sheets_bridge.secret instead (see README).")
    url = base + "/" + get("sheet.bridge_path", "webhook/idea-launch-sheets")
    return url, secret
