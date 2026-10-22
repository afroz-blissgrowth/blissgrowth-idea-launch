# Project skills

Idea Launch (`iv-*`), in run order: `/iv-brief` (includes the company signals interview), `/iv-accounts` (pilot first: 10 to 20 accounts
reviewed by hand, then the full pull), `/iv-signals` (Apollo headcounts), `/iv-qualify`, `/iv-people`, `/iv-tier` (ends with the
people pilot gate), `/iv-enrich-verify`, `/iv-activity`, `/iv-phones`, `/iv-ready`, `/iv-copy`, `/iv-idea-page`, `/iv-launch`.
`/iv-run <idea>` runs all of them in order, resumable, and stops only where you must decide (brief, the two pilot reviews, tuning reviews,
copy approval, idea page text, launch approval).
Order, data locations and how to improve prompts and config: `docs/ENGINE.md`. Each skill is a SKILL.md that tells
Claude which `bin/` script to run and what to ask you.
