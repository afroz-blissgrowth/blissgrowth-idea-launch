# Copy library

Templated sequences of the campaigns already launched in the Bliss HeyReach workspace, built read only by
`python3 -I bin/copy_library.py build` (refresh any time; numbers are as of the build date in `index.md`). Use it as a source of
STRUCTURE and angles for `/iv-copy`. It is not approved copy.

- `index.md` / `index.json`: one row per campaign (idea, persona, region, sender, status, leads, structure, accept and reply rates, rule errors).
- `campaigns/<id>-<name>.md` (+ `.json`): one file per campaign: what each step does, the templated text per variant, the wait before it,
  results, and which of today's rules the old text breaks. Templating: `{IDEA_NAME}` internal idea name, `{IDEA_PLAIN}` the
  plain-words description of the idea (the part that changes per idea), `{LINK}`.
- Search: `python3 -I bin/copy_library.py search --kind invite|message|inmail [--idea X] [--persona X] [--sender X] [--min-leads 20]`.

## Structure codes
`CHECK(connected: A | new: B)` is HeyReach's "already a connection?" branch. `INVITE(blank)` or `INVITE(note xN)` is the connection request
(N text variants); `(accepted: ... | not: ...)` are its two branches. `LIKE` / `VIEW` are warm-up actions, `MSG xN` N follow-up messages,
`INMAIL` an InMail (usually the not-accepted branch, sent by the same account). `end` means the lead leaves the sequence.

## What the data says (read with the lead counts, small campaigns are noise)
Measured on the build date over campaigns with at least 100 invites sent (HeyReach's own rates):
- Blank invite: 15 campaigns, 4,693 invites, 14.0% accepted. Invite with a note: 14 campaigns, 3,872 invites, 16.4% accepted. Not a big
  difference, so a blank invite is a safe default and a short note is a fair test variant. Both of the best long-running examples
  (BlissAISecurity, BlissManager Advisor v2) used a one-sentence note: "Given your X experience, I'd love to speak with you about being an advisor".
- Reply rate per conversation started: about 23% for blank-invite campaigns and about 40% for note campaigns, but the note campaigns
  mostly have 2 follow-ups and the warmest audiences (founders' networks). Treat as a hint only.
- Number of follow-ups: the best long-running examples had 2 short follow-ups (day 1 after accept, then 2 to 5 days later). The 4 to 8 step
  sequences are too young or too small to show that more steps help (not tested, only observed).
- InMail: HeyReach reports 0 InMails sent for every campaign (the counter is not filled), but 36 replies across 10 campaigns, so InMail
  rates cannot be computed. InMail is the not-accepted fallback, wait about 3 to 13 days after the invite.
- Warm lists (founders' own connections, event invites) are not the same audience as cold Apollo lists: compare like with like. Idea
  validation to cold leads has no history in this library yet.

## Patterns worth reusing
1. Opener: a founder asks for advice or an advisor role in one or two sentences, with one question at the end.
2. A credibility line (Yieldify, sold to Publicis; Reachdesk) when the idea page allows it.
3. Follow-up 2: an opinion question ("Do you agree?", "Does this match your area of expertise, or is it an exception?").
4. Follow-up 3: a soft ask for a call with Jay and Meelan. In the new copy this must not state a time commitment.
5. Follow-up angles rotate (problem, expertise check, opinion) and each stands alone.

## What not to copy
Most old text breaks the current rules: "quick chat" and "Open to chat?", "30 min call", "brief call", internal idea names, "we have funding"
with amounts, links in first messages (event invites), "Following up on my last message". The `Rule errors` column and each file's "Rules today"
line list them. New copy is written fresh, V1 plus 2 to 3 variants, and passes `lib/copyrules.py`.
