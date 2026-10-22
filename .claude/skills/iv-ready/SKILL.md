---
name: iv-ready
description: Assign channels per person (T1 LinkedIn + email + call, T2 LinkedIn + email, minus inactive profiles and non-ok emails) and fill the three Ready tabs of an idea launch sheet (5 Ready LinkedIn, 6 Ready Email, 7 Ready Calls for the cold caller), plus the list quality grade. Use for "/iv-ready", "build the ready tabs", "channel assignment", "call sheet".
---

# /iv-ready: people -> channels -> "5 Ready: LinkedIn", "6 Ready: Email", "7 Ready: Calls"

Script: `engine/bin/ready_build.py <run>` (repo root, `python3 -I`). Logic: `lib/ready.py` and `lib/people.py` (`channels_for`).

## Steps
1. Check `summary.md` line 1: tier, enrich_verify, activity and phones should be done or skipped. If a stage is missing, say so and offer to run it first (building anyway is allowed, the tabs just hold less).
2. `ready_build.py <run>` writes `ready/linkedin.csv`, `ready/email.csv`, `ready/calls.csv`, upserts the three tabs (by `person_id`, only changes), grades the list, writes `ready/built.json` and `summary.md`.
3. Report: counts per tab, the list grade and top issues, the sheet URL, and the first line of `summary.md` (it is READY only when every stage is done and the run is not a TEST).

## Channel rules
- T1: LinkedIn + email + call. T2 (and unknown tier after a skipped tiering): LinkedIn + email.
- LinkedIn needs a profile URL and `linkedin_active` yes (unknown and unchecked do not count). Email needs a MillionVerifier `ok` (verdict `valid`). Call needs T1 and a phone.
- Only selected (capped, not duplicate) people qualify. Rows are never deleted: a person who stops qualifying is marked `withdrawn` in the tab.
- "7 Ready: Calls" is for the cold caller (Mansi): first and last name, title, company, phone, LinkedIn, email, idea, call notes (the tier reason and the other channels).
- No em dashes in anything written.
