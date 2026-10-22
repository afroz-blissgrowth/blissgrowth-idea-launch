# AITF - Akhil PE-verified (265)

- HeyReach campaign id: 604349 (read only copy, status PAUSED, created 2026-09-16)
- Idea: AITF | Persona: ? | Region: ? | Sender: Akhil
- Leads: 265 | Structure: `CHECK(connected: MSG x2 | new: INVITE(note x1)(accepted: MSG x1 | not: end))`
- Results: invites sent 263, accepted 17 (6%); messages sent 5, replies 6 (35%); InMails sent 0, replies 0 (0%); tagged interested 5
- Rules today: filler x12, link x4, placeholder x4, spam_promo x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, wait 3 HOUR, path: already_connected)

**Variant 1**, 50 words, rule errors: link, placeholder, spam_promo

```
Hi {FNAME} - on 28th September, we're hosting 50 Growth-stage CXOs & PE Partners at Google's London HQ.

We'll be sharing real use cases of where AI is delivering strong ROI today & where the best investors are allocating capital next.

We'd love to host you as our guest: {LINK}
```

## Step 3: Message (message, wait 3 DAY, path: next)

**Variant 1**, 95 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you're well.

Just checking in to see if you're planning to join us at the AI Transformation Forum at Google's HQ in London on 28th September?

The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It's a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios.

We'd love for you to join us! There are a few spots left, RSVP through the event page if you can make it: {LINK}

Hope to see you there!
```

## Step 4: Connection request (Connection note, wait 3 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 50 words, rule errors: link, placeholder, spam_promo

```
Hi {FNAME} - on 28 Sept we're hosting 50 Growth-stage CXOs & PE Partners at Google's London HQ.

We'll be sharing real use cases of where AI is delivering strong ROI today & where the best investors are allocating capital next.

We'd love to host you as our guest: {LINK}
```

## Step 5: Message (message, wait 3 DAY, path: accepted)

**Variant 1**, 95 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you're well.

Just checking in to see if you're planning to join us at the AI Transformation Forum at Google's HQ in London on 28th September?

The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It's a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios.

We'd love for you to join us! There are a few spots left, RSVP through the event page if you can make it: {LINK}

Hope to see you there!
```

