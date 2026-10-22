---
name: iv-enrich-verify
description: Enrich the capped people of an idea launch with Apollo bulk_match (full name, LinkedIn URL, email; credits), verify the emails with MillionVerifier (only ok passes, catch-all marked), flag missing or invalid emails for a later waterfall, and grade the list with the 8-check list quality report. Use for "/iv-enrich-verify", "enrich and verify the emails", "verify the list", "list quality".
---

# /iv-enrich-verify: capped people -> name, LinkedIn, email -> MillionVerifier -> quality grade

Script: `engine/bin/enrich_verify.py <enrich|verify|quality|all> <run>` (repo root, `python3 -I`). Docs: `docs/ENGINE.md`.

## Steps
0. Gate: enrichment is blocked until the people pilot is approved (or skipped by the user, or the run predates the gate). If `enrich_verify.py enrich` says "blocked by the people pilot gate", go to `/iv-tier` section 4. A dry run is always allowed.
1. Dry run (sends nothing): `enrich_verify.py enrich <run> --dry-run`. Shows how many people (only `cap_status` selected, tiered T1 or T2, within caps) and the expected maximum credits. Tell the user the number; there is no credit gate (usage is only logged) but say it. People rejected in the pilot review are never enriched (no credit). Apollo charges roughly 1 credit per enriched person, also when no email comes back (measured on the test run: 15 people, 15 credits, 9 emails).
2. `enrich_verify.py enrich <run> [--limit N]`: `people/bulk_match`, 10 per call. Real credits come from Apollo's `credits_consumed` and are logged in `apollo-usage.jsonl`. People already matched are never sent again. T1 people are enriched first.
3. Verify: first a canary `enrich_verify.py verify <run> --canary 20` (random 20, shows the ok rate; stop and tell the user if it is low), then `enrich_verify.py verify <run>`. MillionVerifier key `MILLIONVERIFIER_API_KEY` in the project `.env`. **If the key is missing the script prints a clear message and skips**: emails stay `unverified` and no Ready: Email rows are produced; add the key and re-run, nothing is lost. Rules: only `ok` passes; `catch_all` is recorded as `catch_all` and kept for a later secondary verifier; `unknown`, `invalid`, `disposable` fail; `error` is retried on the next run. Apollo's own "verified" is a hint, never the gate. Results are cached per email.
4. `enrich_verify.py all <run>` does enrich, verify (if the key exists), the waterfall list and the quality report in one go.
5. Missing or failed emails: `people.csv` column `waterfall_needed` (email_missing, email_invalid, email_unknown, email_role_address, catch_all_secondary_verify) and the hand-off file `enrich/waterfall-needed.csv`. Prospeo and Amplemarket are NOT set up: `lib/waterfall.py` only holds hooks. Do not call them.
6. List quality: `enrich_verify.py quality <run>` writes `list-quality.md`, `verify/quality.json`, the grade into `summary.md` and the Run Log. It is a port of the 8 checks of list-quality-scorecard (verification, duplicate emails, domain concentration, title relevance, bad titles, role and catch-all, ICP fit, name quality). Under 100 rows the grade is indicative only. Below C: fix the top issues before launching. Show the grade and the top issues to the user.

7. Employment exclusions start here: bulk_match also returns the person's headline and employment history, kept in `enrich/enrich.jsonl`. After the sync, people who are on garden leave, retired, on a career break, between roles, Open to Work, or whose current role has ended (Apollo history lists only jobs with an end date and none current, or the role at the target company has an end date) get `exclusion_reason` and channel none. Rows stay. The count appears in `summary.md` and the Run Log ("exclusions"). Show it to the user with two examples and say Apollo employment data can be stale. Keywords: `config.json` `exclusions`. See the README section "Employment exclusions".

Next: `/iv-activity <run>`, then `/iv-phones <run>`, then `/iv-ready <run>`.

## Gotchas
- MillionVerifier needs a browser User-Agent (403 otherwise); the client sends one. The key is never printed or logged.
- Duplicates by LinkedIn URL or email found after enrichment are marked `duplicate` (the better-ranked row stays); the freed cap slot is not refilled.
- A catch-all result is not a pass. Do not send to catch-all addresses until a second verifier has judged them.
- No em dashes in anything written.
