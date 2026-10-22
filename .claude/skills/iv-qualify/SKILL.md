---
name: iv-qualify
description: AI fit check for the companies of an idea launch. Tunes a judge prompt on a sample of 10 with the user (stop after 2 clean rounds), then scores every company with Sonnet subagents in batches of about 25 (qualified, confidence, one-line reason), checks each live website and flags dead or parked ones, uses the user's company signals (hard thresholds drop a company automatically, soft ones inform the judge), writes results back to the "2 Accounts" tab. Never deletes rows. Use for "/iv-qualify", "qualify the accounts", "score the companies".
---

# /iv-qualify: accounts -> tuned prompt -> qualified / confidence / reason

Script: `engine/bin/qualify_run.py <command> <run>` (repo root, `python3 -I`). Judgement is done by Claude subagents (there is no model API key in the project). Background and file layout: `docs/ENGINE.md`.

Rules: judge only on the evidence given. Keep low-confidence rows and flag them. Never delete or hide a row. Never auto-approve a tuning round.

## 1. Spec and prompt
Check `accounts` is done, or that the accounts pilot is drawn (while the accounts pilot gate is open, qualify works on the PILOT accounts only; the rest follow after the user approves the pilot, see `/iv-accounts`). If the brief has numeric signals, `/iv-signals` must have enriched these accounts first, or qualify refuses (it names the command). Start from `brief.json` -> `qualify` (ICP one-liner, qualifies, disqualifies, countries, leans). Confirm or improve it with the user, write it to the scratchpad as `spec.json`, then:
`qualify_run.py set-spec <run> --spec-file <spec.json>`
This builds `qualify/prompt.md` with the four mandatory blocks (size evidence, screening separation, sparse sites, identity language). Never hand-write a prompt without them. When `brief.json` has `signals`, `set-spec` adds them to the spec automatically and the prompt gets a "Company signals" section after the four blocks (hard rules are enforced by the system, soft rules and free-text signals are weighed, unknown is never a reason to reject). Show the prompt to the user.

### Signals in qualification
- Every batch item carries `signals`: the headcount values, each rule with the user's threshold, strength (hard or soft) and result (pass, fail, unknown, judge), and Apollo's technology list.
- HARD numeric rules are applied BEFORE the model, at `sample` and `batches`: a company that fails one gets flag `drop`, qualified false, reason `signal: engineers 2000 > max 200` (batch `auto-signal`), the row stays in the sheet, and it never goes to a subagent or into a tuning sample. Unknown data never drops. If the user later changes a threshold so a company no longer fails, `batches` releases it (error flag) and it is scored again. Ingest never overwrites a signal drop.
- SOFT and free-text rules are in the scorer's evidence and named in its reason when they decide.
- `qualify_run.py batches` prints `dropped_by_hard_signals`; mention the number and show two or three examples to the user.

## 2. Tuning loop (batches of 10, 2 clean rounds)
For round N = 1, 2, ...:
1. `qualify_run.py sample <run> --round N` (fetches the live sites, picks 10 not used before, writes `qualify/batches/sample-rN.json`).
2. Launch ONE Sonnet subagent (Agent tool, model "sonnet") with the scorer prompt below for that batch file.
3. `qualify_run.py sample-report <run> --round N`, show the table. Offer to show the evidence for any row (page_title, meta_description, homepage_text in the batch file).
4. Ask: "Which are wrong, or right for the wrong reason? Or approved?" Count corrections.
5. `qualify_run.py tune-log <run> --round N --corrections K`. It prints the clean streak. One correction resets it to 0.
6. If K > 0: change the spec (add qualifies or disqualifies, add `extra_rules` with the specific edge case, adjust leans), `set-spec`, show the full new prompt, go to round N+1 with a NEW sample. (A `set-spec` after `lock` unlocks the prompt, so tuning must pass again.)
7. Stop when the streak reaches 2 (config `qualify.clean_rounds_needed`), then `qualify_run.py lock <run>`. If the user wants to stop earlier or the loop will not converge after about 5 rounds (data too thin), `lock --force` only on the user's say-so. If it will not converge, suggest richer evidence.

## 3. Full scoring
1. `qualify_run.py batches <run>`: fetches every missing homepage (hard per-row deadline, resumable), resolves dead, parked and no-website companies without the model (flags `dead_site` or `parked_site`, qualified false, row kept), and writes `batch-NNNN.json` for the rest (25 rows each).
2. Launch Sonnet subagents with the scorer prompt: one subagent per 1 to 4 batch files, up to about 8 in parallel. Wait for all.
3. `qualify_run.py ingest <run>` (also done automatically at the start of `batches` and `retry`) validates strictly (qualified true/false, confidence 0 to 1, reason present, ids match). Invalid rows become `error`, missing rows stay pending.
4. `qualify_run.py status <run>`; if rows are pending or errored, ONE retry pass: `qualify_run.py retry <run>`, subagents again, `ingest`. A second pass needs `--force` and the user's say-so.
5. `qualify_run.py finalize <run>` (required: the stage is only done after it): writes `qualify/qualified.csv`, upserts qualified, confidence, flag, reason and website_status into the "2 Accounts" tab, logs to the Run Log, rewrites `summary.md`.
6. If this was the accounts PILOT, do not go on to scoring the rest: run `pilot_run.py accounts request-review <run>` and follow `/iv-accounts` Part 1 (the user reviews, Claude summarises, the user approves). The human review beats the AI: a rejected pilot account is flag `drop`, an approved one the AI dropped is put back to `keep` at finalize (reason says so).
7. Report counts by flag: keep (qualified, confidence >= 0.6), review (qualified, low confidence), drop (not qualified), dead_site, parked_site, error. Companies with keep or review form the pool for /iv-people (Phase 2). Give the sheet URL and the first line of `summary.md`.

## Scorer prompt (for each Sonnet subagent; fill in the batch file paths)
```
You are an ICP qualification scorer. Read the judge prompt file, then each batch file, and score every company in it.
Judge prompt file: <run>/qualify/prompt.md
Batch file(s): <run>/qualify/batches/batch-NNNN.json
Rules:
- Follow the judge prompt exactly, including its four mandatory blocks, its signals section (if present) and its output contract. Judge ONLY on the evidence in each row (name, domain, facts, page_title, meta_description, homepage_text, signals). Do not use outside knowledge about the company.
- Score every row in "rows". Use the row "id" as the id.
- For each batch file write ONE strict JSON array and nothing else (no fences, no commentary) to the path in that file's "result_file": [{"id","qualified":true|false,"confidence":0.0-1.0,"reason":"one sentence, max 200 chars"}]
- Use the Write tool. Modify no other file. No em dashes. Reply with one line: rows scored.
```

## Gotchas
- A site that answers 403 or 5xx is `blocked`, not dead: it is still scored from the Apollo facts, usually with low confidence.
- A JavaScript-only site with a real meta description is treated as live, not parked.
- If the prompt changes after scoring started, say so and offer to rescore (`batches --reissue` after clearing results is NOT automatic: ask first).
