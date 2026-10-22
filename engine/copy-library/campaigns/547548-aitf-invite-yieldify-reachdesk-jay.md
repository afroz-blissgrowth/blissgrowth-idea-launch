# AITF Invite - Yieldify/Reachdesk (Jay)

- HeyReach campaign id: 547548 (read only copy, status FINISHED, created 2026-08-12)
- Idea: AITF Invite | Persona: ? | Region: ? | Sender: Jay
- Leads: 32 | Structure: `CHECK(connected: MSG x1 | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 2, accepted 0 (0%); messages sent 0, replies 8 (29%); InMails sent 0, replies 0 (0%); tagged interested 6
- Rules today: filler x6, link x2, placeholder x3  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, credibility, wait 0 HOUR, path: already_connected)

**Variant 1**, 112 words, rule errors: filler, link, placeholder

```
Hi {firstNameClean}, hope you're well.

How are things? I know it's been a little while.

Wanted to invite you to a private event that I'm hosting at Google's London HQ on 28 September.

We're bringing together a group of senior operators from high-growth companies and PE funds to share what they're seeing with AI right now, what's actually working, and where they think things are heading next.

Attendees so far include investors and operators from businesses backed by KKR, Apax Partners, Goldman Sachs, General Atlantic and LDC.

There'll be lots of food, drinks, and plenty of time to network.

It would be great to see you there! You can RSVP here: {LINK}
```

## Step 3: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 4: Message (credibility, wait 3 HOUR, path: accepted)

**Variant 1**, 112 words, rule errors: filler, placeholder

```
Hi {firstNameClean}, hope you're well.

How are things? I know it's been a little while.

Wanted to invite you to a private event that I'm hosting at Google's London HQ on 28 September.

We're bringing together a group of senior operators from high-growth companies and PE funds to share what they're seeing with AI right now, what's actually working, and where they think things are heading next.

Attendees so far include investors and operators from businesses backed by KKR, Apax Partners, Goldman Sachs, General Atlantic and LDC.

There'll be lots of food, drinks, and plenty of time to network.

It would be great to see you there! You can RSVP here: {LINK}
```

## Step 5: Message (message, wait 5 DAY, path: next)

**Variant 1**, 54 words, rule errors: filler, placeholder

```
Hey {firstNameClean}, hope you're well.

Just checking if you're able to join the event on 28th September (at Google's HQ)?

The room is shaping up nicely, with leadership teams from some of the UK's fastest-growing companies and Private Equity funds attending.

Would love to see you there! Please RSVP through the event page: {LINK}
```

