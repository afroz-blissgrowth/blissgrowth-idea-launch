# Founder Retarget Campaign - Meelan

- HeyReach campaign id: 543012 (read only copy, status FINISHED, created 2026-08-09)
- Idea: Founder Retarget Campaign | Persona: ? | Region: ? | Sender: Meelan
- Leads: 64 | Structure: `CHECK(connected: end | new: INVITE(blank)(accepted: MSG x3 | not: end))`
- Results: invites sent 60, accepted 12 (20%); messages sent 15, replies 4 (36%); InMails sent 0, replies 0 (0%); tagged interested 1
- Rules today: filler x2, placeholder x3, time_commitment x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 3: Message (opener, credibility, asks for a call, progress update, wait 3 HOUR, path: accepted)

**Variant 1**, 43 words, rule errors: placeholder

```
Hi {FNAME_CLEAN} - your founding experience really stood out to us. I’d love to chat about a co-founder role at my new (validated and funded) AI B2B startup. We believe it’ll surpass our previous ventures, Reachdesk ($225M val) & Yieldify (acq. by Publicis).
```

## Step 4: Message (credibility, opinion question, asks for a call, wait 3 DAY, path: next)

**Variant 1**, 90 words, rule errors: placeholder, time_commitment

```
Hi {FNAME_CLEAN}, hope you’re well.

For context, we’re co-building {IDEA_PLAIN}. We’ve built 10 companies so far that have been backed by Global Tier-1 investors like Google Ventures, Softbank, a16z, and Sequoia.

We’re looking for an exceptional operator with prior founder experience who’s looking to build again. Your profile stood out in our search, so I wanted to see if you’d be open to an intro chat?

Sharing my calendar here to find a convenient time directly: {LINK}

Speak soon,

Meelan
```

## Step 5: Message (asks for a call, close-out, wait 3 DAY, path: next)

**Variant 1**, 68 words, rule errors: filler, placeholder, time_commitment

```
Hi {FNAME_CLEAN} - hope you’re well.

Following up on my last message, in case you missed it.

We’re speaking to a select few founders to co-build our next venture with, and we’d love to learn more about what’s next for you.

Let me know if you’re interested in hearing more about the idea and Blissgrowth.

Sharing my calendar here to find a convenient time directly: {LINK}

Best,
Meelan
```

