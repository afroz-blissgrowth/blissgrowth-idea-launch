---
name: iv-run
description: Run a whole idea launch end to end (brief, account pilot, accounts, signals, qualify, people, tier, people pilot, enrich and verify, activity, phones, ready tabs, copy, idea page, launch), resumable, stopping only where the user must decide (brief, the two hand-review pilot gates, tuning reviews, copy approval, launch approval). Shows cost estimates, never blocks on credits. Use for "/iv-run <idea>", "run the whole idea launch", "where is this launch up to", "continue the launch".
---

# /iv-run <idea>: one command for the whole pipeline

Script: `engine/bin/run_all.py {status|next|go} <run>` (repo root, `python3 -I`). Logic: `lib/orchestrate.py`, stage registry `lib/stages.py`. `<run>` is the folder name, the slug, or omit to pick from `run_status.py --list`.

## Loop
1. `run_all.py status <run>`: the projected pipeline (done, AUTO = a script runs it, STOP = needs the user or Claude with the user), cost estimates, and `summary.md` line 1. Show it briefly.
2. `run_all.py go <run>` is a DRY RUN by default. When the user says go: `run_all.py go <run> --execute`. It runs the auto stages in order (account pilot pull and its signals, then after approval the full accounts pull and signals, people search, people pilot draw, enrich and verify, activity, phones, ready tabs; long ones take a while, use `run_in_background`) and stops with exit code 10 at the first stage that needs a person, printing which one. Exit code 1 means a script failed or nothing changed: read the message.
3. At a stop, follow that stage's skill with the user, then run step 2 again, it resumes at the next stage:
   - `brief`: `/iv-brief` (the user decides ICP, titles, countries, tiers; Claude never decides alone)
   - `pilot_accounts` (user stop 1): the driver pulls the pilot (10 to 20 accounts, default 15) and enriches their signals, then stops for `/iv-qualify` on the pilot, then for the user's HAND REVIEW. Follow `/iv-accounts` Part 1: the user marks every pilot account approve or reject (sheet columns pilot_review, pilot_note, or chat), Claude summarises the patterns from the rejections and proposes brief, signal or prompt changes, and ONLY on the user's explicit approval (`pilot_run.py accounts approve`) does the full pull run. The driver never pulls in full before that.
   - `qualify`: `/iv-qualify` (tuning review on samples of 10, 2 clean rounds)
   - `tier`: `/iv-tier` (same)
   - `pilot_people` (user stop 2): after tiering the driver draws a pilot of 10 to 20 people and stops BEFORE enrichment credits. Follow `/iv-tier` section 4: the user marks each person approve or reject, Claude summarises, the user approves (`pilot_run.py people approve`). Rejected pilot people are never enriched.
   - `copy`: `/iv-copy` (draft, user review, explicit approval)
   - `idea_page`: `/iv-idea-page` (user confirms the text, Notion MCP creates it)
   - `launch`: `/iv-launch` (user approves the plan, DRAFT campaigns only, call sheet for Mansi)
4. Done when `summary.md` line 1 says READY (everything before launch) and the launch stage is done.

## Rules
- Two gates are hard stops by design: the accounts pilot and the people pilot. Only the user can skip one (`pilot_run.py <gate> skip --note`), Claude never does. A SIMULATED review or approval (`--simulated`, TEST runs only) never completes a gate on a real run. Runs whose accounts or enrichment predate the gates are treated as already past them.
- Employment exclusions (garden leave, retired, career break, Open to Work, ended roles) are applied automatically after enrichment and activity; the counts are in `summary.md` and the Run Log.
- Cost is shown (estimate per stage), logged, and never a gate or a limit (Decisions). Do not stop to ask about credits. Do not change phone or enrich credit behaviour: `phones.phones_in_enrich` is false and NOT implemented, it waits for Afroz's decision on REVIEW-PHASE2 issue A.
- The driver never starts a HeyReach campaign and never launches without the user's approval of the plan. A TEST run is never READY and never launches.
- Resumable from files: stage status comes from output files, so a crashed or stopped run continues where it was. Do not re-run a finished stage by hand unless asked.
- Before the first full run on a new machine: `MILLIONVERIFIER_API_KEY` in `.env` (REVIEW-PHASE2 issue B), HeyReach sender account ids and Mansi's email in `config.local.json`.
