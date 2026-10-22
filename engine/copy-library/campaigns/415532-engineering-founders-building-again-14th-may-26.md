# Engineering Founders [Building Again - 14th May 26]

- HeyReach campaign id: 415532 (read only copy, status PAUSED, created 2026-05-01)
- Idea: Engineering Founders [Building Again | Persona: Building Again - 14th May 26 | Region: ? | Sender: ?
- Leads: 363 | Structure: `CHECK(connected: MSG x1 | new: VIEW > INVITE(note x1)(accepted: MSG x1 | not: LIKE > INMAIL))`
- Results: invites sent 301, accepted 105 (35%); messages sent 37, replies 45 (40%); InMails sent 0, replies 6 (4%); tagged interested 28
- Rules today: link x6  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, progress update, close-out, wait 0 HOUR, path: already_connected)

**Variant 1**, 92 words, rule errors: link

```
Hi {FIRST_NAME} - I'm hosting an event for 100+ second-time founders at Google's London HQ on 14th May with Gus Martins from DeepMind. Discussing the question on every founder's mind: how do you build a moat when the underlying models keep evolving faster than you? 

For context, our last event featured the founders of MuleSoft ($6bn exit to Salesforce), Paddle ($2bn exit), and attendees included the founders of Wayve, Carwow, Funding Circle, ComplyAdvantage, and Bloom & Wild.

Would be great to see you there, if you can make it. {LINK}

Best, 
{MY_FIRST_NAME}
```

## Step 3: View profile (warm-up) (View profile (warm-up), wait 0 HOUR, path: not_connected)

## Step 4: Connection request (Connection note, wait 3 HOUR, path: next)
Withdraw the invite after 25 days.

**Variant 1**, 46 words, rule errors: link

```
Hi {FIRST_NAME} - I'm hosting an event for 100+ second-time founders at Google's London HQ on 14th May with Gus Martins from DeepMind. Discussing the question on every founder's mind: how do you build a moat when the underlying models keep evolving faster than you? {LINK}
```

## Step 5: Message (progress update, close-out, wait 1 DAY, path: accepted)

**Variant 1**, 71 words

```
Hi {FIRST_NAME}, good to connect. 

Dropping a quick note as the event is on track to oversubscribe, and we will be closing registrations shortly. 

For context, our last event featured the founders of MuleSoft ($6bn exit to Salesforce), Paddle ($2bn exit), and attendees included the founders of Wayve, Carwow, Funding Circle, ComplyAdvantage, and Bloom & Wild.

Would be great to see you there, if you can make it. {LINK}

Best, 
{MY_FIRST_NAME}
```

## Step 6: Like a recent post (warm-up) (Like a recent post (warm-up), wait 1 DAY, path: not_accepted)

## Step 7: InMail (InMail: opener, progress update, close-out, wait 1 DAY, path: next)

**Variant 1**, 92 words, rule errors: link
Subject: Invitation for 'Building Again' - An Event For Second Time Founders

```
Hi {FIRST_NAME} - I'm hosting an event for 100+ second-time founders at Google's London HQ on 14th May with Gus Martins from DeepMind. Discussing the question on every founder's mind: how do you build a moat when the underlying models keep evolving faster than you? 

For context, our last event featured the founders of MuleSoft ($6bn exit to Salesforce), Paddle ($2bn exit), and attendees included the founders of Wayve, Carwow, Funding Circle, ComplyAdvantage, and Bloom & Wild.

Would be great to see you there, if you can make it. {LINK}

Best, 
{MY_FIRST_NAME}
```

