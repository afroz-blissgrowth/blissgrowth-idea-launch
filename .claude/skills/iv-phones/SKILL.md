---
name: iv-phones
description: Phone numbers for the T1 people of an idea launch through Apollo's asynchronous phone reveal. Apollo posts the numbers to a small n8n receiver workflow that stores them in the data table "IL Phone Results"; a poller in the script collects them by person id. T1 only, 8 credits per mobile found. Use for "/iv-phones", "get phone numbers", "call list phones".
---

# /iv-phones: T1 people -> Apollo phone reveal -> webhook -> phone

Script: `engine/bin/phones_run.py <request|collect|skip|status> <run>` (repo root, `python3 -I`). Design: `engine/lib/phones.py`.

## One-time setup
`python3 -I engine/workflows/deploy_phone_webhook.py` creates (or updates) the n8n workflow "Idea Launch | Apollo Phone Webhook" and the data table "IL Phone Results", activates the workflow and saves the secret webhook path in `config.local.json`. The receiver stays active permanently (tiny, idle, only stores). Apollo cannot send headers, so the path itself is the secret.

## Steps
1. Only T1 people that are selected and enriched are eligible (T2 never). Dry run: `phones_run.py request <run> --dry-run` (people and the maximum credits at 8 per mobile). Tell the user.
2. `phones_run.py request <run> [--limit N]`: `people/bulk_match` with `reveal_phone_number=true` and the receiver's `webhook_url`, 10 per call. Apollo answers at once with a request id; the numbers arrive later. The script then polls the data table every 20 seconds (config `phones.timeout_min`, 15 minutes). People for whom Apollo's search said "no direct phone" are not requested (saves credits) and are marked `not_available`.
3. If time runs out: `phones_run.py collect <run>` later. People are never requested twice; `--rerequest-stale` only after checking with Apollo.
4. Report: requested, received, none, still waiting, credits (also in the run log). Next: `/iv-ready <run>`.
- Prospeo and Amplemarket fallbacks are hooks only (`lib/waterfall.py`). Do not call them. T1 people without a phone are listed in `enrich/waterfall-needed.csv` as `phone_missing`.
- Skip only on the user's say-so: `phones_run.py skip <run> --note "why"`.
- No em dashes in anything written.
