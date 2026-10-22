# Idea Launch engine (Claude skills): plan

Goal: launch an idea-validation campaign quickly from the idea memo, end to end, as Claude commands.
Scope v1 (agreed with Afroz, 2026-10-21): get to a verified, tiered, ready-to-launch list, with copy drafts, a reply-agent idea page and DRAFT campaigns. No live sending.

## Pipeline (one Google Sheet per idea)
1. /iv-brief: memo + ICP docs -> brief (Apollo company filters, target titles, tier rules, exclusions, credit budget). Discussed and confirmed with Afroz before anything runs.
2. /iv-accounts: Apollo company search -> Accounts tab (every company kept).
3. /iv-qualify: AI fit check per company (keep/drop + reason + score). All qualified companies stay in the pool.
4. /iv-people: Apollo people search by target titles on qualified accounts. Companies with no people found -> "Accounts: No People" tab (fallbacks later).
5. /iv-tier: AI tiering T1/T2 (or X, not a buyer) with a reason, tuned with the user on samples of 10, then caps (T1 5, T2 3 per company). T1 = LinkedIn + email + call. T2 = LinkedIn + email.
6. /iv-enrich-verify: Apollo bulk_match for the capped people (full name, LinkedIn URL, email), MillionVerifier on the emails (only ok passes; missing or invalid listed for the Prospeo and Amplemarket waterfall later), list quality grade.
7. /iv-activity: LinkedIn activity check (existing n8n checker, switched on for the run only). Inactive -> email only; no valid email -> LinkedIn only.
8. /iv-phones: T1 phone numbers via Apollo (asynchronous, n8n receiver webhook). Prospeo and Amplemarket later.
9. /iv-ready: channel per person and the three Ready tabs (LinkedIn, Email, Calls for Mansi).
10. /iv-copy: V1 copy and variants per channel and tier, built from the approved copy library plus frameworks from the GrowthEngine repo (MIT).
11. Reply agent idea page: create the idea's page in Notion "Idea Contexts" (from the memo) so the reply agent can draft from day one.
12. /iv-launch: DRAFT campaigns in HeyReach (LinkedIn) and Smartlead (email), plus a call sheet for the cold callers. Nothing is started. (v1: HeyReach only and the call sheet for Mansi, T1 only, per the Decisions.)
13. /iv-run <idea>: runs everything in order, with approval gates before spending credits and before creating campaigns. (Per the Decisions there are no credit gates, usage is only logged; the approval before creating campaigns stays.)

## Decisions (Afroz, 2026-10-21)
- Inputs: the memo and ICP doc come in any format (Notion, Google Doc, PDF, pasted text). /iv-brief normalises them.
- ICP, titles, countries, tiers: decided in /iv-brief through back-and-forth between Claude and the user. Claude never decides them alone.
- People per company: up to 5 T1 and 3 T2 (idea validation, more signal is fine).
- No credit caps or approval gates for credits. Log usage only.
- Copy library: none yet. Build it by templating copy from campaigns already launched on HeyReach (their sequences).
- Copy voice: LinkedIn messages as if from Jay or Meelan (founders). InMails as from a founder's office associate (an employee). No default senders.
- Launch v1: HeyReach only (draft campaign or list ready). Smartlead later (inboxes are already set up).
- Call sheet: for Mansi, T1 leads only.
- Anyone can run the commands, so it's a repeatable system users can improve themselves (clear READMEs, config in files, not in code).
- Build: Sonnet subagents build each phase, an Opus subagent validates it before the next phase starts.

## Target volume per idea (default)
2,000 to 3,000 people with verified emails, and at least 800 people active on LinkedIn. Account search is sized from this target (people per account x verify and activity drop-off rates).

## Google Sheet tabs
1 Brief | 2 Accounts | 3 Accounts: No People | 4 People | 5 Ready: LinkedIn | 6 Ready: Email | 7 Ready: Calls | 8 Copy | 9 Run Log

## Principles
- Python scripts do the API work (pagination, rate limits, credit tracking); Claude does the judgement steps (qualify, tier, copy).
- A run folder per idea (runs/<date>-<idea>/) with stage files plus state.json, so a run resumes and never re-pays.
- Each stage processes only new rows. Dry run (estimate) first. No credit caps (usage logged only). Approval before creating campaigns.

## Later (not v1)
Dedupe and exclusions (needs a central database), a second verifier for catch-all emails, sender and capacity orchestration, personalisation, the Prospeo and Amplemarket fallbacks.

## Phases
1. Foundation + /iv-brief, /iv-accounts, /iv-qualify
2. /iv-people, /iv-tier, /iv-enrich-verify, /iv-activity, /iv-phones, /iv-ready (built; the plan's single /iv-verify became /iv-enrich-verify plus /iv-activity, and /iv-ready was added)
3. /iv-copy, /iv-idea-page (the reply-agent idea page), /iv-launch, /iv-run (built; see "Commands" below)

## Commands (all built)
/iv-brief, /iv-accounts, /iv-signals, /iv-qualify, /iv-people, /iv-tier, /iv-enrich-verify, /iv-activity, /iv-phones, /iv-ready, /iv-copy, /iv-idea-page, /iv-launch, and /iv-run <idea> (runs them all in order, resumable, stops only at the user's decisions). Pipeline items 10 to 13 above map to /iv-copy, /iv-idea-page, /iv-launch and /iv-run.

## Notes on later changes (2026-10-22; built from CHANGES-PROPOSAL-2026-10-21.md, the Decisions above are unchanged)
These are additions, not edits to the Decisions. Where they touch a Decision it is said here.
- **Company signals** (`/iv-brief` asks, `/iv-signals` enriches, `/iv-qualify` uses): the brief gains `signals` (employees, engineers, operations, sales and other departments from Apollo organization enrichment, plus free-text signals), each with a threshold and hard or soft, decided WITH the user (consistent with "ICP, titles, countries, tiers: decided through back-and-forth, Claude never decides alone"). Hard thresholds drop a company automatically (flag drop, row kept); soft ones inform the AI judge. Enrichment costs 1 Apollo credit per matched company, once per company, logged only (consistent with "No credit caps or approval gates").
- **Pilot gates**: the engine now stops twice for a human: a pilot of 10 to 20 accounts (default 15) reviewed by hand before the full account pull, and a pilot of 10 to 20 people before enrichment credits. These are decision stops for the user (like the brief, copy and launch approvals), not credit gates, so they do not conflict with "no approval gates for credits". Approved pilot accounts become seeds (`is_seed`) for the later lookalike expansion. Pipeline order is now: brief, account pilot, accounts, signals, qualify, people, tier, people pilot, enrich + verify, activity, phones, ready, copy, idea page, launch.
- **Employment exclusions**: people on garden leave, retired, on a career break, between roles, Open to Work, or with an ended current role get channel none and an `exclusion_reason` after enrichment and activity (rows never deleted); the keyword list is in `config.json`.
- Pipeline items 2, 3, 5 and 6 above read with these additions; `/iv-run` stops at both pilot gates. Open: `lookalike` expansion from the seeds and a vendor trial harness (CHANGES-PROPOSAL sections 2 and 3) are not built.
