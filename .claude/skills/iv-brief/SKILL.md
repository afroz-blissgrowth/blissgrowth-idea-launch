---
name: iv-brief
description: Start an idea launch. Ingest an idea memo and ICP doc in any format (Notion link, Google Doc, PDF, pasted text), then agree the targeting with the user one question at a time (Apollo company filters, countries, sizes, company signals such as engineering or sales headcount, target titles, T1/T2 rules, exclusions, volume, pilot size). Saves brief.json, creates the run folder runs/<date>-<idea>/ and the Google Sheet with the "1 Brief" tab. Use for "new idea launch", "/iv-brief", "build a list for <idea>".
---

# /iv-brief: memo + ICP -> agreed brief -> run folder + Google Sheet

Scripts live in `engine/bin/` (run from the repo root with `python3 -I`). Keys load from `.env` by themselves. Full system docs: `docs/ENGINE.md`. Brief schema example: `engine/examples/brief.example.json`.

Claude NEVER decides ICP, titles, countries or tiers alone. Propose, then get the user's yes.

## 1. Ingest the memo and ICP doc (any format)
Ask once: "Send me the idea memo and the ICP doc (Notion link, Google Doc, PDF, or paste)."
- Notion link or page name: try the `notion` MCP (Blissgrowth workspace) first; if it is not authenticated or the page is not found, try `claude.ai Notion`. Say which workspace answered.
- Google Doc / Drive link: Google Docs MCP `read_doc` or Drive MCP `read_file_content`.
- PDF: Read tool (use `pages` for long files). Pasted text: use as is.
- No ICP doc: the memo usually has an ICP/buyer section. Say so.
Normalise into a one-screen digest and show it: idea in one line, who buys, ICP segments (size, geography, categories), buyer titles, exclusions mentioned, price point. Save the digest to the scratchpad as `memo.md` (it is copied into the run folder). Ask: "Anything wrong or missing?"

## 2. Interview, one question at a time
Never batch questions. Pre-fill each from the digest ("The memo says X. Confirm or correct?"). Order:
1. Idea name and slug (lowercase-hyphen). Is this a TEST run? (a test brief can never be READY)
2. Segments for v1. Each segment becomes one Apollo `filter_set` with a label.
3. Countries (HARD). Apollo accepts country names such as "United Kingdom", "Germany", "United States" and region strings. Matches HQ location.
4. Employee band (HARD): actual numbers, format "25,1000". Several bands allowed.
5. Company keywords per segment. Wide net: Apollo industry labels are self-reported and often wrong, so do NOT filter on industry unless the user insists; use keyword tags (OR semantics) and let /iv-qualify decide fit. Ask for negative keywords too.
6. For every criterion above, ask the hard/soft test: "If a company matches everything except this, would you still reach out?" Yes = soft (log it, do not filter). No = hard. Triggers are never hard filters.
7. T1 titles with synonyms (e.g. COO, Chief Operating Officer, Head of Operations, Director of Operations). Push back on "CEO" for big companies.
8. T2 titles with synonyms.
9. Tier rules in plain words. Defaults: T1 = LinkedIn + email + call, T2 = LinkedIn + email. People caps default up to 5 T1 and 3 T2 per company (config.json).
10. Exclusions: domains (competitors, customers, partners), keywords.
11. Volume: default 2,000 to 3,000 verified emails and 800 LinkedIn-active. Run `python3 -I -c "import sys;sys.path.insert(0,'engine/lib');import volume,json;print(json.dumps(volume.sizing(),indent=1))"` and show how many accounts that implies; confirm the assumptions.
12. Qualify draft: ICP one-liner, what qualifies, what does not, and whether borderline cases lean keep. (/iv-qualify tunes it later.)
13. Company signals: see "Signals interview" below. Ask it AFTER the filters and BEFORE the titles are final, because the signals decide which companies are worth finding people for.
14. Pilot size: "The first pull is a pilot of 15 accounts that you review by hand before the full pull, and later 15 people before any enrichment credit. Keep 15, or choose 10 to 20?" Store as `pilot.accounts_size` and `pilot.people_size` only if it differs from the default (config `pilot`). The pilot gates cannot be skipped by Claude, only by the user (`pilot_run.py <gate> skip`).

## Signals interview (step 13): ask, never decide alone
Why: filters are broad and self-reported, signals are real data. From the call: Rubix DACH is mostly sales staff with no engineers, so it has the ERP problem (a fit); Zalando has about 2,000 engineers, so it does not (not a fit). The same industry label, opposite answers. "We can't do blind campaigns."
Claude asks and suggests, the user decides. Ask one question at a time:
1. "Which company signals matter for this idea?" Suggest options FROM THE MEMO (quote the sentence that suggests each one). The menu, using Apollo's organization data (`departmental_head_count`, `estimated_num_employees`):
   - total employees (a range, different from the Apollo search band if the user wants it tighter)
   - number of engineers (a max or a min, or engineers as a percent of employees)
   - number of operations people, sales headcount (or sales as a percent), IT, finance, marketing or any other department Apollo lists (`signals.known_departments` in config.json)
   - free-text signals Claude judges from the website and Apollo's technology list: tools used (for example SAP), uses consultancies, anything the memo names
   Always ask about the three core headcounts (total employees, engineers, operations people), even when the memo is silent, and let the user say "none". Beyond those, offer only signals the memo gives a reason for unless the user asks. Say plainly that headcounts are Apollo estimates, and that a company with no data is `unknown` and never dropped.
2. For each signal the user picks: the threshold in plain numbers ("at most 200 engineers", "sales at least 30 percent of staff") and HARD or SOFT. Use the same test as the filters: "If a company matches everything except this signal, would you still reach out?" No = hard (the company is dropped automatically, flag drop, reason "signal: engineers 2000 > max 200"). Yes = soft (shown to the AI judge, never drops alone). Free-text signals are always soft (a must-have criterion goes in the ICP hard list instead).
3. Read the list back in one table and ask "right?". Offer to check the thresholds on the pilot data before they bite.
4. Cost: enrichment is 1 Apollo credit per matched company (POST organizations/bulk_enrich, 10 per call), done on the pilot accounts first, then the rest after the pilot is approved. Each company is paid for once. Say it, there is no credit gate.
Save in `brief.json` as `signals`, a list: `{"name": "engineers", "source_field": "engineering", "op": "lte", "value": 200, "strength": "hard", "note": "why"}`. `source_field` is `employees`, an Apollo department key, or a department key plus `_pct` (percent of employees). `op` is lt, lte, gt, gte, eq, ne or between (value `[low, high]`); min means gte and max means lte. A text signal is `{"name": "uses_sap", "kind": "text", "description": "Runs SAP or another ERP", "strength": "soft"}`. Record the user's answers in `decisions`. `brief_save.py` validates the list and shows it in the "1 Brief" tab. If the user wants none, save no `signals` (the pilot gate still applies).

## 3. Write and confirm
Write the draft to the scratchpad as `brief.json` following the example (Apollo filter keys use Apollo's own names, e.g. `organization_locations`, `organization_num_employees_ranges`, `q_organization_keyword_tags`, `q_not_organization_keyword_tags`). Record each hard/soft answer in `decisions`. Read it back in plain language and ask "look right?".

## 4. Save
```
python3 -I engine/bin/brief_save.py --brief <scratchpad>/brief.json --memo-file <scratchpad>/memo.md
```
It validates, including the signals list and pilot sizes (fix any listed problem with the user), creates `runs/<date>-<slug>/`, creates the Google Sheet (nine tabs) through the Sheets Bridge, writes "1 Brief", and prints the sheet URL and the first line of `summary.md`. Re-running is safe, on any day (the newest run folder for the slug and its sheet are reused, a changed brief is archived). Add `--new-run` only if the user wants a separate run. Give the user the sheet URL and the next command: `/iv-accounts <slug>` (it starts with the pilot).

## Gotchas
- Always include title synonyms: "VP of Talent" alone misses most matches.
- Apollo industry taxonomy is not Prospeo's. Avoid industry filters; if used, names must match Apollo exactly.
- Editing Apollo filters after accounts were pulled needs `--accept-brief-change` in /iv-accounts (old pull is archived, never deleted).
- Do not use the founders' personal network lists until the ICP is confirmed.
- No em dashes in anything written.
