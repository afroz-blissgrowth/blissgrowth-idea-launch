# Jay Founder Retargeting

- HeyReach campaign id: 559497 (read only copy, status PAUSED, created 2026-08-19)
- Idea: Jay Founder Retargeting | Persona: ? | Region: ? | Sender: Jay
- Leads: 57 | Structure: `CHECK(connected: MSG x2 | new: INVITE(blank)(accepted: MSG x2 | not: end))`
- Results: invites sent 35, accepted 3 (9%); messages sent 3, replies 2 (50%); InMails sent 0, replies 0 (0%); tagged interested 1
- Rules today: funding_amount x4, placeholder x4  (old copy often breaks the current rules, use the structure, not the wording)

Text is templated: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the plain-words idea description, `{LINK}` a link. The 'what it does' labels are heuristic.

## Step 1: Check if already connected (Check if already connected, wait 0 HOUR, path: start)

## Step 2: Message (opener, credibility, opinion question, asks for a call, progress update, wait 0 HOUR, path: already_connected)

**Variant 1**, 102 words, rule errors: funding_amount, placeholder

```
Hi {firstNameClean}, great to connect.

Wanted to introduce myself: I'm a 2x exited founder and now run Blissgrowth - a Venture Studio building AI B2B companies with exceptional Second-time founders.

We've built 10 companies so far, including Yieldify (acquired by Publicis), Reachdesk ($225m val @ Series B), and StackOne, backed by top investors like Google Ventures, SoftBank, and a16z.

Your founding experience really stood out to me and my team, and I'd love to chat. We have a validated idea (funded as well), and we thought you would be the perfect founder for it. Would you be interested to chat?

Best,
Jay
```

## Step 3: Message (credibility, opinion question, asks for a call, wait 5 DAY, path: next)

**Variant 1**, 56 words, rule errors: placeholder

```
Hey {firstNameClean},

My team and I speak to over 500 founders a year and have built a proprietary model based on 50+ bespoke filters to find truly exceptional builders. Your name was amongst the top few founders on that list, so I'm quite keen to speak.

Would you be open to an intro call?

Best,
Jay
```

## Step 4: Connection request (Blank invite: no note, the profile does the work, wait 0 HOUR, path: not_connected)
Withdraw the invite after 25 days.

**Variant 1 (blank invite)**, 0 words

```

```

## Step 5: Message (credibility, opinion question, asks for a call, progress update, wait 3 HOUR, path: accepted)

**Variant 1**, 102 words, rule errors: funding_amount, placeholder

```
Hi {firstNameClean}, great to connect.

Wanted to introduce myself: I'm a 2x exited founder and now run Blissgrowth - a Venture Studio building AI B2B companies with exceptional Second-time founders.

We've built 10 companies so far, including Yieldify (acquired by Publicis), Reachdesk ($225m val @ Series B), and StackOne, backed by top investors like Google Ventures, SoftBank, and a16z.

Your founding experience really stood out to me and my team, and I'd love to chat. We have a validated idea (funded as well), and we thought you would be the perfect founder for it. Would you be interested to chat?

Best,
Jay
```

## Step 6: Message (credibility, opinion question, asks for a call, wait 5 DAY, path: next)

**Variant 1**, 56 words, rule errors: placeholder

```
Hey {firstNameClean},

My team and I speak to over 500 founders a year and have built a proprietary model based on 50+ bespoke filters to find truly exceptional builders. Your name was amongst the top few founders on that list, so I'm quite keen to speak.

Would you be open to an intro call?

Best,
Jay
```

