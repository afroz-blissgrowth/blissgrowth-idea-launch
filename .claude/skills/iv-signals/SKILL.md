---
name: iv-signals
description: Enrich the accounts of an idea launch with company signals from Apollo organization enrichment (employees and department headcounts such as engineering, operations, sales), by domain, once per company, credits logged, written to "2 Accounts". Run on the pilot accounts first, then the rest. Use for "/iv-signals", "enrich the accounts with headcounts", "get engineering headcount".
---

# /iv-signals: accounts -> Apollo headcounts -> signal columns

Script: `engine/bin/signals_run.py <plan|run|table|sync|status> <run> [--scope pilot] [--limit N]` (repo root, `python3 -I`). Logic: `engine/lib/signals.py`. The signals themselves (which ones matter, thresholds, hard or soft) are the user's, agreed in `/iv-brief` and stored in `brief.json` `signals`. Claude never adds or changes a threshold alone.

## What it does
Apollo `POST organizations/bulk_enrich` (10 domains per call, `domains[]`), 1 credit per matched company, 0 when not found. The answer gives `estimated_num_employees` and `departmental_head_count` (engineering, operations, sales, information_technology, finance, marketing, human_resources, legal ... as Apollo lists them) and Apollo's technology list. Each domain is enriched ONCE: run cache `signals/enrich.jsonl` plus a shared cross-run cache (`runs/_cache/signals-cache.jsonl`, 90 days), so another run or a re-run never pays twice. Real credits come from `credits_consumed` and are logged in `apollo-usage.jsonl` and the Run Log. The columns employees, engineering, operations, sales, information_technology, finance, marketing, human_resources, signals_status (enriched, not_found, no_domain, pending, error) and signals_at go to "2 Accounts" through the bridge (`add_columns`, then `upsert` by org_id); departments a signal uses beyond those get a `dept_<key>` column.

## Steps
1. If the brief has no numeric signals the script says so and does nothing (a text signal needs no Apollo data). Otherwise:
2. `signals_run.py plan <run> [--scope pilot]`: companies to enrich, credits (maximum), how many are answered from the cache. Tell the user the number (no credit gate, but say it).
3. PILOT FIRST: `signals_run.py run <run> --scope pilot`. Then the rest after the accounts pilot is approved: `signals_run.py run <run>`. `--limit N` caps the spend for a trial. While the accounts pilot is open, `plan` and `run` without `--scope` also stay on the pilot accounts (the script says so), so nothing outside the pilot is paid for before the review.
4. `signals_run.py table <run> [--scope pilot]` shows per company the headcounts and the result of each rule (pass, fail, unknown, judge). Show it to the user, it is the evidence for the pilot review.
5. What the data does in `/iv-qualify`: a failing HARD rule drops the company (flag drop, reason "signal: engineers 2000 > max 200", the row stays), SOFT rules and free-text signals go to the AI judge with the values, unknown data never drops. Qualify refuses to run while numeric-signal data is missing.
6. Errors are retried on the next run; a fatal Apollo error (401, 402, 403, 422) stops cleanly. Re-running is always safe.

## Rules
- Headcounts are Apollo estimates, not truth. Apollo lists departments it found people in, so a missing department with others present counts as 0 (config `signals.missing_department_is_zero`); an empty breakdown is unknown, not 0.
- A company Apollo cannot match is `not_found`: unknown signals, kept, never dropped.
- No em dashes in anything written.
