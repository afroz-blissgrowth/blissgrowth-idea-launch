# Blissgrowth Idea Launch (router for Claude)

This repo turns an idea memo into a verified, tiered campaign list (Apollo, MillionVerifier, LinkedIn activity check, HeyReach drafts, Google Sheet per idea). It runs as Claude Code slash commands backed by Python scripts.

## Commands
- `/iv-run <idea>`: runs the whole pipeline in order, resumable. Start here.
- Single steps: `/iv-brief`, `/iv-accounts`, `/iv-signals`, `/iv-qualify`, `/iv-people`, `/iv-tier`, `/iv-enrich-verify`, `/iv-activity`, `/iv-phones`, `/iv-ready`, `/iv-copy`, `/iv-idea-page`, `/iv-launch`.
- Health check: `python3 -I engine/bin/doctor.py`
- Tests (260, offline, no credits): `python3 -I engine/tests/run_tests.py`
- Run status: `python3 -I engine/bin/run_all.py status <run>`

All scripts run from the repo root with `python3 -I`. The skills are in `.claude/skills/iv-*/SKILL.md`.

## Where things are
- `engine/lib`, `engine/bin`: the code. `engine/config.json`: defaults (prompts, thresholds, caps). `engine/config.local.json`: personal secrets and ids (gitignored).
- `engine/workflows`: n8n workflow definitions and deploy scripts. `engine/vendor/activity-checker`: builder for the LinkedIn activity checker.
- `engine/copy-library`: approved copy to template from.
- `docs/ENGINE.md`: full system doc. `docs/PLAN.md`: plan and decisions. `docs/REUSE-MAP.md`, `docs/REVIEW-*.md`, `docs/CHANGES-PROPOSAL-*.md`: background.
- `runs/`: one folder per idea (gitignored). `runs/_cache/`: shared caches. Keys live in `.env` at the repo root.

## Rules
- Never print, log or paste API keys or the bridge secret. Do not read `.env` or `engine/config.local.json` aloud.
- Never use em dashes in anything written (docs, messages, code comments, copy). Use a comma, a period or a parenthesis.
- Spell it "Blissgrowth".
- ICP, titles, countries and tiers are decided with the user, one question at a time. Claude never decides them alone.
- Get explicit user approval before creating campaigns (HeyReach drafts) and at every pilot gate. Nothing is ever started or sent live by this repo.
- Never commit `.env`, `engine/config.local.json` or anything under `runs/` (except `runs/README.md`).
