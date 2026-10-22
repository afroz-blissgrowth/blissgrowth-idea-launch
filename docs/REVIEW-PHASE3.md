# Idea Launch: Phase 3 review (and end-to-end check)

Reviewer: Opus quality review, 2026-10-21. Scope: `/iv-copy`, `/iv-idea-page`, `/iv-launch`, `/iv-run`, new modules (`heyreach`, `copylib`, `copyrules`, `copydraft`, `ideapage`, `launch`, `orchestrate`), changed modules (`stages`, `run`, `schema`), `bin/` scripts, `copy-library/`, tests, all `iv-*` skills, README, NOTICE, config. Live checks were read only: the reply agent workflow `xwpVwqkcmQecgwlk` (n8n API GET), HeyReach tool docs (schemas only). Nothing was created in HeyReach, no Apollo credits, no activity checker run, no workflow changed. The TEST Notion page was left in place.

## Verdict: PASS WITH FIXES

Phase 3 is faithful to the Decisions and the engine hangs together from brief to DRAFT campaigns. Seven defects were fixed in place. The most important one: the reply agent ignores any campaign whose name does not start with "bliss", and the launch prefix did not come from the idea page. Tests went from 159 to 165, all passing (`python3 -I engine/tests/run_tests.py`). The open items are decisions or things to confirm on the first real launch. None of them can start or send anything.

## What was checked

- **Decisions.** Copy voice is enforced at ingest: `li_invite`/`li_followup` must have sender `founder` (Jay or Meelan, signed `{MY_FIRST_NAME}`), `inmail` must have sender `associate`. Voices and frameworks live in `config.json`. v1 is HeyReach only, and Smartlead appears nowhere in the code. Mansi's call sheet is T1 only (from `ready/calls.csv`), a separate sheet shared only with `launch.mansi_email`. `sheet.create` does not auto-share, so only she gets access. Her columns are never overwritten. Drafts are never started. Anyone can run it: config is in files, the senders and Mansi's email go in `config.local.json`, and each skill names the exact commands and the points where the user decides.
- **Copy rules** (`lib/copyrules.py`). The checker blocks: em and en dashes (also in subject and fallback), links in first messages (invite, InMail, follow-up 1), filler, internal idea names (config list, the run's name and slug, any `Bliss<Word>` except Blissgrowth), Blissgrowth misspelt, time commitments, pay and funding figures, the COS spam lists, silence closeouts, unknown placeholders, a missing fallback, and HeyReach length limits. The COS port matches the attribution in NOTICE.md. Pay detection had gaps (fixed, item 6).
- **Safety of /iv-launch.** `heyreach.py` has no start, resume, pause, stop or delete method, and a test checks both the source and `dir()`. Execute is refused for a TEST brief, a simulated copy or launch approval, a changed plan hash, plan blockers, missing sender ids and (new) a missing real idea page. Every created campaign is read back and must be DRAFT. The orchestrator only ever calls `launch_run.py plan`, `execute` (after an approval file exists, and the gates still apply) and `callsheet`. No code path starts or sends.
- **HeyReach API against the tool docs.** `campaign/Create` (DRAFT, `name`, `linkedInUserListId`, `linkedInAccountIds`, the exclude flags) matches. `AddLeadsToListV2` (`listId`, `leads` up to 100, lead fields) matches. The sequence rules match `validate_sequence`: 3 hour minimum after action nodes, both branches on CONNECTION_REQUEST and CHECK, a conditional END on MESSAGE and INMAIL, fallback variables, size limits. Field names disagree for `CreateEmptyList` (docs: `listName`, `listType`) and `UpdateSequence` (docs: `sequenceJson` string). Mitigated, item 4. The docs give a 1 to 50 character campaign name limit (open C).
- **Idempotency.** `launch/launch.json` saves after every list, lead batch, campaign, sequence and status check. A list or campaign with the same name that this run did not create is never touched. A create whose answer was lost is found on the re-run and refused, so a duplicate is never made silently. Re-running the call sheet only upserts changed rows.
- **Registry and READY** (13 steps: 12 registered stages plus the orchestrator). Status is derived from files. READY needs brief through idea_page to be done or skipped, and a non-test brief. `launch` is `post_ready`. Copy is not done with a simulated approval on a real run. Fixed: a TEST idea page counted as done for a real run (item 3).
- **/iv-run.** It stops at brief, qualify, tier, copy, idea page and launch approval (exit 10). It shows estimates and never gates on credits. It resumes from files, and a stage that runs with no change stops as `stalled` with a hint. Fixed: activity after a timeout (item 5).
- **Reply agent (live, read only).** Node "Match Idea": `if (campaign.toLowerCase().indexOf('bliss') !== 0) return [];`, then the HRA Ideas row with the longest `campaign_prefix` that the campaign name starts with. Putting the prefix first is correct. Before this review the prefix was never checked against this rule.
- **Tests.** Good offline coverage with fakes: refusals, idempotency, resume after failure, the sequence validator against a real sequence, the copy rules, idea page confirmation and dedupe, the orchestrator projection. Tests added for every fix.
- **Docs.** README, the skills and the skills README are consistent. A new teammate with `config.local.json` could follow `/iv-run` end to end. No em dashes.

## Issues

| # | Severity | Issue | Status |
|---|---|---|---|
| 1 | High | Reply agent match. Campaign names must start with "bliss" or the reply agent drops every reply silently. `launch.prefix_of` used only the brief, so a Campaign prefix set or adopted on the idea page was ignored, and nothing checked the "bliss" rule. | Fixed: the prefix comes from `idea-page.json`, then `idea-page/fields.json`, then the brief (a TEST page is ignored). The plan blocks, and `idea_page.py set-fields` refuses, a prefix that does not start with `launch.prefix_must_start_with` ("bliss"). README and skills updated. Tests added |
| 2 | Medium | `approve` approved a stale `plan.json` while `execute` recomputed the plan, so after any input change the run looped on "plan changed, approve again". | Fixed: `approve` recomputes the plan and refuses a stale file ("run plan again, show it, approve"). Gate text clarified. Test added |
| 3 | Medium | Launch did not require the idea page (the stage only blocks on pending or failed), and a TEST page record made `idea_page` done for a real run. | Fixed: a launch gate needs a real recorded page or a user skip. `check_idea_page` is partial for a TEST page on a non-test brief. Tests added and updated |
| 4 | Medium | HeyReach field names: `CreateEmptyList` sent `{name, type}` and `UpdateSequence` sent `{sequence}`. The docs say `listName`/`listType` and `sequenceJson` (a string). | Mitigated: both spellings are sent (unknown keys are ignored). Confirm on the first real launch, then drop the wrong one |
| 5 | Low | After an activity timeout, `/iv-run` re-ran `activity_run.py run` without `--resume`, sending a second Apify run. | Fixed: `--resume` when `activity/state.json` has `activated_by_us`. Test added |
| 6 | Low | Pay rule missed "paying", "$300 for your time", gift cards and vouchers, and "250 per hour" without a currency sign. | Fixed in `copyrules.py`. Test added. "Reachdesk (valued at $225M)" still passes |
| 7 | Low | `AddLeadsToListV2` failure counts were ignored. | Fixed: recorded in `launch.json` (`failed_leads`) and logged |
| A | Medium | The connect and InMail campaigns for T1 use the same list at the same time. With `excludeContactedFromOtherCampaigns` true, whichever campaign is started second skips those leads. With it false, a lead gets an invite and an InMail at once. | Open, decision: start InMail later on non-accepters (a separate list, or `excludeListId`), or drop one channel per lead |
| B | Low | Leads who are already connected get nothing (CHECK conditional goes to END). The library shows connected-path messaging getting 20% to 41% replies. | Open, judgement: add a connected branch (VIEW then follow-ups) |
| C | Medium | The docs give a 50 character campaign name limit. "BlissProductCompliance - T1 - USA - 2026-10-21 - InMail" is 55, yet 28 of the 79 existing campaigns are longer than 50. | Open: watch the first create. If it is rejected, set `launch.max_name_len` 50 and shorten the template (note in config) |
| D | Medium | The create endpoints have never run live. | Open: first launch with the smallest group, check it in HeyReach |
| E | Low | The HRA Ideas sync workflow is inactive, so a new page reaches the reply agent only after a manual run. | Open: the skill now says to run `sync-check` before pressing Start |
| F | Low | Prefix collisions: a new prefix that extends an old one (BlissAISecurityX) matches the old idea until the new page syncs. | Open, low risk |
| H | Low | `ideapage.payload` names the claude.ai Notion tool, while the project CLAUDE.md says claude.ai Notion is the Salescend workspace and the project `notion` MCP is Blissgrowth. The skill checks `notion-get-self` and stops when the workspace is not Blissgrowth, so the wrong workspace cannot be written to. | Open: use whichever connector reports Blissgrowth |
| G | Medium | Phase 2 carry-overs: issue A (phone reveal pays again, `phones_in_enrich` false and not implemented) and issue B (MillionVerifier key missing). | Open, waits for Afroz |

## Go-live checklist (first real idea)

1. `MILLIONVERIFIER_API_KEY` in the project `.env`, then `enrich_verify.py verify <run> --canary 20`.
2. Decide issue A (phones inside the enrich call, saves about 1 credit per T1 person). Until then leave `phones_in_enrich` false.
3. HeyReach sender ids in `config.local.json` `launch.senders` (`founders.jay`, `founders.meelan`, `associate`). `launch_run.py accounts` lists the ids in use. The associate account needs InMail (Sales Navigator or Premium).
4. Mansi's Google account email in `launch.mansi_email`.
5. Decide open A (InMail timing against the connect campaign) and B (already-connected leads).
6. A Campaign prefix that starts with "Bliss" (for example BlissProductRules), Calendly links for Jay and Meelan.
7. Teammates need `config.local.json` (Sheets Bridge secret) from Afroz.
8. First launch: execute, check the smallest group in HeyReach (list, leads, sequence, DRAFT, name length), and confirm the field names (issue 4).
9. Run "HeyReach Reply Agent | 4. Idea Sync" once and `idea_page.py sync-check <run>` before pressing Start.
10. After the run, replace `volume_assumptions` and the cost estimates with measured numbers.
