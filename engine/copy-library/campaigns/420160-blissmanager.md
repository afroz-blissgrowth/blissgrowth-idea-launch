# BlissManager

- HeyReach campaign id: 420160 (read only copy, status FINISHED, created 2026-05-06)
- Idea: BlissManager | Persona: ? | Region: ? | Sender: ?
- Leads: 302 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: VIEW > INMAIL))`
- Results: invites sent 277, accepted 53 (19%); messages sent 66, replies 12 (23%); InMails sent 0, replies 3 (1%); tagged interested 11
- Rules today: em_dash x2, funding_amount x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 49 words, rule errors: funding_amount

```
Hi {FIRST_NAME} - your team is at 100%+ capacity & top people are overworked answering colleagues all day. New company: each team member gets an AI twin that executes tasks & lets others query their knowledge directly. Prev: Reachdesk ($225M Series B), Yieldify (acq Publicis). Open to advisor chat?
```

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 1 DAY, path: accepted)

**Variant 1**, 69 words, rule errors: em_dash

```
Hey {FIRST_NAME} - Great to be connected! 

As mentioned, I’d love to catch up and share more about the new AI digital twin startup I’ve co-founded and explore whether it could be a fit for you to join as a strategic advisor. I believe it has the potential to be bigger than any company I’ve worked on before! 

Are you open to a chat to discuss in more detail?
```

## Step 4: Message (asks for a call, close-out, wait 2 DAY, path: next)

**Variant 1**, 41 words

```
Hi {FIRST_NAME},

Thought I'd try one last time as I'm very keen to chat with you about my new startup. Do you have some time you can spare to see if there's an opportunity for you to be involved?

Best,
{MY_FIRST_NAME}
```

## Step 5: View profile (warm-up) (View profile (warm-up), wait 1 DAY, path: not_accepted)

## Step 6: InMail (InMail: opener, advisor ask, credibility, asks for a call, wait 1 DAY, path: next)

**Variant 1**, 51 words, rule errors: funding_amount
Subject: Advisory for my AI digital twin startup

```
Hi {FIRST_NAME} - your team is at 100%+ capacity and top people are overworked answering colleagues all day. New company: each team member gets an AI digital twin that executes tasks and lets others query their knowledge directly. Prev: Reachdesk ($225M Series B), Yieldify (acq Publicis). Open to an advisor chat?
```

