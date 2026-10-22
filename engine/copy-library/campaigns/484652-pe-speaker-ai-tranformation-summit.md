# PE Speaker - AI Tranformation Summit

- HeyReach campaign id: 484652 (read only copy, status FINISHED, created 2026-06-25)
- Idea: PE Speaker | Persona: ? | Region: ? | Sender: ?
- Leads: 20 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x1 | not: end))`
- Results: invites sent 19, accepted 0 (0%); messages sent 0, replies 0 (0%); InMails sent 0, replies 0 (0%); tagged interested 0
- Rules today: em_dash x2, spam_phrase x2  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 52 words, rule errors: em_dash, spam_phrase

```
Hi {FIRST_NAME}, I work with Jay Radia, founder of Yieldify (acq. Publicis) & Reachdesk (100m+ rev). We're lining up a keynote speaker for our AI Transformation Summit, London 23 Sep - a room of 100+ CEOs, CFOs & PE value creation leads. Think you'd be a great fit, open to hearing more?
```

## Step 3: Message (opener, wait 1 DAY, path: accepted)

**Variant 1**, 69 words

```
Great to connect, {FIRST_NAME}. Quick one: we'd love you as a keynote speaker at our AI Transformation Summit (London, 23 Sep).

Your take on ROI-driven AI deployment would land really well with the room, which is CEOs, CFOs and PE value creation folks. Strong for lead gen and good visibility for your fund. Jay, my MD, is keen to tell you more. Ok if I connect you via email?
```

