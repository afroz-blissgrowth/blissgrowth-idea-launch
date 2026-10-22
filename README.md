# Blissgrowth Idea Launch

Turns an idea memo into a verified, tiered, ready-to-launch campaign list, as Claude Code commands. One Google Sheet and one run folder per idea. It ends with DRAFT campaigns in HeyReach and a call sheet; nothing is sent live.

## Prerequisites
- Claude Code
- Python 3.9 or newer (standard library only, nothing to pip install)
- The Notion and Google Drive connectors enabled in Claude (memo ingestion, the reply-agent idea page)
- Access to the Blissgrowth n8n workflows (the Sheets Bridge, the LinkedIn activity checker, the phone receiver)
- Secrets from Afroz (see the end of this file)

## Setup
1. Clone this repo and open a terminal in it.
2. `cp .env.example .env`, then fill in every key (Apollo, n8n API key and URL, HeyReach, MillionVerifier).
3. `cp engine/config.local.example.json engine/config.local.json`, then fill it in (bridge secret, phone webhook path). Sender ids and Mansi's email live in the committed `engine/config.json`. Get the values from Afroz securely, never Slack. (On Claude web use environment variables instead, see "Claude web".)
4. `python3 -I engine/bin/doctor.py` and fix every `[FAIL]` line.
5. Open Claude Code in this folder and type `/iv-run`.

## Claude web
The repo runs in Claude Code on the web (cloud session with this GitHub repo connected). There are no local files beyond the repo: every secret comes ONLY from environment variables set in the Claude web environment. Never write them to files in the repo. Environment variables beat `<repo>/.env` and `engine/config.local.json`, which still work for local use.

Environment variables to set:

| Variable | Required | What it is |
|---|---|---|
| `APOLLO_API_KEY` | required | Apollo API key (accounts, people, enrichment, phones) |
| `BLISSGROWTH_N8N_API_KEY` | required | Blissgrowth n8n API key (activity checker, phone data table) |
| `BLISSGROWTH_N8N_INSTANCE_URL` | required | n8n base URL, no trailing slash |
| `HEYREACH_API_KEY` | required | HeyReach key for the Blissgrowth workspace (draft campaigns) |
| `MILLIONVERIFIER_API_KEY` | required | MillionVerifier key (without it emails stay unverified) |
| `IDEA_LAUNCH_BRIDGE_SECRET` | required | Sheets Bridge secret (every Google Sheet read and write) |
| `IDEA_LAUNCH_PHONE_WEBHOOK_PATH` | required for /iv-phones | Phone receiver webhook path (acts as a secret) |
| `IDEA_LAUNCH_PHONE_DATA_TABLE_ID` | optional | Overrides `phones.data_table_id` in `engine/config.json` |
| `IDEA_LAUNCH_PHONE_WORKFLOW_ID` | optional | Overrides `phones.workflow_id` in `engine/config.json` |
| `IDEA_LAUNCH_SENDER_JAY`, `IDEA_LAUNCH_SENDER_MEELAN` | optional | Override the HeyReach account ids in `launch.senders` |
| `IDEA_LAUNCH_SENDER_ASSOCIATE` | optional now, needed for InMail | HeyReach account id of the associate. While `launch.senders.associate` is null, InMail campaign creation is refused |
| `IDEA_LAUNCH_MANSI_EMAIL` | optional now, needed for the call sheet | Mansi's Google email. While `launch.mansi_email` is null, the call sheet is skipped and /iv-launch asks |
| `IDEA_LAUNCH_BRIDGE_HEADER` | optional | Bridge header name (default `X-Idea-Launch-Secret`) |
| `APIFY_TOKEN` | optional | Only to rebuild the activity checker workflow |

Network allowlist (the session must be able to reach these):
- `api.apollo.io`
- `api.heyreach.io`
- the host of `BLISSGROWTH_N8N_INSTANCE_URL` (n8n API, Sheets Bridge, activity checker, phone receiver)
- `api.millionverifier.com`
- Company websites: `/iv-qualify` fetches each account's own website, so it needs general web access (a closed allowlist cannot cover them). Google Sheets and LinkedIn are reached only through n8n, never directly. `api.apify.com` only if you set `APIFY_TOKEN`.

Connectors: the Notion and Google Drive connectors must be enabled for the session (memo ingestion, the reply-agent idea page, sharing sheets).

Check the setup with `python3 -I engine/bin/doctor.py`: it lists every required variable as OK or MISSING and its source (env, .env or config.local.json), never the value.

## Daily usage
- `/iv-run <idea>` starts or resumes a run. It stops only where you must decide: the brief, the account pilot (10 to 20 accounts), tuning samples, the people pilot, copy approval, the idea page text and the launch approval.
- Run one stage on its own with its command (`/iv-brief`, `/iv-accounts`, ...). Order and details: `.claude/skills/README.md` and `docs/ENGINE.md`.
- Run data lands in `runs/<date>-<idea>/` (gitignored). Check progress with `python3 -I engine/bin/run_all.py status <idea>`.

## How to improve it
- Change behaviour in files, not code: prompts and rules in `.claude/skills/iv-*/SKILL.md`, defaults and thresholds in `engine/config.json`, approved copy in `engine/copy-library/`.
- Run the tests before every commit: `python3 -I engine/tests/run_tests.py` (265 tests, offline, no credits).
- Commit and push on a branch, and open a pull request. Never commit `.env`, `engine/config.local.json` or `runs/`.
- Rules for writing: no em dashes, spell "Blissgrowth".

## Costs
- Apollo: account search 1 credit per page of 100, company signals 1 credit per matched company, enrichment (bulk match) credits per person, phones 8 credits per mobile. Apollo calls are logged per run in `apollo-usage.jsonl`. There are no credit caps, so watch your balance.
- MillionVerifier: one credit per email verified.
- LinkedIn activity check: Apify usage on the n8n workflow, logged in dollars.
- HeyReach, n8n, Google Sheets: no per-run cost beyond the subscriptions.
- Every stage prints an estimate before it spends.

## What you must get from Afroz (securely, never Slack)
- The values for `.env` (Apollo, n8n API key and URL, HeyReach, MillionVerifier keys)
- `engine/config.local.json` (or the matching environment variables): Sheets Bridge secret and phone webhook path
- The associate's HeyReach account id and Mansi's Google email (to put in `engine/config.json`, both are null until provided)
- Access to the Blissgrowth n8n, HeyReach workspace and the shared Drive
