---
name: iv-launch
description: After explicit user approval, create HeyReach lead lists from the run's "5 Ready: LinkedIn" leads and DRAFT campaigns (connect plus follow-ups from the founders, InMail from an associate) with the approved copy, never started, and build Mansi's separate call sheet. Names follow "<Idea> - <Tier> - <Region> - <YYYY-MM-DD>". HeyReach only (v1). Use for "/iv-launch", "create the HeyReach campaigns", "launch the list", "call sheet for Mansi".
---

# /iv-launch: Ready tabs + approved copy -> HeyReach lists + DRAFT campaigns + call sheet

Script: `engine/bin/launch_run.py <command> <run>` (repo root, `python3 -I`). Logic: `lib/launch.py`, client `lib/heyreach.py`, config `config.json` `launch`. Docs: `docs/ENGINE.md`.

## Hard rules
- NOTHING IS EVER STARTED. The client has no start, resume, pause or delete call. After creating a campaign the status is read back and must be DRAFT; the user presses Start in HeyReach.
- Explicit approval of the exact plan first. A TEST brief, a SIMULATED copy or launch approval, an unapproved or changed plan, or missing sender accounts refuse execution.
- Smartlead stays out (hooks only).

## Steps
1. Needs: `/iv-ready` done, `/iv-copy` approved (not simulated), `/iv-idea-page` done with a real page or skipped (execution refuses otherwise). `run_all.py next <run>` says what is missing.
2. Senders: HeyReach LinkedIn account ids for Jay, Meelan and the associate go in `config.local.json` under `launch.senders` (`founders: {jay, meelan}`, `associate`). `launch_run.py accounts` lists the account ids in use (read only). If unknown, ASK the user, do not guess. Mansi's Google account email goes in `launch.mansi_email`: ask the user if empty.
3. `launch_run.py plan <run>`: lists per tier x region (`launch.group_by`), campaign names, sequences (validated locally against HeyReach's documented rules), problems, and why execution is currently refused. Show `launch/plan.md` to the user: list names, lead counts, which copy goes where, who sends, that every campaign is a DRAFT. Naming convention: `<prefix> - <Tier> - <Region> - <date>` plus ` - InMail` for the InMail campaign. The prefix is the idea page's Campaign prefix (read from `idea-page.json`, then `idea-page/fields.json`, then the brief), the reply agent depends on it: its Match Idea node ignores any campaign whose name does not start with "Bliss", so the plan refuses such a prefix (`launch.prefix_must_start_with`).
4. Ask: "Create these lists and DRAFT campaigns in HeyReach?" Only on a clear yes: `launch_run.py approve <run> --note "<who approved>"`.
5. `launch_run.py execute <run> --dry-run` shows every gate and what would be sent. Then `launch_run.py execute <run>`: per group it finds-or-creates the list (an existing list with the same name that this run did not create is never touched without `--adopt-existing-list`), adds leads in batches of 100, creates the DRAFT campaign(s), sets the sequence (V1 to V4 variants rotate inside each step), verifies DRAFT. `launch/launch.json` records every id, so a re-run resumes and never duplicates.
6. Call sheet for Mansi (T1 leads with a phone): `launch_run.py callsheet <run>` (dry run) then `--execute`: a separate Google Sheet "<Idea> - Call sheet (Mansi) - <date>" shared only with `launch.mansi_email`, with her status columns (call_status, call_outcome, called_at, next_step, call_notes_mansi). Re-running adds new people and never overwrites her columns.
7. Report: lists and campaigns (ids, names, DRAFT), lead counts, skipped leads (no LinkedIn URL), the call sheet link. Remind the user: open HeyReach, check sender accounts and schedule, then press Start themselves. Before Start, `idea_page.py sync-check <run>` must say the page is in the n8n table HRA Ideas (the Idea Sync workflow is inactive by default; the user runs it once in n8n), otherwise the reply agent drafts without idea context.

First real run: the create endpoints were not exercised by the build agent (only read endpoints were tested live). Start with the smallest group and check the result in HeyReach before the rest.
