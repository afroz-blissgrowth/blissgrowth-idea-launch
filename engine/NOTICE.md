# Third-party notice

Parts of this engine are Python ports of ideas and prompts from GrowthEngine's
`coldoutboundskills` repository (https://github.com/growthenginenowoslawski/coldoutboundskills),
used under the MIT License:

- `lib/qualify.py`: judge prompt template with 4 mandatory blocks, strict-JSON scoring contract,
  streaming and resume, row deadline, one retry pass, live website check, tuning loop
  (from `list-builder/prompts/_TEMPLATE.md`, `list-expander/scripts/score-batch.ts`,
  `list-expander/scripts/verify-website.ts`, `icp-prompt-builder/SKILL.md`).
- `lib/apollo.py`: result-cap sharding idea (from `list-expander/scripts/pull.ts`).
- `lib/run.py`: run folder, state.json, stage completion from artifacts, summary.md READY line
  (from `list-builder/scripts/run-lane.ts` and `RUNBOOK.md`).
- `lib/quality.py`: the 8 list quality checks and grade bands (from `list-quality-scorecard/scripts/score-list.ts`
  and `SKILL.md`), adapted as documented in the module.
- `lib/tier.py`, `lib/verify.py`: strict-JSON batch and ingest pattern of `qualify.py`; MillionVerifier rules
  (only `ok` passes, catch-all and unknown fail) from the `list-builder` guidance.
- `.claude/skills/iv-brief`: question flow adapted from `icp-onboarding/SKILL.md`.
- `lib/copyrules.py`: the banned single words, banned phrases, promotional, phishing and irrelevant-category lists, the formatting bans
  and the silence-based closeout rule are copied from `spam-word-checker/SKILL.md`; LinkedIn adaptations are marked in the module.
- `lib/copydraft.py`, `.claude/skills/iv-copy`: the confirm-before-final-copy flow, the confirmation CTA, standalone follow-ups,
  50 to 90 word guidance and the variants idea (from `campaign-copywriting/SKILL.md` and `cold-email-starter-kit`).
- `lib/launch.py`: create-never-start rule, batches of 100 leads and attach-sequence flow (from `smartlead-campaign-upload-public`,
  adapted to HeyReach).

Ideas only (no text or code copied, written independently): ColdIQ-s-GTM-Skills has no licence, so from it we took only the ideas
"Ask Before Pitch", permission openers and one soft call to action.

MIT License

Copyright (c) 2026 GrowthEngineX

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

ColdIQ-s-GTM-Skills has no license: only ideas were used (ICP layers checklist, tier matrix
skeleton), all text here is original.
