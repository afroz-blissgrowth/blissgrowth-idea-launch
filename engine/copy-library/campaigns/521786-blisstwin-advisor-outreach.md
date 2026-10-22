# BlissTwin Advisor Outreach

- HeyReach campaign id: 521786 (read only copy, status FINISHED, created 2026-07-24)
- Idea: BlissTwin | Persona: ? | Region: ? | Sender: ?
- Leads: 325 | Structure: `CHECK(connected: end | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 321, accepted 74 (23%); messages sent 59, replies 19 (27%); InMails sent 0, replies 0 (0%); tagged interested 16
- Rules today: filler x6, time_commitment x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 3 HOUR, path: accepted)

**Variant 1**, 71 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME}, great to connect.

Given your experience leading and scaling B2B sales teams, I'd love to speak to you about advising my new AI sales-enablement startup. It puts an always-on AI expert on your reps' live sales calls, so every rep can sell like your best one.

I'm confident it'll be bigger than my previous companies, Reachdesk (valued at $225M) and Yieldify (sold to Publicis).

Open to a quick chat?
```

## Step 4: Message (advisor ask, asks for a call, wait 3 DAY, path: next)

**Variant 1**, 91 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME}, following up as I think your experience building high-performing sales teams could be particularly valuable here.

Even the strongest reps struggle to recall every product detail, competitor difference, and objection response in the moment. We're building {IDEA_PLAIN}.

We're speaking with a small group of experienced sales leaders to help shape the product and advise us as we build.

Would you be open to a quick chat this week or next?
```

