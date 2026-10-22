# UK PE Event v2 - Akhil

- HeyReach campaign id: 551840 (read only copy, status FINISHED, created 2026-08-14)
- Idea: UK PE Event v2 | Persona: ? | Region: UK | Sender: Akhil
- Leads: 98 | Structure: `CHECK(connected: MSG x2 | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 98, accepted 20 (20%); messages sent 18, replies 4 (20%); InMails sent 0, replies 0 (0%); tagged interested 4
- Rules today: filler x8, link x2, placeholder x4, spam_promo x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, credibility, wait 3 HOUR, path: already_connected)

**Variant 1**, 80 words, rule errors: link, placeholder, spam_promo

```
Hi {FNAME}, on 28th September we're hosting a private session at Google's London HQ, bringing together Private Equity investors and CXO’s from their growth-stage portcos. 

We’ll be showcasing real use cases of where AI is delivering ROI today, and discussing where the best funds are allocating capital next. 

Attendees so far include investors and operators from businesses backed by KKR, Apax Partners, Goldman Sachs, General Atlantic, and LDC.

Would love for you to join us! Link to sign up: {LINK}
```

## Step 3: Message (message, wait 7 DAY, path: next)

**Variant 1**, 74 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you’re well.

Just checking in to see if you’re planning to join us at the AI Transformation Forum on 28th September?

The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It’s a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios. 

Please RSVP, if you can make it: {LINK} 
Hope to see you there!
```

## Step 4: Connection request (Blank invite: no note, the profile does the work, wait 3 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 5: Message (credibility, wait 1 DAY, path: accepted)

**Variant 1**, 80 words, rule errors: placeholder, spam_promo

```
Hi {FNAME}, on 28th September we're hosting a private session at Google's London HQ, bringing together Private Equity investors and CXO’s from their growth-stage portcos. 

We’ll be showcasing real use cases of where AI is delivering ROI today, and discussing where the best funds are allocating capital next. 

Attendees so far include investors and operators from businesses backed by KKR, Apax Partners, Goldman Sachs, General Atlantic, and LDC.

Would love for you to join us! Link to sign up: {LINK}
```

## Step 6: Message (message, wait 7 DAY, path: next)

**Variant 1**, 74 words, rule errors: filler, placeholder

```
Hey {FNAME}, hope you’re well.

Just checking in to see if you’re planning to join us at the AI Transformation Forum on 28th September?

The room is shaping up nicely, with leadership from some of Europe's fastest-growing scaleups and Private Equity funds attending. It’s a highly curated audience of senior operators and investors actively deploying AI across their companies and portfolios. 

Please RSVP, if you can make it: {LINK} 
Hope to see you there!
```

