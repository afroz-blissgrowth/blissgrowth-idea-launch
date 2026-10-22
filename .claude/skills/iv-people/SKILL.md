---
name: iv-people
description: Find the buyers at the qualified companies of an idea launch. Apollo people search, one company per call, T1 and T2 titles from the brief together, per-company ledger so it resumes, 0 credits. Companies with nobody found go to the "3 Accounts: No People" tab with a reason, everyone else to "4 People". Use for "/iv-people", "find the people", "search contacts for the qualified accounts".
---

# /iv-people: qualified accounts -> Apollo people search -> "4 People" + "3 Accounts: No People"

Script: `engine/bin/people_search.py <run>` (repo root, `python3 -I`). `<run>` is the idea slug, the folder name under `runs/`, or a path. Full docs: `docs/ENGINE.md`.

## Before you start
Read the first line of `summary.md`. The `qualify` stage must be finalized (`qualify/qualified.csv` exists). The pool is every company flagged `keep` or `review`. Titles come from `brief.json` (`people.T1`, `people.T2`), agreed with the user in /iv-brief. Never change titles here on your own: if the user wants other titles, edit the brief with /iv-brief, then re-run with `--accept-query-change` (the old search is archived, nothing is deleted).

## Steps
1. Estimate (sends nothing): `python3 -I engine/bin/people_search.py <run> --dry-run`. It shows companies to search, the query (all T1 and T2 titles in one call, union of the seniorities), calls (one per company) and time. Cost is 0 credits. Limit: 200 requests per minute and 6,000 per hour on this Apollo key, shared with everything else. Roughly 3,000 to 4,000 companies take an hour or more.
2. Small first run on a real run folder (optional): `... <run> --limit-orgs 20`, look at `people.csv`, then run the rest.
3. Full search: `... <run>`. For hundreds of companies start it with `run_in_background`. It writes a per-company ledger (`people/search.ledger.jsonl`); if it stops (error, hourly budget nearly used) re-run the same command and it continues. Errors are retried on the next run and show in the No People tab as `search_error`.
4. It then rebuilds `people.csv` and updates the sheet: "4 People" (one row per Apollo person, `cap_status` candidate) and "3 Accounts: No People" (company, reason). Report: companies searched, with people, without, people found, truncated companies (more than 3 pages of results), and the first line of `summary.md`. Next: `/iv-tier <run>`.

## What to know
- Apollo search returns an obfuscated last name, no LinkedIn URL and no email. Those come from `/iv-enrich-verify` (credits), only for the capped people.
- Caps (T1 5, T2 3 by default; `brief.people.caps` overrides `config.json` people_caps) are applied AFTER tiering. Before tiering, only the best `people.tier_pool_per_company` (10) people per company by title priority go to Claude. Title priority = position in the brief's title lists (all T1 titles first, earlier is better). If the user skips tiering, the top T1 cap + T2 cap people by title priority are selected and get the T2 channels.
- `title_hint` (T1/T2/blank) only says which brief title list matched. It is a hint for the tiering prompt, not a tier. Words like "Owner" also match "Product Owner": Claude fixes that in /iv-tier.
- Rows are never deleted. `over_cap` and `not_tiered` rows stay in the sheet.
- Companies the user rejected in the accounts pilot are flag `drop` and are not searched. After `/iv-tier` the people pilot gate follows (10 to 20 people reviewed by hand) before any enrichment credit.
- No em dashes in anything written.
