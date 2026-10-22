# UK PE Event v2 - Vinamr

- HeyReach campaign id: 518510 (read only copy, status PAUSED, created 2026-07-22)
- Idea: UK PE Event v2 | Persona: ? | Region: UK | Sender: Vinamr
- Leads: 505 | Structure: `CHECK(connected: MSG x2 | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 368, accepted 30 (8%); messages sent 13, replies 6 (25%); InMails sent 0, replies 0 (0%); tagged interested 3
- Rules today: filler x8, link x2, placeholder x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, wait 3 HOUR, path: already_connected)

**Variant 1**, 47 words, rule errors: link, placeholder

```
Hi {FNAME}, in September we’re bringing together 100+ C-suite leaders from European scale-ups and Senior PE partners to discuss where AI is delivering strong ROI and where they are focusing next.
We’d love to offer a free pass (normally £300) and host you as our guest: {LINK}
```

## Step 3: Message (message, wait 7 DAY, path: next)

**Variant 1**, 95 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you’re well.
Just checking in to see if you’re planning to join us at the AI Transformation Forum at Google’s HQ in London on 28th September?
The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It’s a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios. 
We’d love for you to join us! Please RSVP through the event page: {LINK} and select the “Blissgrowth Invited Guest” for your complimentary pass. 
Hope to see you there!
```

## Step 4: Connection request (Blank invite: no note, the profile does the work, wait 3 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 5: Message (message, wait 1 DAY, path: accepted)

**Variant 1**, 47 words, rule errors: placeholder

```
Hi {FNAME}, in September we’re bringing together 100+ C-suite leaders from European scale-ups and Senior PE partners to discuss where AI is delivering strong ROI and where they are focusing next.
We’d love to offer a free pass (normally £300) and host you as our guest: {LINK}
```

## Step 6: Message (message, wait 7 DAY, path: next)

**Variant 1**, 95 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you’re well.
Just checking in to see if you’re planning to join us at the AI Transformation Forum at Google’s HQ in London on 28th September?
The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It’s a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios. 
We’d love for you to join us! Please RSVP through the event page: {LINK} and select the “Blissgrowth Invited Guest” for your complimentary pass. 
Hope to see you there!
```

