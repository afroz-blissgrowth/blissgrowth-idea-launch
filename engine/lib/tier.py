"""Stage 5 logic: T1 / T2 tiering of the people found by search, done by Claude (Sonnet subagents), then caps.

Same strict-ingest pattern as qualify.py (ported from GrowthEngine score-batch.ts, MIT): this module writes
batch files, a Claude subagent reads the judge prompt plus a batch and writes a strict JSON result file,
ingest_file() validates it row by row, results are append-only (last record per person wins), a prompt is
tuned on samples of 10 with explicit user review (stop after 2 clean rounds, never auto-approved) and the lock
is tied to the exact prompt text. The tier rules come from the brief (`tier_rules`), agreed with the user in
/iv-brief. No model API key exists in the project, so no API call is made here.

Output per person: tier T1 | T2 | X and a one-sentence reason (tier_reason). X means "not a buyer for this idea":
no credits are spent on X people, the row stays. Caps are enforced by people.apply_caps (after tiering, best
title priority first inside a tier).

Files (run folder, tier/): spec.json, prompt.md, prompt.locked.json, tuning.json, samples.json, batches/,
results.jsonl, ingested.json, skipped.json (user chose to skip tiering).
The CONFIG for batch size etc. is config.json -> tier.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path

import brief as briefmod
import config
import people as peoplemod
import schema
from qualify import parse_result_text
from util import append_jsonl, atomic_write, now_iso, read_csv, read_json, read_jsonl, write_json

TEMPLATE = """IDEA: {idea}

You decide, for each PERSON, which tier they are for this idea. The tier rules were agreed with the user.

T1 ({t1_channels}):
{t1}

T2 ({t2_channels}):
{t2}

X (not a buyer for this idea, no outreach, no credits spent):
{x}

## MANDATORY BLOCK 1 - evidence
You see only: the job title Apollo has, the company name and country, whether the title matched a T1 or T2 title
in the brief (title_hint), and the company's fit verdict. Seniority, full name and LinkedIn are not known yet.
Judge ONLY on this. Do not use outside knowledge about the person or the company.

## MANDATORY BLOCK 2 - lean
A title that fits a tier but is slightly off (for example a regional or deputy title) is T2, not X. Use X only
when the title clearly has no budget, ownership or influence over the idea's problem (intern, assistant,
coordinator, student, unrelated function). Several T1 titles at one company are all T1 (caps are applied later).

## MANDATORY BLOCK 3 - company context
Company fit confidence is given. At a company with a weak fit (low confidence or flag review), a person whose
title would normally be T1 may still be T1 if the rules above say so; follow the tier rules text, not a guess.

## Output (strict JSON, nothing else)
Return one JSON array with exactly one object per person, in any order:
[{{"id": "<id from the input>", "tier": "T1"|"T2"|"X", "reason": "<one sentence, max 200 chars>"}}]
No markdown fences, no commentary, no extra keys.
"""
MARKERS = ["MANDATORY BLOCK 1", "MANDATORY BLOCK 2", "MANDATORY BLOCK 3"]

DEFAULT_X = ["Interns, assistants, coordinators, students, trainees, retired.",
             "Functions with no budget, ownership or influence over the problem (unrelated departments)."]


def build_prompt(spec):
    for k in ("idea", "t1", "t2"):
        if not spec.get(k):
            raise ValueError("spec.%s is required" % k)
    bullets = lambda v: "\n".join("- " + x for x in (v if isinstance(v, list) else [v]))
    text = TEMPLATE.format(idea=spec["idea"], t1=bullets(spec["t1"]), t2=bullets(spec["t2"]),
                           x=bullets(spec.get("x") or DEFAULT_X),
                           t1_channels=spec.get("t1_channels", "LinkedIn + email + call"),
                           t2_channels=spec.get("t2_channels", "LinkedIn + email"))
    if spec.get("extra_rules"):
        text += "\n## Extra rules (from tuning)\n" + bullets(spec["extra_rules"]) + "\n"
    check_prompt(text)
    return text


def check_prompt(text):
    missing = [m for m in MARKERS if m not in text]
    if missing:
        raise ValueError("tier prompt is missing mandatory blocks: %s" % ", ".join(missing))
    return True


def spec_from_brief(brief):
    """Starting spec from brief.tier_rules (the user's own words). Claude and the user refine it before use."""
    tr = brief.get("tier_rules") or {}
    idea = brief.get("idea") or {}
    return {"idea": idea.get("one_liner") or idea.get("name", ""), "t1": tr.get("T1", ""), "t2": tr.get("T2", ""),
            "x": tr.get("X") or DEFAULT_X, "extra_rules": []}


def validate_item(item, valid_ids):
    """(clean or None, problem or None)."""
    if not isinstance(item, dict):
        return None, "not an object"
    pid = str(item.get("id", ""))
    if pid not in valid_ids:
        return None, "unknown id %r" % pid
    t = str(item.get("tier", "")).strip().upper()
    if t not in schema.TIERS:
        return {"id": pid}, "tier must be T1, T2 or X"
    reason = str(item.get("reason", "")).strip()
    if not reason:
        return {"id": pid}, "reason is empty"
    return {"id": pid, "tier": t, "reason": reason[:200]}, None


class Tier:
    def __init__(self, run):
        self.run = run
        self.f = peoplemod.Files(run)
        self.dir = self.f.tier
        (self.dir / "batches").mkdir(exist_ok=True)
        self.cfg = config.get("tier")
        self.spec_path = self.dir / "spec.json"
        self.prompt_path = self.dir / "prompt.md"
        self.lock_path = self.dir / "prompt.locked.json"
        self.tuning_path = self.dir / "tuning.json"
        self.sample_log = self.dir / "samples.json"
        self.results_path = self.f.tier_results

    # -- spec, lock, tuning
    def set_spec(self, spec):
        text = build_prompt(spec)
        write_json(self.spec_path, spec)
        atomic_write(self.prompt_path, text)
        return text

    def _sha(self):
        return hashlib.sha1(self.prompt_path.read_bytes()).hexdigest()[:10]

    def is_locked(self):
        lk = read_json(self.lock_path, None)
        return bool(lk and self.prompt_path.exists() and lk.get("prompt_sha") == self._sha())

    def lock(self, rounds, note="", simulated=False):
        write_json(self.lock_path, {"locked_at": now_iso(), "rounds": rounds, "note": note, "simulated": simulated,
                                    "prompt_sha": self._sha()})
        atomic_write(self.dir / ("prompt.locked-%s.md" % now_iso()[:10]), self.prompt_path.read_text(encoding="utf-8"))

    def tuning(self):
        return read_json(self.tuning_path, {"rounds": []})

    def log_round(self, round_no, corrections, note="", simulated=False):
        t = self.tuning()
        t["rounds"] = [r for r in t["rounds"] if r["round"] != round_no] + [
            {"round": round_no, "corrections": corrections, "note": note, "simulated": simulated, "at": now_iso()}]
        t["rounds"].sort(key=lambda r: r["round"])
        write_json(self.tuning_path, t)
        return self.clean_streak(t)

    def clean_streak(self, t=None):
        streak = 0
        for r in reversed((t or self.tuning())["rounds"]):
            if r["corrections"] == 0:
                streak += 1
            else:
                break
        return streak

    # -- people to tier
    def table(self):
        rows = peoplemod.load_table(self.run)
        if not rows:
            raise RuntimeError("people.csv is missing or empty. Run people_search.py first.")
        return rows

    def results(self):
        out = {}
        for r in read_jsonl(self.results_path):
            out[r.get("person_id")] = r
        return out

    def _company_ctx(self):
        ctx = {}
        for r in read_csv(self.run.qdir / "qualified.csv"):
            ctx[r["org_id"]] = r
        return ctx

    def _item(self, row, ctx):
        c = ctx.get(row["org_id"], {})
        return {"id": row["person_id"], "title": row["title"], "company": row["company"], "domain": row["domain"],
                "country": c.get("country") or row.get("country", ""), "title_hint": row.get("title_hint") or "none",
                "company_flag": c.get("flag", ""), "company_confidence": c.get("confidence", ""),
                "company_reason": c.get("reason", "")}

    def candidates(self, rows=None):
        """People still waiting for a tier: cap_status candidate (inside the tiering pool, no result yet)."""
        rows = rows or self.table()
        return [r for r in rows if r["cap_status"] == schema.CAP_CANDIDATE]

    def _write_batch(self, name, items, kind):
        path = self.dir / "batches" / (name + ".json")
        write_json(path, {"batch": name, "kind": kind, "issued_at": now_iso(), "prompt_file": str(self.prompt_path),
                          "result_file": str(self.dir / "batches" / (name + ".result.json")),
                          "output_format": 'JSON array: [{"id","tier","reason"}], one object per person', "rows": items})
        return path

    def sample_batch(self, round_no, n=None):
        """10 people (default) spread over different companies, never reused across rounds."""
        n = n or self.cfg["sample_size"]
        rows = self.table()
        log = read_json(self.sample_log, {"rounds": {}})
        used = {i for ids in log["rounds"].values() for i in ids}
        rng = random.Random("%s-tier-%d" % (self.run.dir.name, round_no))
        cand = [r for r in rows if r["person_id"] not in used and r["cap_status"] in (schema.CAP_CANDIDATE, schema.CAP_SELECTED, schema.CAP_NOT_TIERED, schema.CAP_OVER)]
        rng.shuffle(cand)
        chosen, orgs = [], set()
        for r in cand:  # first pass: one person per company, so the sample shows variety
            if r["org_id"] not in orgs:
                orgs.add(r["org_id"])
                chosen.append(r)
            if len(chosen) >= n:
                break
        for r in cand:
            if len(chosen) >= n:
                break
            if r not in chosen:
                chosen.append(r)
        if not chosen:
            raise RuntimeError("no unsampled people left")
        log["rounds"][str(round_no)] = [r["person_id"] for r in chosen]
        write_json(self.sample_log, log)
        ctx = self._company_ctx()
        return self._write_batch("sample-r%d" % round_no, [self._item(r, ctx) for r in chosen], "sample")

    def make_batches(self, size=None, reissue=False):
        """Batches of people still waiting for a tier, grouped by company (a company is not split unless it is
        larger than the batch size). Skips people already inside a fresh unanswered batch."""
        size = size or self.cfg["batch_size"]
        pend = self.candidates()
        issued = set()
        stale = self.cfg["batch_stale_minutes"] * 60
        for p in sorted((self.dir / "batches").glob("batch-*.json")):
            if p.name.endswith(".result.json"):
                continue
            if (self.dir / "batches" / (p.stem + ".result.json")).exists() and not reissue:
                continue
            if reissue or time.time() - p.stat().st_mtime > stale:
                continue
            issued |= {i["id"] for i in read_json(p)["rows"]}
        todo = [r for r in pend if r["person_id"] not in issued]
        todo.sort(key=lambda r: (r["org_id"], peoplemod.rank_of(r["title_rank"]), r["person_id"]))
        ctx = self._company_ctx()
        existing = [int(re.search(r"(\d+)", p.stem).group(1)) for p in (self.dir / "batches").glob("batch-*.json")
                    if not p.name.endswith(".result.json")]
        n0 = max(existing or [0])
        paths, cur = [], []
        by_org = {}
        for r in todo:
            by_org.setdefault(r["org_id"], []).append(r)
        for members in by_org.values():
            if cur and len(cur) + len(members) > size:
                n0 += 1
                paths.append(self._write_batch("batch-%04d" % n0, [self._item(x, ctx) for x in cur], "tier"))
                cur = []
            cur += members
            while len(cur) >= size:
                n0 += 1
                paths.append(self._write_batch("batch-%04d" % n0, [self._item(x, ctx) for x in cur[:size]], "tier"))
                cur = cur[size:]
        if cur:
            n0 += 1
            paths.append(self._write_batch("batch-%04d" % n0, [self._item(x, ctx) for x in cur], "tier"))
        return {"pending": len(pend), "batches": [str(p) for p in paths], "skipped_in_flight": len(pend) - len(todo)}

    def ingest_file(self, path):
        path = Path(path)
        batch_path = path.with_name(path.name.replace(".result.json", ".json"))
        batch = read_json(batch_path)
        if batch is None:
            raise RuntimeError("no batch file for %s" % path.name)
        items = {i["id"]: i for i in batch["rows"]}
        rows = {r["person_id"]: r for r in self.table()}
        rep = {"batch": batch["batch"], "ok": 0, "invalid": 0, "missing": 0, "problems": []}
        try:
            data = parse_result_text(path.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError) as e:
            rep["problems"].append(str(e))
            rep["missing"] = len(items)
            return rep
        seen = set()
        for it in data:
            clean, problem = validate_item(it, set(items))
            if clean is None:
                rep["invalid"] += 1
                rep["problems"].append(problem)
                continue
            seen.add(clean["id"])
            if batch["kind"] == "sample":
                continue
            if problem:
                rep["invalid"] += 1
                rep["problems"].append("%s: %s" % (clean["id"], problem))
                seen.discard(clean["id"])  # stays untiered, picked up by the retry pass
                continue
            row = rows.get(clean["id"])
            append_jsonl(self.results_path, {"person_id": clean["id"], "org_id": row["org_id"] if row else "",
                                             "tier": clean["tier"], "reason": clean["reason"], "batch": batch["batch"],
                                             "tiered_at": now_iso()})
            rep["ok"] += 1
        if batch["kind"] == "sample":
            rep["ok"] = len(seen)
        rep["missing"] = len(set(items) - seen)
        return rep

    def sample_report(self, round_no):
        batch = read_json(self.dir / "batches" / ("sample-r%d.json" % round_no))
        res_path = self.dir / "batches" / ("sample-r%d.result.json" % round_no)
        got = {}
        if res_path.exists():
            for it in parse_result_text(res_path.read_text(encoding="utf-8")):
                got[str(it.get("id"))] = it
        out = []
        for row in batch["rows"]:
            g = got.get(row["id"], {})
            out.append({"company": row["company"], "title": row["title"], "hint": row["title_hint"],
                        "tier": g.get("tier", "?"), "reason": g.get("reason", "(no result)")})
        return out

    def status(self):
        rows = self.table()
        res = self.results()
        batches = {"open": [], "answered": 0}
        for p in sorted((self.dir / "batches").glob("batch-*.json")):
            if p.name.endswith(".result.json"):
                continue
            if (self.dir / "batches" / (p.stem + ".result.json")).exists():
                batches["answered"] += 1
            else:
                age = (time.time() - p.stat().st_mtime) / 60
                batches["open"].append({"batch": p.stem, "age_min": round(age), "stale": age > self.cfg["batch_stale_minutes"]})
        tiers = {}
        for r in res.values():
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        return {"people": len(rows), "tiered": len(res), "waiting": len(self.candidates(rows)), "tiers": tiers,
                "locked": self.is_locked(), "clean_streak": self.clean_streak(), "batches": batches,
                "tuning_simulated": any(r.get("simulated") for r in self.tuning()["rounds"]),
                "skipped": self.f.tier_skipped.exists()}

    def finalize(self, push=True):
        """Rebuild people.csv (caps enforced) and push. Returns counts incl. cap effects per tier."""
        brief = self.run.brief()
        rows, rep = peoplemod.sync(self.run, brief, push=push and bool(self.run.sheet_id()))
        c = peoplemod.counts(rows)
        caps = briefmod.people_caps(brief)
        sel = {"T1": 0, "T2": 0}
        for r in rows:
            if r["cap_status"] == schema.CAP_SELECTED and r["tier"] in sel:
                sel[r["tier"]] += 1
        return {"caps": caps, "selected_by_tier": sel, "cap_status": c["by_cap"], "tiers": c["by_tier"], "sheet": rep}
