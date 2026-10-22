---
name: iv-idea-page
description: Create the idea's page in the Blissgrowth Notion database "Idea Contexts" so the HeyReach reply agent can draft replies from day one (Idea, Campaign prefix, Calendly links, Pitch, Who we're targeting, Idea specifics), from the memo and brief, with the user's confirmation of the text. Uses the Notion MCP tools, no Notion API key. Use for "/iv-idea-page", "create the reply agent idea page", "Idea Contexts page".
---

# /iv-idea-page: memo + brief -> Notion "Idea Contexts" page (reply agent) -> run record

Script: `engine/bin/idea_page.py <command> <run>` (repo root, `python3 -I`). Config: `config.json` `idea_page`. Docs: `docs/ENGINE.md`, section "Reply-agent idea page".

## Which Notion
The page goes into the BLISSGROWTH workspace, database `e895ef6bf69d41cf9faf11e1cbbdee4f`, data source `collection://3d6bd3e8-f4a2-4ea6-a266-4ce299131652`. Use the Notion MCP tools of the person running Claude Code (project `notion` MCP, or the claude.ai Notion connection if it is the Blissgrowth workspace). Check first: `notion-get-self` must say workspace "Blissgrowth" and `notion-fetch` of the collection URL must work. If it is the wrong workspace, stop and tell the user to authenticate the right one (`/mcp`). No Notion API key is used.

## Steps
1. Never twice: `idea_page.py status <run>` (a recorded page means done). Then query Notion for an existing page: `notion-query-data-sources`, mode `rows`, data_source_url above, filter `Campaign prefix` (text) `string_is` the idea's prefix (the idea name, for example BlissProductCompliance). If one exists, show it to the user and `idea_page.py record <run> --url <page url> --adopt` (record the existing page, do not create another). Update an existing page only if the user asks.
2. Look at one or two existing pages (same query without the filter) for the style: short lines, A) B) C) personas, "Different because:", "Idea specifics" with the rules for the reply agent (never give amounts or investor names).
3. `idea_page.py starter <run>` prints a mechanical start. Rewrite it from `memo.md` and `brief.json` into the seven properties and write them to the scratchpad as `fields.json`: Idea, Campaign prefix (the campaign names will START with it, so keep it exact; it must start with "Bliss", the reply agent ignores other campaigns, and `set-fields` refuses it), Calendly (Jay), Calendly (Meelan) (ask the user if unknown, leave empty only on their say-so), Pitch (what it is, how it works, "Different because:"), Who we're targeting (A) B) C) with tiers), Idea specifics (stage, funding wording allowed, what never to say, the ask, founder track record if allowed). No em dashes, spell Blissgrowth, no funding amounts or investor names. Each property at most 2,000 characters.
4. `idea_page.py set-fields <run> --file fields.json` (validates), `idea_page.py show <run>`: show the user the text exactly as it will be written. Ask for corrections until they confirm.
5. `idea_page.py confirm <run> --note "<who confirmed>"` (only after the user said yes; `--simulated` for tests, labelled).
6. `idea_page.py payload <run>` prints the exact `notion-create-pages` arguments. Call that Notion tool with them (parent data_source_id, properties). For a TEST run use `payload --test`: the page is named "TEST DELETE ME - ..." with a TEST prefix; never delete it yourself, tell the user (deleting needs their explicit ask).
7. `idea_page.py record <run> --url <the new page link> [--test]` stores `idea-page.json` in the run folder. Refuses a second record.
8. Sync: the n8n table HRA Ideas is filled by the workflow "HeyReach Reply Agent | 4. Idea Sync" (id TwQx8DHxkrSW98g6, reads the Notion database through a Notion credential and upserts into the table). It was INACTIVE on 2026-10-21. `idea_page.py sync-check <run>` reads the table (read only) and says whether this page is in it. To sync: run that workflow once by hand in n8n (Execute workflow), or activate it (then every 15 minutes), or POST its webhook `hra-idea-sync-run` while it is active. Tell the user, do not activate workflows yourself. The reply agent matches a campaign to its idea by the Campaign prefix at the start of the campaign name.

Skip only on the user's say-so: `idea_page.py skip <run> --note "why"`.
