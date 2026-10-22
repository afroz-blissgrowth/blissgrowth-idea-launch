# BlissSLM (v2) Advisory (USA) enterprise CFOs USA Akhil [Punith]

- HeyReach campaign id: 650447 (read only copy, status PAUSED, created 2026-10-12)
- Idea: BlissSLM | Persona: ? | Region: USA | Sender: Akhil
- Leads: 36 | Structure: `CHECK(connected: VIEW > MSG x4 | new: INVITE(blank)(accepted: LIKE > MSG x4 | not: INMAIL))`
- Results: invites sent 36, accepted 0 (0%); messages sent 0, replies 0 (0%); InMails sent 0, replies 0 (0%); tagged interested 0
- Rules today: filler x6, time_commitment x10  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: View profile (warm-up) (View profile (warm-up), wait 0 HOUR, path: already_connected)

## Step 3: Message (opener, advisor ask, credibility, asks for a call, wait 3 HOUR, path: next)

**Variant 1**, 51 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME}, we are building {IDEA_PLAIN}. I’d love for you to potentially be an advisor.

I believe it'll be bigger than our other startups - Yieldify (Google backed and sold to Publicis) & Reachdesk (valued at $225M).

Given your background, would you be open to a quick chat?
```

## Step 4: Message (opinion question, wait 2 DAY, path: next)

**Variant 1**, 48 words

```
I know everyone is under more pressure than ever on AI costs, with AI agents now running around the clock.

I believe choosing AI models should be more than guesswork: proven on your own work, always up to date, and cheaper without losing quality.

Do you agree? {FIRST_NAME}
```

## Step 5: Message (advisor ask, asks for a call, wait 2 DAY, path: next)

**Variant 1**, 77 words, rule errors: time_commitment

```
{FIRST_NAME}, if you've been following Stripe's move to buy OpenRouter, you'll have seen how tokens are becoming the currency of the AI era. Managing them takes a combination of financial rigour and proof of what each model can really do.

We're putting together a small group of AI and finance leaders to advise us as we build. I'd love to bring you on as a potential advisor.

Could we do a brief call this week or next? 
```

## Step 6: Message (opinion question, social proof, wait 2 DAY, path: next)

**Variant 1**, 33 words

```
Hi {FIRST_NAME}, we've been getting strong early feedback from finance and AI leaders.

Given your background, I'd value your read.

Does this company match your area of expertise, or is it an exception?
```

## Step 7: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 14 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 8: Like a recent post (warm-up) (Like a recent post (warm-up), wait 3 HOUR, path: accepted)

## Step 9: Message (advisor ask, credibility, asks for a call, wait 3 HOUR, path: next)

**Variant 1**, 57 words, rule errors: filler, time_commitment

```
Hi {FIRST_NAME}, we are building {IDEA_PLAIN}. I’d love for you to potentially be an advisor.

I believe it'll be bigger than our other startups - Yieldify (Google backed and sold to Publicis) & Reachdesk (valued at $225M).

Given your background, would you be open to a quick chat?
```

## Step 10: Message (opinion question, wait 2 DAY, path: next)

**Variant 1**, 48 words

```
I know everyone is under more pressure than ever on AI costs, with AI agents now running around the clock.

I believe choosing AI models should be more than guesswork: proven on your own work, always up to date, and cheaper without losing quality.

Do you agree, {FIRST_NAME}?
```

## Step 11: Message (advisor ask, asks for a call, wait 2 DAY, path: next)

**Variant 1**, 77 words, rule errors: time_commitment

```
{FIRST_NAME}, if you've been following Stripe's move to buy OpenRouter, you'll have seen how tokens are becoming the currency of the AI era. Managing them takes a combination of financial rigour and proof of what each model can really do.

We're putting together a small group of AI and finance leaders to advise us as we build. I'd love to bring you on as a potential advisor.

Could we do a brief call this week or next? 
```

## Step 12: Message (opinion question, social proof, wait 2 DAY, path: next)

**Variant 1**, 33 words

```
Hi {FIRST_NAME}, we've been getting strong early feedback from finance and AI leaders.

Given your background, I'd value your read.

Does this company match your area of expertise, or is it an exception?
```

## Step 13: InMail (InMail: opener, advisor ask, credibility, asks for a call, wait 7 DAY, path: not_accepted)

**Variant 1**, 58 words, rule errors: filler, time_commitment
Subject: Yieldify / Reachdesk founder’s new AI infrastructure project

```
Hi {FIRST_NAME}, I'm building {IDEA_PLAIN}. I’d love for you to potentially be an advisor.

I believe it'll be bigger than our other startups - Yieldify (Google backed and sold to Publicis) & Reachdesk (valued at $225M).

Given your background, would you be open to a quick chat?

Thanks, {MY_FIRST_NAME}
```

