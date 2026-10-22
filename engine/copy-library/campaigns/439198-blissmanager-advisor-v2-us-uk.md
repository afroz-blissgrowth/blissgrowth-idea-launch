# BlissManager Advisor v2 - US/UK

- HeyReach campaign id: 439198 (read only copy, status PAUSED, created 2026-05-21)
- Idea: BlissManager | Persona: ? | Region: USA, UK | Sender: ?
- Leads: 712 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: end))`
- Results: invites sent 680, accepted 93 (14%); messages sent 94, replies 39 (42%); InMails sent 0, replies 0 (0%); tagged interested 35
- Rules today: em_dash x2, filler x2, time_commitment x2  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 48 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME} - Given your operational experience, I’d love to speak with you about being an advisor to my new AI Digital Twin startup. I’m confident it'll be bigger than my previous companies - Reachdesk (valued at $225M) & Yieldify (sold to Publicis). Open to a quick chat?
```

## Step 3: Message (opener, advisor ask, credibility, wait 1 DAY, path: accepted)

**Variant 1**, 67 words, rule errors: em_dash

```
Hey {FIRST_NAME} - Great to be connected! As mentioned, I’d love to catch up and share more about the company I’ve founded and discuss whether it might be something you want to get involved with as an advisor. I believe it has the potential to be bigger than any company I’ve worked on before! Are you open to speaking and seeing if it’s exciting enough for you?
```

## Step 4: Message (asks for a call, close-out, wait 5 DAY, path: next)

**Variant 1**, 41 words

```
Hi {FIRST_NAME}, Thought I'd try one last time as I'm very keen to chat with you about my new startup. Do you have some time you can spare to see if there's an opportunity for you to be involved? 

Best, 
{MY_FIRST_NAME}
```

