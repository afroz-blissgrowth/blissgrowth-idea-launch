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
3. `cp engine/config.local.example.json engine/config.local.json`, then fill it in (bridge secret, phone webhook path, HeyReach sender ids, Mansi's email). Get the values from Afroz securely, never Slack.
4. `python3 -I engine/bin/doctor.py` and fix every `[FAIL]` line.
5. Open Claude Code in this folder and type `/iv-run`.

## Daily usage
- `/iv-run <idea>` starts or resumes a run. It stops only where you must decide: the brief, the account pilot (10 to 20 accounts), tuning samples, the people pilot, copy approval, the idea page text and the launch approval.
- Run one stage on its own with its command (`/iv-brief`, `/iv-accounts`, ...). Order and details: `.claude/skills/README.md` and `docs/ENGINE.md`.
- Run data lands in `runs/<date>-<idea>/` (gitignored). Check progress with `python3 -I engine/bin/run_all.py status <idea>`.

## How to improve it
- Change behaviour in files, not code: prompts and rules in `.claude/skills/iv-*/SKILL.md`, defaults and thresholds in `engine/config.json`, approved copy in `engine/copy-library/`.
- Run the tests before every commit: `python3 -I engine/tests/run_tests.py` (260 tests, offline, no credits).
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
- `engine/config.local.json`: Sheets Bridge secret, phone webhook path, data table id and workflow id, HeyReach sender account ids (Jay, Meelan, associate), Mansi's Google email
- Access to the Blissgrowth n8n, HeyReach workspace and the shared Drive
