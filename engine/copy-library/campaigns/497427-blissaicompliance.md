# BlissAICompliance

- HeyReach campaign id: 497427 (read only copy, status FINISHED, created 2026-07-07)
- Idea: BlissAICompliance | Persona: ? | Region: ? | Sender: ?
- Leads: 426 | Structure: `CHECK(connected: end | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 422, accepted 28 (7%); messages sent 20, replies 3 (14%); InMails sent 0, replies 0 (0%); tagged interested 1
- Rules today: filler x2, time_commitment x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 3 HOUR, path: accepted)

**Variant 1**, 64 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME}, great to connect.

Given your experience operating in regulated markets, I'd love to speak with you about being an advisor to my new AI compliance startup that protects businesses from millions in lost brand reputation and regulatory fines.

I'm confident it'll be bigger than my previous companies - Reachdesk (valued at $225M) & Yieldify (sold to Publicis). 

Open to a quick chat?
```

## Step 4: Message (advisor ask, asks for a call, wait 3 DAY, path: next)

**Variant 1**, 106 words, rule errors: time_commitment

```
Hi {FIRST_NAME}

As mentioned, given your tenure in regulated markets, I think you'd bring a lot of value to my new AI compliance startup as a strategic advisor.

As AI is used in more external communications, compliance teams must review a growing volume of both human and AI-generated content. They cannot manually review every email, message or marketing asset, despite each one carrying potential regulatory and reputational risk.

We are building {IDEA_PLAIN}.

Would you be open to a quick conversation this week or next?
```

