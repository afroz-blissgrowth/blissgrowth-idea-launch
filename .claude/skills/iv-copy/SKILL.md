---
name: iv-copy
description: Draft the LinkedIn connection invite, LinkedIn follow-ups (as Jay or Meelan) and InMail (as a founder's office associate) for an idea launch, V1 plus 2 to 3 variants per tier, check them against the Blissgrowth copy rules and the spam-word checker, tune them with the user on samples, and write the approved copy to copy.json and the "8 Copy" tab. Also builds the copy library from campaigns already launched in HeyReach. Use for "/iv-copy", "write the copy", "draft the LinkedIn messages", "build the copy library".
---

# /iv-copy: brief + memo + library patterns -> approved copy -> "8 Copy" + copy.json

Scripts (repo root, `python3 -I`, all under `engine/bin/`): `copy_library.py` (library) and `copy_run.py <command> <run>` (per run). Rules: `lib/copyrules.py` and `config.json` `copy`. Docs: `docs/ENGINE.md`.

Claude writes the copy (no model API key in the project). Scripts validate, store, show and record. The user decides. Never write the final copy (`approve`, `write`) without the user's explicit yes in this chat.

## 0. Copy library (once, refresh when asked)
`copy_library.py build` pulls every non-draft campaign of the BLISS HeyReach workspace (`HEYREACH_API_KEY`, read only), templates the text and writes `copy-library/campaigns/<id>-<name>.md` (+ `.json`) and `copy-library/index.md`. `copy_library.py search --kind invite|message|inmail --idea X --persona X` ranks campaigns by rate. Read `copy-library/README.md` (patterns) and the index before drafting. The library is a source of STRUCTURE and angles. Old wording often breaks today's rules (quick chat, internal idea names, time commitment): the index shows how many errors each campaign would have. Never copy it word for word.

## 1. Prepare
1. `copy_run.py context <run>` writes `copy/context.json`: idea, ICP, tier rules, tiers that have people in "5 Ready: LinkedIn", the slots to fill, variant counts, rules, the names that must never appear. Read it, the run's `memo.md`, and the idea page text if it exists (`idea-page/fields.json`).
2. Agree the angle with the user in two lines before drafting (what we ask, what we say the idea is in plain words). They decide.

## 2. Draft (Claude)
Write ONE strict JSON array (no fences) to the scratchpad. One item per slot and variant:
`{"channel":"li_invite|li_followup|inmail","tier":"T1|T2|all","step":1,"variant":"V1","subject":"(InMail only)","body":"...","sender":"founder|associate","fallback":"...","note":"why this angle"}`
- Slots: invite (step 1), follow-ups steps 1 to 3, InMail (T1 by default, `launch.inmail_tiers`). Per slot V1 plus 2 to 3 variants (3 to 4 in total; a `blank` invite counts as a variant). Tiers may have different copy; a tier item beats an `all` item.
- Voices: LinkedIn invite and follow-ups are Jay or Meelan (first person, sign off with `{MY_FIRST_NAME}`, the same text works for either). InMail is a founder's office associate ("I work with Jay and Meelan at Blissgrowth"), subject at most 60 characters. No default sender is assumed.
- Frameworks: advisor ask, not sales. Ask before pitch (a question the reader can answer in a few words), permission opener, confirmation CTA, 25 to 95 words for follow-ups, each follow-up standalone with a different angle (problem, expertise check, opinion question, soft ask for advice). The idea is described in plain words, never by its internal name.
- Rules (the checker enforces them): no em dashes, no links in first messages, no "quick chat", "just checking in" or other filler, never an internal idea name (BlissSLM etc.), no time commitment ("30 min", "brief call"), no pay numbers, no funding amounts, always spell Blissgrowth, invite at most 300 characters, InMail body at most 1,900. Placeholders: `{FIRST_NAME}`, `{COMPANY}`, `{POSITION}` etc.; anything beyond first and last name needs a `fallback` text without them.
- A valid draft passes with no errors. Warnings (flagged single words such as "get", "new", "now", sales tone, no question, length) should be fixed unless there is a reason.

## 3. Check and tune (with the user)
1. `copy_run.py ingest <run> draft.json` (shape errors reject an item; rule errors store it as BLOCKED with the reason, fix and re-ingest, the last record per slot wins).
2. `copy_run.py show <run> --sample` then `show <run>`: show the user the copy as written, every variant, one slot at a time if long. Say which variant you recommend as V1 and why.
3. Ask: "What should change, or is this approved?" Count corrections K. `copy_run.py tune-log <run> --round N --corrections K`. Fix and re-ingest until a round has 0 corrections. For TESTS where no user reviews, label rounds and approval `--simulated` (kept in the files, sheet status says SIMULATED, and a simulated approval can never launch).
4. `copy_run.py approve <run> --note "<who approved>"` only after the user said yes to exactly the shown text. Any later change makes the approval stale.

## 4. Write
`copy_run.py write <run>` writes `copy.json` and upserts the "8 Copy" tab (status `draft` or `approved`, rows are never deleted, withdrawn items get status `withdrawn`). Report counts, warnings left, and the sheet link. Next: `/iv-idea-page`, then `/iv-launch`.
