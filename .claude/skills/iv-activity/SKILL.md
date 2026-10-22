---
name: iv-activity
description: LinkedIn activity check for the enriched people of an idea launch through the existing n8n "LinkedIn Activity Checker" (activated only for the run, deactivated afterwards, results cached by profile URL in the run folder). Inactive profiles get email only, people without a valid email get LinkedIn only, and people the checker shows as not in a current job are excluded. Use for "/iv-activity", "check LinkedIn activity", "activity filter".
---

# /iv-activity: LinkedIn URLs -> Active / Inactive -> channel rules

Script: `engine/bin/activity_run.py <run|deactivate|skip|status> <run>` (repo root, `python3 -I`). Contract and design: `engine/lib/activity.py` and the README section "LinkedIn activity contract".

## What happens
Input: LinkedIn profile URLs of the selected, enriched people. The script upserts them into two new tabs of the checker's spreadsheet (`il <run name>` and `il <run name> runs`), activates the workflow "LinkedIn Activity Checker" (id `NrweLKOV7gMu54bD`, normally INACTIVE), starts a run through its webhook, polls until `run_end`, reads the tab, caches every FINAL answer in `activity/cache.jsonl` keyed by the profile URL, and deactivates the workflow again (also after errors). Output per person: `activity_status` Active, Inactive, Shell or blank (unknown), mapped to `linkedin_active` yes, no, unknown. Apify costs a few cents for a small run (the run's usd is in the run log).

## Steps
1. Make sure the contract patch is live once: `python3 -I engine/workflows/patch_activity_checker.py --check` (it says `contract_patched=True`; if not, run it without `--check`; it backs the workflow up first and only adds three optional webhook fields).
2. Tell the user how many profiles will be checked (`people.csv`, selected people with a URL, minus cached) and that the checker will be switched on for the run only.
3. `activity_run.py run <run>` (use `run_in_background` for more than a few dozen profiles; it takes minutes). Timeout (config `activity.timeout_min`): the checker may still be running, it stays on; collect later with `activity_run.py run <run> --resume`, which also switches it off.
4. Safety: `activity_run.py deactivate <run>` makes sure it is inactive.
5. Report counts: Active, Inactive, Shell, unknown, pending (blank answers are retried by the checker up to 3 attempts, re-run the command to retry), and that the workflow is inactive again. Next: `/iv-phones <run>` then `/iv-ready <run>`.

## Employment exclusions from the checker output
The checker's columns `headline`, `current_title`, `current_company`, `jobs_count`, `current_jobs_count` and `latest_job_start` are cached with the activity answer. After the run, `people.csv` is rebuilt: keywords on the headline and titles (garden leave, retired, career break, open to work, between roles, "seeking new ...", "looking for my next role", "former ..." and "ex-..." at the start of a title only, never the headline; config `exclusions.groups`) and `current_jobs_count` 0 with `jobs_count` above 0 set `exclusion_reason`, the channel becomes none, the row stays. Active on LinkedIn does not override it. People already excluded by Apollo employment data (or rejected in the pilot) are not sent to the checker, which saves Apify cost. For a run checked before these columns were cached: `activity_run.py backfill <run>` copies them from the checker tab (free, no Apify, no credits). Report the exclusion counts from `summary.md`.

## Rules
- Inactive and Shell: email channel only. No valid email: LinkedIn only. Unknown or unchecked counts as not active (config `activity.unknown_policy` can change that).
- Skip only on the user's say-so: `activity_run.py skip <run> --note "why"` (LinkedIn then needs only a profile URL).
- Never edit or rename the checker workflow by hand. Previous campaigns used tab pairs in the same spreadsheet; this uses the same pattern.
- No em dashes in anything written.
