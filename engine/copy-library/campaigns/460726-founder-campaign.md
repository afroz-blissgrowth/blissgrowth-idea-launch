# Founder Campaign

- HeyReach campaign id: 460726 (read only copy, status FINISHED, created 2026-06-08)
- Idea: Founder Campaign | Persona: ? | Region: ? | Sender: ?
- Leads: 299 | Structure: `CHECK(connected: end | new: INVITE(note x1)(accepted: MSG x2 | not: end))`
- Results: invites sent 224, accepted 83 (37%); messages sent 77, replies 57 (69%); InMails sent 0, replies 0 (0%); tagged interested 48
- Rules today: filler x2  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Connection request (Connection note, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1**, 48 words

```
Hi {FIRST_NAME} - your founding experience really stood out to us. Our Managing Partner, Jay Radia, would love to chat about a co-founder role at our new (validated and funded) AI B2B startup. We believe it’ll surpass our previous ventures, Reachdesk ($225M val) & Yieldify (acq. by Publicis).
```

## Step 3: Message (opener, credibility, opinion question, asks for a call, wait 1 DAY, path: accepted)

**Variant 1**, 93 words

```
Hi {FIRST_NAME} - great to connect. 

For context, we’re co-building {IDEA_PLAIN}. We’ve built 10 companies so far that have been backed by Global Tier 1 investors like Google Ventures, Softbank, a16z, and Sequoia.  

We’re looking for an exceptional operator with prior founder experience who’s looking to build again. Your profile stood out in our search, so I wanted to connect you to our Managing Partner, Jay for an intro call. 

Let me know if you’re interested, and I’ll set it up. 

Best,
Akhil
```

## Step 4: Message (close-out, wait 3 DAY, path: next)

**Variant 1**, 61 words, rule errors: filler

```
Hi {FIRST_NAME}, hope you’re well. 

Following up on my last message, in case you missed it. 

We’re speaking to a select few founders to co-build our next venture with, and we’d love to learn more about what’s next for you.

Let me know if you’re interested in hearing more about the idea and would like to speak with Jay. 

Best, 
Akhil
```

