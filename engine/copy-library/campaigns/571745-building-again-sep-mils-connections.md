# Building Again Sep - Mils connections

- HeyReach campaign id: 571745 (read only copy, status FINISHED, created 2026-08-27)
- Idea: Building Again Sep | Persona: ? | Region: ? | Sender: ?
- Leads: 9 | Structure: `CHECK(connected: MSG x2 | new: end)`
- Results: invites sent 0, accepted 0 (0%); messages sent 8, replies 1 (12%); InMails sent 0, replies 0 (0%); tagged interested 0
- Rules today: filler x6, funding_amount x2, link x2, pay_number x2  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, wait 0 HOUR, path: already_connected)

**Variant 1**, 124 words, rule errors: funding_amount, link, pay_number

```
Hi {FIRST_NAME}, hope you've been well.

I wanted to personally invite you to a private event I'm hosting on 10th September at Stripe's London HQ, an invite-only evening for 100+ of the UK's best second-time/exited founders who are Building Again.

We've got 2 incredible speakers lined up:

Luke Harries, Head of Growth at ElevenLabs, on what it takes to build one of the world's fastest-growing AI companies, and the early bets that paid off on their journey from $0 to $11bn.

Dan Lifshits, Co-Founder of Dwelly (just raised $170m from EQT and General Catalyst), on building {IDEA_PLAIN}.

Would love for you to join us. You can register here: {LINK}

Kind Regards,
Meelan
```

## Step 3: Message (opinion question, close-out, wait 7 DAY, path: next)

**Variant 1**, 61 words, rule errors: filler

```
Hey {FIRST_NAME}, following up in case you missed my last message.

Just checking in to see if you're planning to join us at our Building Again event on 10th September?

The room is shaping up nicely, with a truly exceptional lineup of second-time/exited founders attending.

We've got a few spots left, please RSVP through the event page: {LINK}

Kind Regards,
Meelan
```

