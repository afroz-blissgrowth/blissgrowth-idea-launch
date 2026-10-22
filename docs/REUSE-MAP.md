# Idea Launch: reuse map

Sources: COS = coldoutboundskills (MIT, copy or adapt with notice). CIQ = ColdIQ-s-GTM-Skills (no license, ideas only, write our own text).
Both are TypeScript (run with `npx tsx`, no deps, Node 18 fetch) plus one Python Sheets pusher. We plan Python, so everything is a port, not a copy-paste. State is flat files per run (stream CSVs, WAL, state.json), no database required.

## Per step

**1 Brief (/iv-brief)**
- COS: `icp-onboarding/SKILL.md` (adapt): ask one question at a time, pre-fill from scraped context, split HARD vs SOFT with "would you still reach out if only this differs?", output a yaml. Swap website interview for memo + ICP docs. `list-builder` Phase 0 intake (7 lines) for the exclusions/bands shape.
- CIQ: ICP 3 layers (firmographic, technographic, behavioral) and the 100-point scoring matrix as a checklist for what the brief must cover.
- Build: brief schema with Apollo filters, titles with synonyms, tier rules, credit budget, volume math (people per account x verify and activity drop-off).
- Gotchas: triggers are soft, never hard filters. Always include title synonyms. Prospeo industry enums do not map to Apollo; ours need the Apollo taxonomy.

**2 Accounts (/iv-accounts)**
- COS: `list-expander/SKILL.md` exhaustive-sweep law (wide net on industry and keywords, only band and geo as hard pre-filters, AI decides fit) and `perfect-company-list` rationale. `pull.ts` auto-shard idea (country to state to headcount bisection) because Apollo also caps results (about 50k, 100 per page x 500 pages).
- Build: Apollo client with pagination, rate limit, credit log. Count-first sizing before paging.
- Gotchas: industry labels are self-reported and wrong often; do not over-filter by industry.

**3 Qualify (/iv-qualify)**
- COS: `list-builder/prompts/_TEMPLATE.md` (copy nearly verbatim): ICP, QUALIFIES, DOES NOT QUALIFY plus 4 mandatory blocks (absent size is not a reject, geo/size handled by filters, sparse sites ok, judge on identity language, lean thin evidence to keep). `icp-prompt-builder` tuning loop. `score-batch.ts` (port): strict JSON `{qualified, confidence, reason}`, streaming CSV, resume, 120s row deadline, one retry pass. `list-expander/verify-website.ts`: live homepage fetch drops dead/parked sites (about 10% ghosts).
- CIQ: three-tier qualification prompt shape (tier + one-sentence reason).
- Build: runner using Claude (Haiku-class) in batches of 10-20 companies per call, or Task sub-agents. Their default uses OpenAI nano; we should not add a key unless cost demands.
- Gotchas: keep low-confidence rows, flag instead of drop. Judge only on evidence given.

**4 People (/iv-people)**
- COS: `prospeo-search-api` (pagination, 25k cap, state-splitting concepts only). `list-builder` hard rule: pull all matching titles. We should cap instead (decision: 2-3 per account, as CIQ `max_person_per_company`).
- CIQ: find-contacts smart title expansion, role-based passes.
- Build: Apollo people search by org id and titles, dedupe by LinkedIn URL then domain+name (`contacts-merge.ts` logic), "No People" tab.
- Gotchas: Apollo search returns obfuscated emails; reveal costs credits.

**5 Tier (/iv-tier)**
- CIQ: company tier x contact tier matrix, contact tiers by seniority (C-level/Founder/VP, Manager, IC). Use as the T1/T2 rule skeleton.
- Build: our own T1/T2 prompt and reasons. COS has no tiering.

**6 Verify (/iv-verify)**
- COS: only guidance. No MillionVerifier script ships (only mentions in `list-builder`, `blitz-list-builder`). Keep rules: provider "verified" is a hint, MV `ok` is the gate, drop catch-all and unknown. `list-quality-scorecard/scripts/score-list.ts` (port the 8 checks: dupes, domain concentration, bad titles, role addresses, name quality).
- CIQ: 20-address spot-check on a verifier we control; role-based and free-mail removal.
- Build: MV client (browser User-Agent or it 403s), Apollo fallback enrichment, LinkedIn n8n hook, quality gate summary.

**7 Phones**: nothing to reuse. Build Apollo reveal with a T1-only cap.

**8 Copy (/iv-copy)**: see frameworks below. COS `campaign-copywriting` 4-step confirm flow, `variants.yaml` schema (adapt), `spam-word-checker` (copy list, our context), `smartlead-spintax` (adapt, optional).

**9 Notion idea page**: build ourselves. Nothing equivalent.

**10 Launch (/iv-launch)**: COS `smartlead-campaign-upload-public/scripts/upload.ts` (port): create campaign, sequences with variants, attach inboxes by tag, batch 100 leads, schedule, never start. `smartlead-api` as endpoint reference. HeyReach and call sheet: build (use existing MCP).

**Sheet**: COS `push-sheet.py` (adapt): replace tab, header bold, chunks of 2,000. Add our 9 tabs.

## Patterns to adopt
- Run folder + `state.json`; stage completion decided from artifacts, atomic writes, config hash, re-run same command resumes (`run-lane.ts`, `RUNBOOK.md` decision table and failure playbook).
- `summary.md` line 1 is READY or NOT READY with the next command.
- Canary 50-100 rows before every full run; show first output before scale.
- Prompt-tuning loop: batches of 10, need 2 clean rounds, save locked prompt per idea (`icp-prompt-builder`).
- Approval gates: DRAFT only, human presses Start.
- Registry/WAL dedup idea for later central database.
- Experiment design: one variable per test (`experiment-design`), useful for idea A/B.

## Copy frameworks (advisor ask, not sales)
- COS: confirmation CTAs ("Is this still the case?"), "can they reply in 5 words", 50-90 words, standalone follow-ups, no weak openers, rotate angles per follow-up.
- CIQ: Ask Before Pitch, Neutral Insight, Josh Braun style (permission, poke, no pitch), 60-90 words, one soft CTA.
- Adapt: replace value-prop/proof with "we are exploring X, you know this space, 2 questions?". Drop case-study and "3 offers" blocks.

## Do not reuse
- Blitz, DiscoLike, GetLeads, Exa/Parallel lanes, Google Maps/Yelp: tools we lack or off-ICP.
- `zapmail-*`, `inbox-lifecycle`, `deliverability-*`, `email-deliverability-audit`, Instantly scripts: infra we do not run here.
- `lead-magnet-brainstorm`, `campaign-strategy` (15-25 ideas), `creative ideas` copy, `personalization-subagent-pattern` (per-lead personalisation is v2).
- CIQ "ColdIQ-first" blocks in every skill push their paid MCP; ignore. CIQ signal-sourcer scoring: later.
- COS Prospeo rate-limit and shard code: provider specific.
