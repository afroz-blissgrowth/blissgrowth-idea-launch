#!/usr/bin/env python3
"""Idea Launch doctor: checks that this clone is ready to run. Never prints key values.

    python3 -I engine/bin/doctor.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402
import net  # noqa: E402

OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"
results = []


def say(level, msg):
    results.append(level)
    print("%s %s" % (level, msg))


def main():
    config.cfg()
    print("Idea Launch doctor")
    print("Repo root: %s\n" % config.REPO_ROOT)

    v = sys.version_info
    say(OK if v >= (3, 9) else FAIL, "Python %d.%d.%d (need 3.9 or newer)" % v[:3])

    envp = config.REPO_ROOT / ".env"
    say(OK if envp.exists() else FAIL, ".env present at the repo root" if envp.exists() else ".env missing (copy .env.example to .env and fill it)")

    for k, why in (("APOLLO_API_KEY", "Apollo"), ("BLISSGROWTH_N8N_API_KEY", "n8n API"),
                   ("BLISSGROWTH_N8N_INSTANCE_URL", "n8n URL"), ("HEYREACH_API_KEY", "HeyReach"),
                   ("MILLIONVERIFIER_API_KEY", "MillionVerifier, presence only, not tested because a test costs a credit")):
        say(OK if os.environ.get(k) else FAIL, "%s set (%s)" % (k, why) if os.environ.get(k) else "%s missing (%s)" % (k, why))

    lp = config.IDEA_LAUNCH_DIR / "config.local.json"
    local = {}
    if lp.exists():
        try:
            local = json.loads(lp.read_text(encoding="utf-8"))
            say(OK, "engine/config.local.json present and valid JSON")
        except ValueError:
            say(FAIL, "engine/config.local.json is not valid JSON")
    else:
        say(FAIL, "engine/config.local.json missing (copy engine/config.local.example.json and fill it)")

    secret = (local.get("sheets_bridge") or {}).get("secret", "")
    real = bool(secret) and not secret.startswith("PASTE_")
    say(OK if real else FAIL, "sheets_bridge.secret filled in" if real else "sheets_bridge.secret not filled in")
    ph = (local.get("phones") or {}).get("webhook_path", "")
    say(OK if ph and not ph.startswith("PASTE_") else WARN,
        "phones.webhook_path filled in" if ph and not ph.startswith("PASTE_") else "phones.webhook_path not filled in (needed for /iv-phones)")
    snd = ((local.get("launch") or {}).get("senders") or {})
    have = bool((snd.get("founders") or {}).get("jay")) and bool((snd.get("founders") or {}).get("meelan")) and bool(snd.get("associate"))
    say(OK if have else WARN, "launch.senders filled in" if have else "launch.senders not filled in (needed for /iv-launch; ids via bin/launch_run.py accounts)")
    me = (local.get("launch") or {}).get("mansi_email", "")
    say(OK if me and "example.com" not in me else WARN,
        "launch.mansi_email filled in" if me and "example.com" not in me else "launch.mansi_email not set (needed for the call sheet)")

    base = os.environ.get("BLISSGROWTH_N8N_INSTANCE_URL", "").rstrip("/")
    if base and real:
        try:
            url = base + "/" + config.get("sheet.bridge_path", "webhook/idea-launch-sheets")
            hdr = (local.get("sheets_bridge") or {}).get("header", "X-Idea-Launch-Secret")
            st, _, _ = net.fetch("POST", url, {hdr: secret, "Content-Type": "application/json"},
                                 json.dumps({"action": "read"}).encode(), 30)
            if st == 403:
                say(FAIL, "n8n bridge reachable but refused the secret (403): wrong sheets_bridge.secret")
            elif st == 404:
                say(FAIL, "n8n bridge webhook not found (404): workflow 'Idea Launch | Sheets Bridge' inactive or wrong URL")
            elif st < 500:
                say(OK, "n8n bridge reachable and the secret is accepted (HTTP %d)" % st)
            else:
                say(FAIL, "n8n bridge answered HTTP %d" % st)
        except Exception as e:
            say(FAIL, "n8n bridge not reachable (%s)" % type(e).__name__)
    else:
        say(WARN, "n8n bridge check skipped (needs BLISSGROWTH_N8N_INSTANCE_URL and the bridge secret)")

    if base and os.environ.get("BLISSGROWTH_N8N_API_KEY"):
        try:
            st, _, _ = net.fetch("GET", base + "/api/v1/workflows?limit=1",
                                 {"X-N8N-API-KEY": os.environ["BLISSGROWTH_N8N_API_KEY"]}, None, 30)
            say(OK if st == 200 else FAIL, "n8n API key accepted" if st == 200 else "n8n API key refused or URL wrong (HTTP %d)" % st)
        except Exception as e:
            say(FAIL, "n8n API not reachable (%s)" % type(e).__name__)

    k = os.environ.get("APOLLO_API_KEY")
    if k:
        try:
            st, _, _ = net.fetch("POST", config.get("apollo.base_url", "https://api.apollo.io/api/v1").rstrip("/") + "/usage_stats/api_usage_stats",
                                 {"x-api-key": k, "Content-Type": "application/json", "Accept": "application/json"}, b"{}", 30)
            if st == 200:
                say(OK, "Apollo key valid (free usage-stats call)")
            elif st in (401, 403):
                say(WARN, "Apollo refused the usage-stats call (HTTP %d): key invalid, or this endpoint needs a master key" % st)
            else:
                say(WARN, "Apollo usage-stats call answered HTTP %d" % st)
        except Exception as e:
            say(WARN, "Apollo not reachable (%s)" % type(e).__name__)

    k = os.environ.get("HEYREACH_API_KEY")
    if k:
        try:
            st, _, _ = net.fetch("GET", "https://api.heyreach.io/api/public/auth/CheckApiKey", {"X-API-KEY": k}, None, 30)
            say(OK if st == 200 else WARN, "HeyReach key valid" if st == 200 else "HeyReach key check answered HTTP %d" % st)
        except Exception as e:
            say(WARN, "HeyReach not reachable (%s)" % type(e).__name__)

    rd = config.lists_dir()
    say(OK if rd.exists() else WARN, "runs folder exists" if rd.exists() else "runs folder missing (created on first run)")

    print("\n%d ok, %d warnings, %d failures" % (results.count(OK), results.count(WARN), results.count(FAIL)))
    if results.count(FAIL):
        print("Fix the [FAIL] lines first. Get missing secrets from Afroz securely (never Slack).")
    sys.exit(1 if results.count(FAIL) else 0)


if __name__ == "__main__":
    main()
