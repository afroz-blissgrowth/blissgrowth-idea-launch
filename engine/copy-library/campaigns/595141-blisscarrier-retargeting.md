# BlissCarrier Retargeting

- HeyReach campaign id: 595141 (read only copy, status PAUSED, created 2026-09-10)
- Idea: BlissCarrier | Persona: ? | Region: ? | Sender: ?
- Leads: 328 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: end))`
- Results: invites sent 326, accepted 18 (6%); messages sent 22, replies 6 (33%); InMails sent 0, replies 0 (0%); tagged interested 5
- Rules today: filler x7, placeholder x3, time_commitment x5  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 47 words, rule errors: filler, placeholder, time_commitment

```
Hi {firstNameClean} - Given your operations experience, We'd love to speak with you about being an advisor to our new AI logistics startup. We're confident it'll be bigger than our previous companies - Reachdesk (valued at $225M) & Yieldify (sold to Publicis). Open to a quick chat?
```

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 3 HOUR, path: accepted)

**Variant 1**, 100 words, rule errors: filler, placeholder, time_commitment

```
Hi {firstNameClean}, great to connect.

Given your background, I imagine you've seen the significant amount of money carriers overcharge and the unclaimed refunds - 10% of all 3PL spend, based on our findings.

That's exactly the problem we're trying to solve with this new logistics startup. Our AI agents audit every invoice, find what they're owed, and recover it automatically.

We'd love to get your perspective and potentially bring you on as an advisor if you're interested.

We're confident it'll be bigger than our previous companies, Reachdesk (valued at $225M) and Yieldify (sold to Publicis).

Open to a quick chat?
```

## Step 4: Message (advisor ask, asks for a call, wait 3 DAY, path: next)

**Variant 1**, 93 words, rule errors: filler, placeholder, time_commitment

```
Hi {firstNameClean}, following up as I think your operational background could be particularly valuable here.

What's interesting is how much recoverable cash gets written off simply because supply chain teams don't have the bandwidth to pursue every claim through to recovery.

We think that's exactly where AI can unlock a lot of value. We're building {IDEA_PLAIN}.

Would you be open to a quick chat this week or next?
```

