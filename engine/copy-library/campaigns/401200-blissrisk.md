# BlissRisk

- HeyReach campaign id: 401200 (read only copy, status FINISHED, created 2026-04-20)
- Idea: BlissRisk | Persona: ? | Region: ? | Sender: ?
- Leads: 150 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: VIEW > INMAIL))`
- Results: invites sent 143, accepted 13 (9%); messages sent 2, replies 3 (23%); InMails sent 0, replies 10 (8%); tagged interested 9
- Rules today: em_dash x2, placeholder x2  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 43 words, rule errors: placeholder

```
Hi {FIRST_NAME} - {Custom_Message}, I’d love to speak with you about being an advisor to my new risk intelligence startup. I’m confident it will surpass my previous companies - Reachdesk (valued at $225M) & Yieldify (sold to Publicis). Are you free to discuss?
```

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 1 DAY, path: accepted)

**Variant 1**, 67 words, rule errors: em_dash

```
Hey {FIRST_NAME} - Great to be connected! 

As mentioned, I’d love to catch up and share more about the risk intelligence startup I’ve co-founded and explore whether it could be a fit for you to join as a strategic advisor. I believe it has the potential to be bigger than any company I’ve worked on before! 

Are you open to a chat to discuss in more detail?
```

## Step 4: Message (asks for a call, close-out, wait 2 DAY, path: next)

**Variant 1**, 41 words

```
Hi {FIRST_NAME},

Thought I'd try one last time as I'm very keen to chat with you about my new startup. Do you have some time you can spare to see if there's an opportunity for you to be involved?

Best,
Meelan
```

## Step 5: View profile (warm-up) (View profile (warm-up), wait 1 DAY, path: not_accepted)

## Step 6: InMail (InMail: opener, advisor ask, credibility, wait 1 DAY, path: next)

**Variant 1**, 43 words, rule errors: placeholder
Subject: Advisory for my Risk Intelligence startup

```
Hi {FIRST_NAME} - {Custom_Message}, I’d love to speak with you about being an advisor to my new risk intelligence startup. I’m confident it will surpass my previous companies - Reachdesk (valued at $225M) & Yieldify (sold to Publicis). Are you free to discuss?
```

