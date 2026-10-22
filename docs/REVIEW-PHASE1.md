# Idea Launch: Phase 1 review

Reviewer: Opus quality review, 2026-10-21. Scope: `/iv-brief`, `/iv-accounts`, `/iv-qualify`, the library, the Sheets Bridge, tests, docs.

## Verdict: PASS WITH FIXES

The foundation is solid and faithful to the plan and the decisions. Nine defects were fixed in place (all small, tests extended from 31 to 33, all passing). The open items below are judgement calls or Phase 2 work, none blocks Phase 2 from starting.

## What was checked
- **Plan and decisions**: any-format memo ingestion (Notion, Docs, PDF, pasted), one-question-at-a-time brief where Claude proposes and the user decides, people caps T1 5 / T2 3 in `config.json`, target volume and volume math, no credit caps (usage logged only), HeyReach-only scope (nothing in Phase 1 touches launch), sheet tabs exactly as in PLAN.md, run folder, state.json, resume, READY semantics, config in files not code.
- **Reuse fidelity** against coldoutboundskills (MIT): `_TEMPLATE.md` (4 mandatory blocks ported nearly verbatim, block 2 parameterised by country; enforced by `check_prompt`), `score-batch.ts` (strict JSON `{qualified, confidence, reason}`, streaming append-only results, resume, 120 s row deadline, one retry pass, last record wins), `verify-website.ts` (same parked patterns, https then http, retry once on dead; we add `blocked` for 401/403/429/5xx so real sites are not dropped), `icp-prompt-builder` (batches of 10, fresh sample per round, stop after 2 consecutive clean rounds, never auto-approve), `icp-onboarding` (hard/soft test, triggers never hard). Attribution in NOTICE.md and module docstrings.
- **Correctness**: read every file in `lib/`, `bin/`, `workflows/`, `tests/`. Ran the offline tests. Live checks (2 Apollo credits total): `q_not_organization_keyword_tags` is honoured by org search (4,810 matches drop to 0 when the same keyword is negated); people `api_search` response shape. Bridge: `ping` and a read of the test sheet's "2 Accounts" tab work. The live workflow `WyIsq2lNqJEudsuv` was fetched read-only and is identical to `workflows/idea-launch-sheets-bridge.json` (nodes, parameters, connections). No expression contains an object literal, so the n8n `}}` bug cannot occur (bodies are built in Code nodes and passed as one string).
- **Secrets**: keys only from `.env`, bridge secret only in `config.local.json` (gitignored, along with `.env`), never logged; Apollo usage log has no key; error messages carry response text only.
- **Usability**: README plus the three SKILL.md files are enough for a new teammate to run the three commands. Descriptions trigger on the natural phrases.

## Issues

| # | Severity | Issue | Status |
|---|---|---|---|
| 1 | High | `Run.resolve("<slug>")` used a suffix glob, so a short slug such as `test` resolved to `...-blissproductcompliance-test` (wrong run, wrong sheet). | Fixed: exact `YYYY-MM-DD-<slug>` match (`lib/run.py`), test added |
| 2 | High | A `set-spec` after `lock` left the prompt "locked", so a changed, untuned prompt could be used for full scoring (breaks the explicit-review rule). | Fixed: lock is tied to the prompt's hash (`Qualify.is_locked`), test added |
| 3 | Medium | Running `batches` (or `retry`) after subagents wrote results but before `ingest` re-batched those rows, so they were scored twice. | Fixed: `batches` and `retry` ingest waiting result files first (`bin/qualify_run.py`) |
| 4 | Medium | A single persistent scoring error kept qualify `partial` forever; `run.max_error_rate_for_ready` was dead config. | Fixed: done when every row has an answer and errors are at or below the rate |
| 5 | Medium | `summary.md` could say READY right after `ingest`, before `finalize` had written `qualified.csv` and updated the sheet. | Fixed: done requires a `qualified.csv` newer than `results.jsonl`; summary says "run finalize" |
| 6 | Medium | Re-saving a brief on a later day created a second run folder and a second Google Sheet for the same idea. | Fixed: `brief_save.py` reuses the newest run for the slug; `--new-run` or `--date` forces a new one |
| 7 | Medium | `deploy_sheets_bridge.py` listed only the first 250 workflows; a miss would create a duplicate bridge on the same webhook path. | Fixed: follows `nextCursor`, stops on a listing error |
| 8 | Low | NOTICE.md shortened the MIT warranty paragraph (MIT asks for the full notice). | Fixed: full license text |
| 9 | Low | README mixed command paths relative to the repo root and to the idea-launch folder; people search note did not say last names are obfuscated and LinkedIn URLs are missing. | Fixed |
| 10 | Low | Empty `.lock` file (pid 0) was read as "locked by pid 0". | Fixed |
| 11 | Medium | Sheets are created in the Drive of the n8n credential's account (Afroz). Other teammates can run the commands but cannot open the sheet until it is shared. | Open: add a bridge `share` action (Drive permissions) and a `runner_email` in `config.local.json`. README now says to share by hand |
| 12 | Medium | PLAN.md "Principles" still says "Credit caps. Approval before spending", which contradicts the Decisions (no caps, log only). The code follows the Decisions. | Open: edit PLAN.md wording (owner's document) |
| 13 | Low | A full pull reuses `accounts.plan.json` if the brief is unchanged. If the plan is days old, leaf totals are stale and pages beyond the old total are not fetched. | Open: re-count when the plan is older than a few days |
| 14 | Low | Result-cap sharding and segment spreading are tested offline only. Credit cost of 1 per org-search page is from the docs, not measured. | Open: on the first real pull, compare `apollo-usage.jsonl` with Apollo's usage stats |
| 15 | Low | Parked detection (same patterns as COS, including "coming soon", "index of /", "related searches") auto-flags short pages without the model, so a few real small sites may land in `parked_site`. | Open: acceptable (rows are kept); consider sending parked rows to the model as low-confidence |
| 16 | Low | If Google refuses `create`, the bridge's later nodes run with an empty URL and the webhook returns non-JSON; Python reports it as an error (no sheet.json written, safe to retry). | Open, cosmetic |

## Phase 2 recommendations (structural, do before building)
1. **People search per company.** `api_search` returns no org id or domain per person, so query one company per call (`q_organization_domains_list[]` with one domain, or `organization_ids[]`) and attach the company from the query. Put T1 and T2 titles in one call and tier afterwards, to halve calls. 0 credits but the rate limit is 6,000 per hour: about 3,000 to 4,000 accounts is an hour or more, so use a per-org ledger (resume) and `run_in_background`.
2. **Enrichment is mandatory, not a fallback.** Search gives an obfuscated last name and no LinkedIn URL or email. Pick the capped people first (T1 up to 5, T2 up to 3), then enrich only those with `people/bulk_match` (10 per call, credits) to get full name, LinkedIn URL and email. Dedupe by Apollo person id, then LinkedIn URL. Log real credits per call (variable cost).
3. **Phones are asynchronous in Apollo.** Phone reveal delivers numbers to a `webhook_url`, so Phase 2 needs a receiving n8n webhook (a new action or a second small workflow) and a pending/received state per person.
4. **Schema migration.** Headers are written only at sheet creation and the bridge's upsert ignores unknown columns. Before adding People columns (for example `email_source`, `mv_result`, `linkedin_active`, `linkedin_checked_at`, `phone_source`, `channels`, `enrich_status`), add a bridge `headers` action that appends new columns to row 1 of existing sheets.
5. **Stage registry.** `STAGES`, `stage_status` and `next_command` in `lib/run.py` are hard-coded for three stages. Turn them into a small registry (name, artifact check, next command) so people, tier, verify and phones plug in with the same file-based completion and READY rules.
6. **Cap precedence.** One helper: `brief.people.caps` overrides `config.people_caps`.
7. **Verification.** MillionVerifier client with a browser User-Agent (403 otherwise), `ok` is the only pass, catch-all and unknown fail; cache per email. Activity checker: define the contract with the existing n8n checker (input LinkedIn URLs, output active true/false plus checked_at) and cache per URL so re-runs never re-check.
8. **Replace volume guesses** in `config.json` with rates measured on the first real run (qualify pass rate on the test run was 17 of 25, small sample).
