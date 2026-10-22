# Building Again Sep - Exited operators

- HeyReach campaign id: 506867 (read only copy, status FINISHED, created 2026-07-14)
- Idea: Building Again Sep | Persona: ? | Region: ? | Sender: ?
- Leads: 11 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: end))`
- Results: invites sent 11, accepted 8 (73%); messages sent 13, replies 2 (25%); InMails sent 0, replies 0 (0%); tagged interested 2
- Rules today: filler x2, link x4, placeholder x3  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 47 words, rule errors: link, placeholder

```
Hi {first_name} - we're hosting an invite-only event for 100+ exited founders in September with Luke Harries, Head of Growth at ElevenLabs.
He'll walk through the experiments that took them from 0 to their $11bn valuation today - and what worked early on. Link to join: {LINK}
```

## Step 3: Message (opener, close-out, wait 7 DAY, path: accepted)

**Variant 1**, 70 words, rule errors: link, placeholder

```
Hi {first_name} - great to connect.

Wanted to see if you're planning to join us at Building Again on 9th September?

The last edition in May at Google's HQ was nearly 2x oversubscribed. This one is shaping up just as strongly, with Luke Harries, Head of Growth at ElevenLabs, speaking to a highly curated room of exited founders now building again.

Would be great to have you join us: {LINK}
```

## Step 4: Message (credibility, wait 8 DAY, path: next)

**Variant 1**, 79 words, rule errors: filler, placeholder

```
Hi {first_name}, hope you're well.

Thought I'd check if you've had a chance to sign up for Building Again?

As you know, 65% of Europe's unicorns have been built by previously exited founders on their second venture. This is that room.

Previous edition speakers and attendees have included unicorn founders from Paddle, MuleSoft and Starling Bank, and the guest list is on track to be oversubscribed again.

Resharing the link to sign up: {LINK}

Hope to see you there!
```

