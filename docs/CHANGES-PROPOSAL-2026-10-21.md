# Idea Launch engine: proposed changes (2026-10-21)

Sources: Fireflies 01M5CMAGBNXC6D4ASN19JYXWAC (Prajwal / Afroz / Punith / Matthew, 52 min, read in full) plus summary; web research; GrowthEngine `disco-like` and `list-expander` skills. No call with Darshan, Prajwal and Punith together exists in Fireflies for 18 to 21 Oct (the "ColdCall Dashboard Sync" has Darshan, Punith, Maddy and is about dashboard tags only; "Founder + Idea Engine Catch Up" is silent, no transcript).

## 1. What stood out in the call
- Wrong ICP is the real pain. Punith: "the team is getting a bit tired of wrong icp". Prajwal: "the first definition that gets to you needs to be really good and the first 10, 20 subset ... needs to be reviewed properly".
- Memo text is imprecise and the AI over-reads it: "we just mention CFO is a champion ... and it pulls the CFOs into the list as well".
- Signals beat broad filters. Prajwal: Rubix DACH has mostly sales staff and no engineering, so it has the ERP problem; Zalando has about 2,000 engineers and 1,000 IT, so it does not. "We can't do blind campaigns."
- Seeds come from competitors' customers and website customer lists (Matthew sent 17). Reverse search: if a company names a consultancy or tool, find that vendor's other customers. Punith already hand-picked 10, used lookalikes and scraped SKU counts.
- Reinstate a 15 minute "Excalibur" signal review (Matthew, Prajwal) before handoff; Prajwal forwards ICP to Jay.
- Afroz: "get a list of 100 accounts that we feel are really solid, do a manual check, find all the most relevant people and offer a paid call". Prajwal: downstream, "we can manage".
- Exclude garden leave, retired, career break, ended-role (experience array end date), Open to Work. Scrape recent posts only after the activity pass (about 500 people), not the raw list.
- Tools: Prajwal advises against Claude native web search, suggests Hermes (uses Exa and similar) and DeepSeek search API (about $0.75 per 1,000 results, his figure). Disco about $99/month, Deepline pay as you go, AI Ark lookalike (trial), LeadOcean on AppSumo. Apollo used 7,800 of 20,000 credits last month. Apollo's free people search is the thing alternatives lack. Decision: Afroz trials, reviews manually, then decides.
- Tiering already in use by Punith (revenue, SKU bands: tier 2 is 50k to 100k SKUs).

## 2. Proposed engine changes

| Change | Skill(s) | Effort | Today? |
|---|---|---|---|
| Pilot gate: pull 10 to 20 accounts, human marks keep/drop with reason, then expand. Hard stop before scale pull. Same for 10 to 20 people before enrich credits | /iv-accounts (add `--pilot 20` and an approval file), /iv-people, /iv-run (new user stop) | S | Yes |
| Signal fields in brief: engineering headcount, IT headcount, sales share, tools, consultancy, SKU or size proxy, plus 3 to 6 seed accounts and buyer profile from the memo author | /iv-brief (new interview block), /iv-qualify (judge prompt uses signals, outputs evidence per signal) | M | Yes |
| Learn from the pilot: dropped rows' reasons become new `disqualifies` in qualify spec; kept rows become seeds | /iv-qualify, new `bin/seeds_from_pilot.py` | S | Yes |
| Lookalike expansion seeded from approved accounts, then re-qualify with the same judge, snowball until net-new is under 3% | new `/iv-lookalikes` (port GrowthEngine disco-like and list-expander phases 1, 2, 4), then /iv-qualify | M | After key |
| People filters: drop garden leave, retired, career break, open to work, ended experience entry (from Apollo match data and headline) | /iv-enrich-verify, /iv-activity | S | Yes |
| Post scrape for job signals only on the active shortlist | /iv-activity | S | Later |
| Vendor trial harness: run the same 20 seeds through each tool, human scores precision | new `bin/vendor_compare.py` | S | Yes |
| Paid experts track | new `/iv-experts` (see 4) | M | Design now |

## 3. Lookalike and discovery tools

Pricing figures are from third party pages and may be stale; confirm before buying.

| Tool | Input | What and accuracy notes | API | Price | Plugs in | Setup |
|---|---|---|---|---|---|---|
| DiscoLike | Seed domains, NL text, or both; negation domains; country | 65M to 80M domains, weighted industry, headcount band. Seeds beat text (text is broad). Thin outside US. Count endpoint before paying | Yes, REST and MCP | Tiers $99 to $1,599/month, per-search plus per 1,000 records (repo skill: $0.10 per call, $2 per 1,000) | After pilot, before /iv-qualify | S, repo script exists |
| Exa (findSimilar, Websets) | Seed URL or NL query | Content similarity, returns homepage text (free evidence for qualify). Websets does criteria-verified lists. Good for odd niches, noisier at volume | Yes | Search about $7 per 1,000 requests; Websets $49 (8k credits) to $449; $10 free per month | Lookalike lane 2, or seed discovery from competitor pages | S |
| Ocean.io | Seed domains | Strong lookalike, enterprise leaning, quote based | Paid plans, contract | Unclear ($47 to $299/month cited, about $13 to $17 per 1,000 companies) | Alternative to Disco | M |
| Prospeo `company_lookalike` | One seed domain per call | Composable with location, headcount, keyword filters (per repo). We already plan Prospeo as waterfall | Yes, MCP exists | Paid tiers $39 to $249; lookalike credit cost unconfirmed | Cheap extra lane | S |
| Deepline | Not discovery | Claude Code CLI that orchestrates 40 to 97 providers, waterfall, managed at $0.10 per credit or bring your own keys | Yes | Pay as you go | Replaces Apollo enrich and phones, later | M |
| AI Ark | Seeds (per Afroz) | Lookalike finder, per-seat free pricing claimed ($49 per 5k credits, call figure). Not verified by me | Unknown | See call | Trial | S |
| Hermes Agent | Not a data tool | Open source self-improving agent from Nous Research (Feb 2026), 40+ tools incl. web search, cheap models via OpenRouter. Exa as its backend is unconfirmed. Useful as a research worker, not a source of truth | Self hosted | Free plus model cost | Optional: bulk signal research | M |
| Apollo, Clay | Filters | Apollo has no documented seed lookalike API; Clay is orchestration. Keep Apollo for free people search | Yes | Current | Already in | none |

Recommendation: adopt DiscoLike (seed fingerprint, negation, count first, $99 plan, script already written, matches the human-approved seed workflow) and Exa findSimilar (cheap, adds homepage text and covers what Disco misses). Run both on the same pilot seeds, let a human score the first 50 of each, keep the winner. Treat Ocean, AI Ark and Deepline as trials only after that. Our own Claude qualify step stays the final judge in all cases.

## 4. Paid experts track ("Top 100")
- Selection: after qualify and tier, score each T1 person (title fit, signal match, company is a seed lookalike, LinkedIn active, seniority, tenure). Claude ranks, then Matthew or Prajwal manually check the top 150 and keep 100. Output tab "Experts" with reason per person.
- Outreach: separate copy file and rules, not the main checker. The main rules ban pay figures; the expert track allows the fee and a time box but keeps: no links in message one, no em dashes, no filler, no pitch of the product. Frame: "paid research conversation about how you handle X", honorarium, one question. Sender is a founder (Jay or Meelan, who said he will pay for the best person).
- Channel: HeyReach invite plus email, calls booked directly. Not a cold-caller track.
- Budget: 100 invited, assume 10 to 20 percent accept, so 10 to 20 calls at $200 = $2,000 to $4,000 per idea. Needs a named approver (Jay) and a per-idea cap.
- Tools: expert networks quoted at roughly $500 to $1,500 per hour (Tegus about $550 per call), so direct outreach at $200 is cheaper and gives us the relationship. Network use only when the person cannot be reached directly.
- Risks: employees of large companies may be barred from paid consulting (conflicts, insider information); ask for confirmation they can take it, avoid anyone at a public company discussing non-public data, record consent.
- Build: copy in `copy/experts.json`, new stage `experts` after `ready`, nothing launches without Afroz and Jay approval.

## 5. Open questions for Afroz
1. Pilot size: 20 accounts and 20 people, and who reviews (you, or Matthew and Prajwal)?
2. Is the $200 for 30 minutes confirmed by Jay and Meelan, with a per-idea budget and approver?
3. Are paid calls offered to anyone at large employers, or only founders, owners and ex-employees?
4. Okay to buy a DiscoLike month ($99) and an Exa key now for the wholesaler pilot, using Rubix DACH, CNS Wholesaler and the 17 competitor customers as seeds?
5. Should the 15 minute signal review be a gate in /iv-run (blocking), or advisory?
6. Is the intended Darshan call a different meeting? It is not in Fireflies yet, send the title if it exists.
