---
name: iv-tier
description: Tier the people of an idea launch as T1 or T2 (or X for not a buyer) with Claude Sonnet subagents using the brief's tier rules, tune the prompt on a sample of 10 with the user until 2 clean rounds, tier everyone in batches with strict ingest, then enforce the per-company caps (T1 5, T2 3 by default), then STOP for a hand-reviewed pilot of 10 to 20 people before any enrichment credit is spent. Use for "/iv-tier", "tier the people", "T1 T2 tiering".
---

# /iv-tier: people -> tier + reason -> caps

Script: `engine/bin/tier_run.py <command> <run>` (repo root, `python3 -I`). Judgement is done by Claude subagents (no model API key in the project). Same pattern as /iv-qualify. Docs: `docs/ENGINE.md`.

Rules: tier rules are the user's (agreed in /iv-brief, stored in `brief.json` `tier_rules`). Never invent or loosen them alone. Judge only on the evidence given (title, company, country, title hint, company fit). Never auto-approve a tuning round. Never delete a row.

## 1. Spec and prompt
`tier_run.py show-spec <run>` prints a starting spec from `brief.tier_rules` (T1 text, T2 text, X text, extra rules). Show it to the user, improve it with them, write it to the scratchpad as `spec.json`, then `tier_run.py set-spec <run> --spec-file <spec.json>`. Show the prompt (`tier/prompt.md`). Three mandatory blocks are enforced (evidence only, lean T2 over X, company context).

## 2. Tuning loop (samples of 10, 2 clean rounds, with the user)
For round N = 1, 2, ...:
1. `tier_run.py sample <run> --round N` (10 people over different companies, never reused).
2. ONE Sonnet subagent (Agent tool, model "sonnet") with the scorer prompt below for that sample file.
3. `tier_run.py sample-report <run> --round N` and show the table.
4. Ask the user: "Which tiers are wrong, or right for the wrong reason? Or approved?" Count corrections K.
5. `tier_run.py tune-log <run> --round N --corrections K`. One correction resets the streak.
6. If K > 0: change the spec (an extra rule for the specific edge case), `set-spec`, show the new prompt, next round with a NEW sample. A `set-spec` after `lock` unlocks the prompt.
7. At 2 clean rounds in a row: `tier_run.py lock <run>`. `--force` only on the user's say-so. For TESTS where no user reviews, label the rounds `--simulated` on `tune-log` and `lock`; the label is kept in `tier/tuning.json` and `status`.

## 3. Tier everyone
1. `tier_run.py batches <run>` (needs a locked prompt): batches of 30 people, grouped by company.
2. Subagents with the scorer prompt, one per 1 to 3 batch files, parallel. Wait for all.
3. `tier_run.py ingest <run>` (strict: tier T1, T2 or X, a reason, ids must match; bad rows are not recorded and are re-batched). `status` shows counts. One retry pass: `tier_run.py retry <run>`, subagents, `ingest`.
4. `tier_run.py finalize <run>`: enforces the caps, rebuilds `people.csv`, updates "4 People", Run Log, `summary.md`. Report: counts by tier, `selected` per tier, `over_cap`, `not_tiered` (X), and which companies hit a cap.

## 4. People pilot gate (before enrichment credits)
Enrichment (`/iv-enrich-verify`) is REFUSED until this gate is approved or skipped by the user. After `finalize`:
1. `pilot_run.py people start <run> [--size 15]` (10 to 20, default 15; no credits): draws people spread over different companies, keeping the T1/T2 mix. Then `pilot_run.py people request-review <run>` pushes `pilot`, `pilot_review`, `pilot_note` to "4 People" (filter pilot = yes).
2. Show the user the pilot (`pilot_run.py people list <run>`: company, title, tier; the tier reason is in the sheet). Ask them to mark each person approve or reject (and a note) in the sheet or in chat. Marks: `pilot_run.py people pull-review <run>` or `pilot_run.py people record <run> --match "<company>" --review reject --note "..."`. A blank sheet cell never erases a chat mark.
3. `pilot_run.py people summary <run>`: counts by tier, the rejected people with their tier reasons. Explain the patterns and PROPOSE changes (a tier rule, an extra rule in the tier spec, titles in the brief). Change nothing without the user's yes; if the tier prompt changes, re-tier and redraw is NOT allowed (the pilot is never re-drawn), so review the new tiers of the pilot people again.
4. Only on the user's explicit go: `pilot_run.py people approve <run> --note "<what the user said>"` (refuses while anyone is unmarked). People the user rejected get exclusion `pilot_rejected` and are never enriched (no credits); everyone else proceeds. Skip: `pilot_run.py people skip <run> --note "why"`, the user's decision only. `--simulated` is for TEST runs only and never counts for a real run.

Skip tiering only on the user's say-so: `tier_run.py skip <run> --note "why"`, then `finalize`. Then the top (T1 cap + T2 cap) people by title priority are selected and get the T2 channels (no calls).

## Cap rules (decision)
Caps come from `brief.people.caps` (overrides `config.json` people_caps). They are applied AFTER tiering; inside a tier the best title priority stays (position in the brief's title lists). Extra people become `over_cap`, X people `not_tiered`; both stay in the sheet.

## Scorer prompt (for each Sonnet subagent)
```
You are a tiering scorer. Read the judge prompt file, then the batch file, and tier every person in it.
Judge prompt file: <run>/tier/prompt.md
Batch file: <run>/tier/batches/batch-NNNN.json   (or sample-rN.json)
Rules:
- Follow the judge prompt exactly, including its mandatory blocks and output contract. Judge ONLY on the evidence in each row. Do not use outside knowledge.
- Score every row in "rows". Use the row "id" as the id.
- Write ONE strict JSON array and nothing else (no fences, no commentary) to the path in the batch file's "result_file": [{"id","tier":"T1"|"T2"|"X","reason":"one sentence, max 200 chars"}]
- Use the Write tool. Modify no other file. Never use em dashes. Reply with one line: rows scored.
```
