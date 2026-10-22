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
    print("(.env is optional: on Claude web every value comes from the environment)")
    say(OK if envp.exists() else WARN, ".env present at the repo root" if envp.exists() else ".env not present (fine if the variables are set in the environment)")

    print("\nRequired environment variables (names and sources only, values are never printed):")
    for k, why in (("APOLLO_API_KEY", "Apollo"), ("BLISSGROWTH_N8N_API_KEY", "n8n API"),
                   ("BLISSGROWTH_N8N_INSTANCE_URL", "n8n URL"), ("HEYREACH_API_KEY", "HeyReach"),
                   ("MILLIONVERIFIER_API_KEY", "MillionVerifier, presence only, not tested because a test costs a credit")):
        if os.environ.get(k):
            src = ".env" if k in config._DOTENV_KEYS else "env"
            say(OK, "%s: OK (source: %s) (%s)" % (k, src, why))
        else:
            say(FAIL, "%s: MISSING (%s)" % (k, why))
    local_path = config.IDEA_LAUNCH_DIR / "config.local.json"
    if local_path.exists():
        try:
            json.loads(local_path.read_text(encoding="utf-8"))
        except ValueError:
            say(FAIL, "engine/config.local.json is not valid JSON")
    for k, why, level in (("IDEA_LAUNCH_BRIDGE_SECRET", "Sheets Bridge secret", FAIL),
                          ("IDEA_LAUNCH_PHONE_WEBHOOK_PATH", "phone receiver webhook path, needed for /iv-phones", WARN),
                          ("IDEA_LAUNCH_PHONE_DATA_TABLE_ID", "phone results data table id, in config.json by default", WARN),
                          ("IDEA_LAUNCH_PHONE_WORKFLOW_ID", "phone receiver workflow id, in config.json by default", WARN)):
        src = config.source_of(k)
        if src:
            say(OK, "%s: OK (source: %s) (%s)" % (k, src, why))
        else:
            say(level, "%s: MISSING (%s)" % (k, why))
    secret = config.get("sheets_bridge.secret", "")
    real = bool(secret) and not config.is_placeholder(secret)
    snd = config.get("launch.senders") or {}
    f = snd.get("founders") or {}
    say(OK if (f.get("jay") and f.get("meelan")) else WARN,
        "launch.senders founders set (source: %s)" % (config.source_of("IDEA_LAUNCH_SENDER_JAY") or "config") if (f.get("jay") and f.get("meelan"))
        else "launch.senders founders not set (needed for /iv-launch)")
    say(OK if snd.get("associate") else WARN,
        "launch.senders.associate set" if snd.get("associate") else "launch.senders.associate is null (InMail campaign creation is refused until set; IDEA_LAUNCH_SENDER_ASSOCIATE)")
    me = config.get("launch.mansi_email")
    say(OK if me else WARN, "launch.mansi_email set" if me else "launch.mansi_email is null (call sheet is skipped until set; IDEA_LAUNCH_MANSI_EMAIL)")
    print("")

    base = os.environ.get("BLISSGROWTH_N8N_INSTANCE_URL", "").rstrip("/")
    if base and real:
        try:
            url = base + "/" + config.get("sheet.bridge_path", "webhook/idea-launch-sheets")
            hdr = config.get("sheets_bridge.header", "X-Idea-Launch-Secret")
            st, _, _ = net.fetch("POST", url, {hdr: secret, "Content-Type": "application/json"},
                                 json.dumps({"action": "read"}).encode(), 30)
            if st == 403:
                say(FAIL, "n8n bridge reachable but refused the secret (403): wrong IDEA_LAUNCH_BRIDGE_SECRET")
            elif st == 404:
                say(FAIL, "n8n bridge webhook not found (404): workflow 'Idea Launch | Sheets Bridge' inactive or wrong URL")
            elif st < 500:
                say(OK, "n8n bridge reachable and the secret is accepted (HTTP %d)" % st)
            else:
                say(FAIL, "n8n bridge answered HTTP %d" % st)
        except Exception as e:
            say(FAIL, "n8n bridge not reachable (%s)" % type(e).__name__)
    else:
        say(WARN, "n8n bridge check skipped (needs BLISSGROWTH_N8N_INSTANCE_URL and IDEA_LAUNCH_BRIDGE_SECRET)")

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
        print("Fix the [FAIL] lines first. Set missing variables in the Claude web environment (or .env locally). Get secrets from Afroz securely (never Slack).")
    sys.exit(1 if results.count(FAIL) else 0)


if __name__ == "__main__":
    main()
