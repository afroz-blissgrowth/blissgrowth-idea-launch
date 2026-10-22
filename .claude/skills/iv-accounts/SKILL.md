---
name: iv-accounts
description: Pull the companies for an idea launch from Apollo using the agreed brief.json, PILOT FIRST. Pulls a pilot of 10 to 20 accounts (default 15), enriches company signals, hands over to /iv-qualify, then STOPS for the user's hand review in the sheet or chat; only after the user's explicit approval does the full pull run (dry-run estimate, pagination, sharding past 50,000, retries, dedupe, "2 Accounts" tab). Approved pilot accounts become seeds. Use for "/iv-accounts", "pull the accounts", "run the Apollo company search", "pilot the accounts".
---

# /iv-accounts: brief.json -> PILOT (reviewed by hand) -> full Apollo company search -> "2 Accounts"

Scripts (run from the repo root with `python3 -I`): `engine/bin/accounts_pull.py`, `pilot_run.py`, `signals_run.py`. `<run>` is the idea slug, the folder name under `runs/`, or a path. List runs: `python3 -I engine/bin/run_status.py --list`.

Why a pilot: the real pain is a wrong ICP. "The first 10, 20 subset needs to be reviewed properly" (call, 2026-10-21). The full pull is REFUSED by `accounts_pull.py` until the pilot is approved (or the user skips the gate, a recorded decision).

## Part 1: the pilot
1. Find the run and read the first line of its `summary.md`. If the brief stage is not done, go back to /iv-brief.
2. Optional dry run (about 1 credit per count call): `accounts_pull.py <run> --dry-run`. Show matches, pages, credits and the volume-math line, and interpret it with the user (too many: tighten the brief; too few: widen; a set marked "truncated" hit the 50,000 cap).
3. Pull the pilot: `pilot_run.py accounts start <run> [--size 15]` (10 to 20; the brief's `pilot.accounts_size` or config `pilot.accounts_size`). It is a small limit pull spread over the filter sets (a few Apollo credits), writes `pilot/accounts.json`, marks the rows `pilot = yes` in "2 Accounts". Never re-drawn. (`--from-existing` draws the pilot from accounts already pulled, with no Apollo call: for tests and old runs.)
4. Signals (if the brief has numeric signals): `signals_run.py plan <run> --scope pilot`, tell the user the credits (1 per matched company, up to the pilot size), then `signals_run.py run <run> --scope pilot`. See `/iv-signals`.
5. Qualify the pilot with `/iv-qualify` (until the pilot is reviewed, qualify works on the pilot accounts only). Hard signals drop automatically, soft ones inform the AI judge.
6. Ask for the review: `pilot_run.py accounts request-review <run>` (finalizes qualify, pushes the pilot, signal and review columns to the sheet). Tell the user: "Open the sheet, tab 2 Accounts, filter pilot = yes. Mark pilot_review approve or reject for each of the N rows, add a pilot_note if you like. Or just tell me here." STOP and wait. Show for each row: name, domain, AI flag and reason, headcounts, signal results.
7. Marks: from the sheet `pilot_run.py accounts pull-review <run>`; from chat `pilot_run.py accounts record <run> --match "<company>" --review approve|reject --note "..."`. A blank sheet cell never erases a chat mark. `pilot_run.py accounts list <run>` shows the rows and marks. Every row needs a decision.
8. Summarise the patterns: `pilot_run.py accounts summary <run>` (AI versus human: AI too loose or too strict, signal ranges of approved versus rejected, the rejection notes). Read it, explain it in plain words, and PROPOSE adjustments: a changed signal threshold or a new signal (/iv-brief), a new disqualify or extra rule in the qualify spec (/iv-qualify `set-spec`), a keyword or band change (`--accept-brief-change`). Make a change only when the user agrees; if one is made, re-check the pilot rows against it.
9. Approval: only when the user says go (the explicit words, not silence): `pilot_run.py accounts approve <run> --note "<what the user said>"`. It refuses while any row is unmarked. It re-runs qualify finalize (a human reject becomes flag drop, a human approve puts an AI drop back to keep; rows are never deleted), writes `pilot/seeds.csv` and sets `is_seed = yes` on the approved pilot accounts (seeds for future lookalike expansion), and records the approval, tied to a hash of the marks (changing a mark afterwards re-opens the gate).
   `--simulated` labels marks and approvals nobody gave (tests, TEST runs only). A simulated approval never counts for a real run.
   Skipping the pilot is the user's call only: `pilot_run.py accounts skip <run> --note "why"`.

## Part 2: the full pull (after the approval)
10. `accounts_pull.py <run>` (add `--accept-brief-change` only if the brief's Apollo filters changed after a pull). Long runs (hundreds of pages): `run_in_background`. It resumes from `accounts.ledger.json`; re-run the same command. The pilot accounts are kept (dedupe by org id), their qualify results are reused.
11. Then `/iv-signals` for the rest (the companies already enriched are not paid for again), `/iv-qualify` for the rest, with the prompt locked on the pilot.
12. Report: accounts pulled, duplicates merged, excluded, credits used (also in `apollo-usage.jsonl` and `summary.md`), the sheet URL. Next: `/iv-qualify <run>`.

## Facts worth knowing
- Apollo's organization search returns companies in two arrays (`organizations` and CRM `accounts`); the client reads both.
- Records carry no industry, headcount or description. Headcounts come from `/iv-signals`, fit is judged later from the live website.
- Rate limit on this key: 200 per minute, 6,000 per hour, 50,000 per day; the client reads the headers and waits on 429.
- Every company is kept. Excluded domains from the brief go to `accounts.excluded.csv`, not away.
- A limit run (`--limit 25`) is a test pull: partial, never READY, and it does NOT replace the pilot gate.
- No em dashes in anything written.
