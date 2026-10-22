"""Stage 3 logic: AI fit check per company (qualified, confidence, reason) + live website check.

Ported from GrowthEngine coldoutboundskills (MIT, copyright 2026 GrowthEngineX):
  * list-builder/prompts/_TEMPLATE.md   the judge prompt with 4 MANDATORY blocks
  * list-expander/scripts/score-batch.ts   strict JSON {qualified, confidence, reason}, streaming
    results, resume, row deadline, one retry pass
  * list-expander/scripts/verify-website.ts   live homepage fetch, dead and parked detection
  * icp-prompt-builder/SKILL.md   tuning loop on batches of 10, stop after 2 clean rounds
The judgement itself is done by Claude: this module prepares batch files of evidence, a Claude
subagent scores each batch and writes a result file, and ingest() validates it strictly. There is
no model API key in <repo>/.env, so no API call is made here. A direct API scorer could be
added later; it only has to produce the same result files.

Files (run folder, qualify/):
  spec.json            ICP one-liner, qualifies, disqualifies, leans, countries (input to the prompt)
  prompt.md            the assembled judge prompt (with the 4 mandatory blocks)
  prompt.locked.json   written when tuning converged (2 clean rounds)
  tuning.json          per round: corrections count
  evidence.jsonl       live homepage fetch per domain (cache, last wins)
  batches/             batch-0001.json (input) and batch-0001.result.json (written by the subagent)
  results.jsonl        validated results, append-only, last record per org_id wins
  qualified.csv        accounts plus qualification columns (rebuilt by finalize)
"""
from __future__ import annotations

import html
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

import config
import net
import schema
from util import (append_jsonl, atomic_write, now_iso, read_csv, read_json, read_jsonl, write_csv, write_json)

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")

# ---- prompt ------------------------------------------------------------------------------------
MANDATORY_MARKERS = ["MANDATORY BLOCK 1", "MANDATORY BLOCK 2", "MANDATORY BLOCK 3", "MANDATORY BLOCK 4"]

TEMPLATE = """ICP: {icp_one_liner}

QUALIFIES ({lean_direction}):
{qualifies}

DOES NOT QUALIFY:
{disqualifies}

## MANDATORY BLOCK 1 - size evidence
Absence of revenue / size / headcount information is NOT a reason to reject. Most private
companies do not publish it. Only disqualify on size when evidence CLEARLY shows a
mega-firm far outside the stated range.

## MANDATORY BLOCK 2 - screening separation
Geography and employee-headcount screening are handled separately by database filters.
Do NOT reject for unstated location or unstated size; only reject when evidence clearly
shows the company is based outside the target countries ({countries}).

## MANDATORY BLOCK 3 - sparse websites
Minimal or splash-page websites are common for private firms. A sparse site is NOT
disqualifying when the name, branding and evidence are consistent with the ICP. Reject only
on positive evidence of a DIFFERENT business.

## MANDATORY BLOCK 4 - identity language
Qualify on how the company DESCRIBES ITSELF (its identity language), not on whether it
proves operational details. When evidence is thin but the identity language fits, lean
{thin_evidence_lean} with lower confidence rather than rejecting outright.
"""

SIGNALS_BLOCK = """
## Company signals (set by the user for this idea)
Each company comes with a "signals" object: Apollo headcounts and the user's thresholds, each rule marked HARD or SOFT, with
this company's result (pass, fail, unknown or judge). Headcounts are estimates, not exact.
- HARD rules are enforced by the system before you see a company (a company that fails one is dropped automatically). Do not
  re-judge them.
- SOFT rules: weigh them. A failed soft rule lowers confidence, and disqualifies only together with other evidence. A passed
  one raises confidence.
- unknown means Apollo has no data. It is NEVER a reason to reject (same logic as MANDATORY BLOCK 1).
- judge rules (tools used, uses consultancies, anything without a number): look for them in the homepage text, the meta
  description and the `technologies` list, and say what you found. No evidence either way is not a failure.
- When a signal decides the answer, name it in the reason (for example "mostly sales staff, no engineers, fits").
The signals for this idea:
{signal_lines}
"""

CONTRACT = """
## Evidence you are given
For each company: name, domain, a few Apollo facts (country, city, revenue band, founded year,
NAICS/SIC codes), the live homepage title, meta description and visible text. Judge ONLY on this
evidence. Do not use outside knowledge to invent facts about the company.

## Output (strict JSON, nothing else)
Return one JSON array with exactly one object per company, in any order:
[{"id": "<id from the input>", "qualified": true|false, "confidence": 0.0-1.0, "reason": "<one sentence, max 200 chars>"}]
confidence is how sure you are of the qualified value. Use 0.5 to 0.7 for borderline cases.
No markdown fences, no commentary, no extra keys.
"""


def build_prompt(spec):
    """Assemble prompt.md text from spec.json content. Raises ValueError on a bad spec."""
    for k in ("icp_one_liner", "qualifies", "disqualifies"):
        if not spec.get(k):
            raise ValueError("spec.%s is required" % k)
    bullets = lambda xs: "\n".join("- " + x for x in xs)
    text = TEMPLATE.format(
        icp_one_liner=spec["icp_one_liner"],
        lean_direction=spec.get("lean_direction", "lean inclusive: when in doubt keep it with lower confidence"),
        qualifies=bullets(spec["qualifies"]),
        disqualifies=bullets(spec["disqualifies"]),
        countries=", ".join(spec.get("countries") or ["the target countries"]),
        thin_evidence_lean=spec.get("thin_evidence_lean", "toward qualifying"))
    if spec.get("extra_rules"):
        text += "\n## Extra rules (from tuning)\n" + bullets(spec["extra_rules"]) + "\n"
    if spec.get("signals"):
        import signals as signalsmod
        lines = []
        for sg in signalsmod.canonical(spec["signals"]):
            what = ("%s %s" % (sg["source_field"], signalsmod.rule_text(sg))) if sg["kind"] == "numeric" else sg.get("description", "")
            lines.append("- %s (%s): %s" % (sg["name"], sg["strength"].upper(), what))
        text += SIGNALS_BLOCK.replace("{signal_lines}", "\n".join(lines))
    text += CONTRACT
    check_prompt(text)
    return text


def check_prompt(text):
    """Every judge prompt MUST contain all four mandatory blocks. Returns True or raises."""
    missing = [m for m in MANDATORY_MARKERS if m not in text]
    if missing:
        raise ValueError("prompt is missing mandatory blocks: %s" % ", ".join(missing))
    return True


# ---- live website check ------------------------------------------------------------------------
PARKED_PATTERNS = [
    "account suspended", "this account has been suspended", "domain is parked", "parked domain",
    "buy this domain", "domain for sale", "this domain may be for sale", "purchase this domain",
    "coming soon", "under construction", "website expired", "sedoparking", "hugedomains",
    "godaddy.com/domainsearch", "future home of something", "site not published",
    "default web site page", "this site is temporarily unavailable", "index of /",
    "domain has expired", "this domain is for sale", "related searches",
]


def _clean(html_text):
    t = re.sub(r"(?is)<(script|style|noscript|svg)[\s\S]*?</\1>", " ", html_text)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _meta(html_text):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
    d = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]*content=["\'](.*?)["\']', html_text) or \
        re.search(r'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]*name=["\']description["\']', html_text)
    desc = re.sub(r"\s+", " ", html.unescape(d.group(1))).strip() if d else ""
    return title[:200], desc[:400]


def classify_page(status, html_text, chars):
    """Pure function: (http status, html) -> {status, title, description, text}. Easy to unit test."""
    if status in (401, 403, 429) or status >= 500:
        return {"status": "blocked", "title": "", "description": "", "text": ""}
    if status >= 400:
        return {"status": "dead", "title": "", "description": "", "text": ""}
    title, desc = _meta(html_text)
    body = _clean(html_text)
    low = (html_text[:20000] + " " + body[:3000]).lower()
    if any(p in low for p in PARKED_PATTERNS) and len(body) < 2500:
        return {"status": "parked", "title": title, "description": desc, "text": body[:500]}
    if len(body) < 150 and len(desc) < 40:
        return {"status": "parked", "title": title, "description": desc, "text": body}
    return {"status": "live", "title": title, "description": desc, "text": body[:chars]}


def fetch_live(domain, timeout=15, chars=3000, transport=None):
    """Fetch the homepage live. https then http then www. Returns {status, http, ...}.
    status: live | parked | blocked (site answered but refused us: 401/403/429/5xx) | dead."""
    transport = transport or net.fetch
    last_http = 0
    for url in ("https://%s/" % domain, "http://%s/" % domain, "https://www.%s/" % domain):
        try:
            st, hdrs, raw = transport("GET", url, {"User-Agent": BROWSER_UA, "Accept": "text/html,*/*;q=0.8"},
                                      None, timeout)
        except Exception:
            continue
        last_http = st
        if st >= 400 and st not in (401, 403, 429) and st < 500:
            continue
        ctype = hdrs.get("content-type", "")
        m = re.search(r"charset=([\w-]+)", ctype)
        try:
            text = raw[:400000].decode(m.group(1) if m else "utf-8", "replace")
        except LookupError:
            text = raw[:400000].decode("utf-8", "replace")
        out = classify_page(st, text, chars)
        out["http"] = st
        return out
    return {"status": "dead", "http": last_http, "title": "", "description": "", "text": ""}


def fetch_many(domains, on_result, concurrency=None, deadline=None, timeout=None, chars=None, fetcher=None):
    """Fetch many homepages concurrently with a hard per-row deadline (a hung socket must not stall the run)."""
    q = config.get("qualify")
    concurrency = concurrency or q["fetch_concurrency"]
    deadline = deadline or q["row_deadline_s"]
    timeout = timeout or q["fetch_timeout_s"]
    chars = chars or q["evidence_chars"]
    fetcher = fetcher or fetch_live
    starts = {}

    def task(d):
        starts[d] = time.time()
        res = fetcher(d, timeout=timeout, chars=chars)
        if res["status"] == "dead":  # transient DNS failures kill real companies: retry once
            time.sleep(min(5, timeout))
            res = fetcher(d, timeout=timeout, chars=chars)
        return res

    ex = ThreadPoolExecutor(max_workers=concurrency)
    futs = {ex.submit(task, d): d for d in domains}
    pending = set(futs)
    while pending:
        done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
        for f in done:
            try:
                res = f.result()
            except Exception as e:
                res = {"status": "error", "reason": str(e)[:100]}
            on_result(futs[f], res)
        now = time.time()
        for f in list(pending):
            d = futs[f]
            if d in starts and now - starts[d] > deadline:
                pending.discard(f)
                on_result(d, {"status": "error", "reason": "row deadline %ds" % deadline})
    ex.shutdown(wait=False, cancel_futures=True)


# ---- results -----------------------------------------------------------------------------------
def decide(qualified, confidence, min_conf):
    if qualified is None:
        return schema.FLAG_ERROR
    if not qualified:
        return schema.FLAG_DROP
    return schema.FLAG_KEEP if confidence >= min_conf else schema.FLAG_REVIEW


def parse_result_text(text):
    """Extract the JSON array from a subagent reply (tolerates fences and prose). Raises ValueError."""
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    a, b = t.find("["), t.rfind("]")
    if a < 0 or b < a:
        raise ValueError("no JSON array found")
    try:
        data = json.loads(t[a:b + 1])
    except json.JSONDecodeError as e:
        raise ValueError("invalid JSON: %s" % e)
    if not isinstance(data, list):
        raise ValueError("result must be a JSON array")
    return data


def validate_item(item, valid_ids):
    """Return (clean dict or None, problem or None)."""
    if not isinstance(item, dict):
        return None, "not an object"
    oid = str(item.get("id", ""))
    if oid not in valid_ids:
        return None, "unknown id %r" % oid
    q = item.get("qualified")
    if isinstance(q, str) and q.lower() in ("true", "false"):
        q = q.lower() == "true"
    if not isinstance(q, bool):
        return {"id": oid}, "qualified must be true or false"
    try:
        c = float(item.get("confidence"))
    except (TypeError, ValueError):
        return {"id": oid}, "confidence must be a number"
    if not 0.0 <= c <= 1.0:
        return {"id": oid}, "confidence out of range 0 to 1"
    reason = str(item.get("reason", "")).strip()
    if not reason:
        return {"id": oid}, "reason is empty"
    return {"id": oid, "qualified": q, "confidence": round(c, 2), "reason": reason[:200]}, None


class Qualify:
    """Stage 3 operations on one run folder."""

    def __init__(self, run):
        self.run = run
        self.dir = run.qdir
        self.dir.mkdir(exist_ok=True)
        (self.dir / "batches").mkdir(exist_ok=True)
        self.cfg = config.get("qualify")
        self.spec_path = self.dir / "spec.json"
        self.prompt_path = self.dir / "prompt.md"
        self.lock_path = self.dir / "prompt.locked.json"
        self.tuning_path = self.dir / "tuning.json"
        self.evidence_path = self.dir / "evidence.jsonl"
        self.results_path = self.dir / "results.jsonl"
        self.qualified_csv = self.dir / "qualified.csv"
        self.sample_log = self.dir / "samples.json"

    # -- inputs
    def accounts(self):
        rows = read_csv(self.run.accounts_csv)
        if not rows:
            raise RuntimeError("accounts.csv is missing or empty. Run accounts_pull.py first.")
        import pilot
        scope = pilot.scope_ids(self.run)  # an open accounts pilot limits qualify to the pilot accounts
        return [r for r in rows if r["org_id"] in scope] if scope is not None else rows

    def set_spec(self, spec):
        spec = dict(spec)
        try:
            brief_signals = self.run.brief().get("signals")
        except Exception:
            brief_signals = None
        if brief_signals:
            # the prompt always reflects the signals the user agreed in /iv-brief (the brief wins over a spec.json copied
            # from an earlier set-spec, so a changed threshold reaches the prompt as well as the hard drops)
            spec["signals"] = brief_signals
        text = build_prompt(spec)
        write_json(self.spec_path, spec)
        atomic_write(self.prompt_path, text)
        return text

    def is_locked(self):
        """Locked only while prompt.md is the exact prompt that passed tuning (set-spec after lock unlocks it)."""
        lk = read_json(self.lock_path, None)
        if not lk or not self.prompt_path.exists():
            return False
        return lk.get("prompt_sha") == __import__("hashlib").sha1(self.prompt_path.read_bytes()).hexdigest()[:10]

    def lock(self, rounds, note=""):
        write_json(self.lock_path, {"locked_at": now_iso(), "rounds": rounds, "note": note,
                                    "prompt_sha": __import__("hashlib").sha1(self.prompt_path.read_bytes()).hexdigest()[:10]})
        atomic_write(self.dir / ("prompt.locked-%s.md" % now_iso()[:10]), self.prompt_path.read_text(encoding="utf-8"))

    # -- tuning log
    def tuning(self):
        return read_json(self.tuning_path, {"rounds": []})

    def log_round(self, round_no, corrections, note=""):
        t = self.tuning()
        t["rounds"] = [r for r in t["rounds"] if r["round"] != round_no] + [
            {"round": round_no, "corrections": corrections, "note": note, "at": now_iso()}]
        t["rounds"].sort(key=lambda r: r["round"])
        write_json(self.tuning_path, t)
        return self.clean_streak(t)

    def clean_streak(self, t=None):
        t = t or self.tuning()
        streak = 0
        for r in reversed(t["rounds"]):
            if r["corrections"] == 0:
                streak += 1
            else:
                break
        return streak

    # -- evidence
    def evidence(self):
        ev = {}
        for r in read_jsonl(self.evidence_path):
            ev[r["domain"]] = r
        return ev

    def fetch_evidence(self, domains, progress=True):
        ev = self.evidence()
        todo = [d for d in dict.fromkeys(domains) if d and (d not in ev or ev[d]["status"] == "error")]
        counts = {}

        def on_result(d, res):
            rec = {"domain": d, "fetched_at": now_iso()}
            rec.update(res)
            append_jsonl(self.evidence_path, rec)
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            if progress and sum(counts.values()) % 50 == 0:
                print("  fetched %d/%d %s" % (sum(counts.values()), len(todo), counts), flush=True)

        if todo:
            fetch_many(todo, on_result)
        return counts

    # -- results
    def results(self):
        res = {}
        for r in read_jsonl(self.results_path):
            res[r["org_id"]] = r
        return res

    def _record(self, row, ev, qualified, confidence, reason, flag, batch=""):
        rec = {"org_id": row["org_id"], "domain": row["domain"], "name": row["name"],
               "website_status": (ev or {}).get("status", ""), "qualified": qualified,
               "confidence": confidence, "reason": reason, "flag": flag,
               "qualified_at": now_iso(), "batch": batch}
        append_jsonl(self.results_path, rec)
        return rec

    def resolve_unreadable(self, rows):
        """Rows whose site is dead or parked (or have no domain) are resolved without the model: flagged, kept."""
        ev, res, n = self.evidence(), self.results(), 0
        for row in rows:
            if row["org_id"] in res and res[row["org_id"]]["flag"] != schema.FLAG_ERROR:
                continue
            if not row["domain"]:
                self._record(row, {"status": "no_website"}, False, 1.0, "no website domain in Apollo",
                             schema.FLAG_DEAD, "auto")
                n += 1
                continue
            e = ev.get(row["domain"])
            if not e:
                continue
            if e["status"] == "dead":
                self._record(row, e, False, 0.9, "website did not load (HTTP %s)" % (e.get("http") or "no response"),
                             schema.FLAG_DEAD, "auto")
                n += 1
            elif e["status"] == "parked":
                self._record(row, e, False, 0.9, "website is parked, suspended or empty", schema.FLAG_PARKED, "auto")
                n += 1
        return n

    def resolve_signal_drops(self, rows):
        """HARD signals drop a company without the model: flag drop, reason 'signal: engineers 2000 > max 200', batch
        `auto-signal`. Rows stay. A company whose threshold no longer fails (the user changed it) loses its old signal drop
        and is scored again. Unknown data never drops. Returns the number of rows newly dropped or released."""
        import signals as signalsmod
        try:
            sigs = self.run.brief().get("signals")
        except Exception:
            sigs = None
        if not signalsmod.needs_apollo({"signals": sigs}):
            return 0
        sg = signalsmod.Signals(self.run)
        recs = sg.records()
        res, ev, n = self.results(), self.evidence(), 0
        for row in rows:
            reason = signalsmod.drop_reason(signalsmod.evaluate(sigs, recs.get(row.get("domain") or "")))
            cur = res.get(row["org_id"]) or {}
            was_auto = cur.get("batch") == "auto-signal"
            if reason:
                if was_auto and cur.get("reason") == reason:
                    continue
                self._record(row, ev.get(row["domain"]), False, 1.0, reason, schema.FLAG_DROP, "auto-signal")
                n += 1
            elif was_auto and cur.get("flag") != schema.FLAG_ERROR:
                self._record(row, ev.get(row["domain"]), None, "", "signal threshold changed, re-score", schema.FLAG_ERROR, "auto-signal-released")
                n += 1
        return n

    def signal_dropped(self, rows):
        """Org ids currently dropped by a hard signal."""
        res = self.results()
        return {r["org_id"] for r in rows if (res.get(r["org_id"]) or {}).get("batch") == "auto-signal"
                and res[r["org_id"]].get("flag") == schema.FLAG_DROP}

    def pending_rows(self, rows, include_errors=True):
        res = self.results()
        out = []
        for r in rows:
            x = res.get(r["org_id"])
            if x is None or (include_errors and x["flag"] == schema.FLAG_ERROR):
                out.append(r)
        return out

    # -- batch files
    def _signals_for(self, row):
        """The signals object of a batch item, or None when the brief has no signals. Values, the user's thresholds and the
        result of each (pass | fail | unknown | judge), plus Apollo's technology list for text signals."""
        import signals as signalsmod
        try:
            sigs = self.run.brief().get("signals")
        except Exception:
            sigs = None
        if not sigs:
            return None
        sg = signalsmod.Signals(self.run)
        recs = sg.records()
        vals = sg.values(row, recs)
        rec = recs.get(row.get("domain") or "") or {}
        checks = signalsmod.evaluate(sigs, rec)
        out_vals = {k: vals[k] for k in ["employees"] + list(config.get("signals.fixed_departments", [])) if vals.get(k, "") != ""}
        return {"values": out_vals, "status": vals["signals_status"],
                "rules": [{"name": c["name"], "strength": c["strength"], "rule": c["rule"], "value": c["value"],
                           "result": c["result"]} for c in checks],
                "technologies": (rec.get("technologies") or [])[:25]}

    def _item(self, row, ev):
        ev = ev or {}
        item = self._item_base(row, ev)
        sg = self._signals_for(row)
        if sg is not None:
            item["signals"] = sg
        return item

    def _item_base(self, row, ev):
        return {"id": row["org_id"], "name": row["name"], "domain": row["domain"],
                "facts": {k: row[k] for k in ("country", "city", "filter_location", "revenue", "founded_year", "naics", "sic")
                          if row.get(k)},
                "website_status": ev.get("status", "unknown"), "page_title": ev.get("title", ""),
                "meta_description": ev.get("description", ""), "homepage_text": ev.get("text", "")}

    def _write_batch(self, name, items, kind):
        path = self.dir / "batches" / (name + ".json")
        write_json(path, {"batch": name, "kind": kind, "issued_at": now_iso(),
                          "prompt_file": str(self.prompt_path),
                          "result_file": str(self.dir / "batches" / (name + ".result.json")),
                          "output_format": 'JSON array: [{"id","qualified","confidence","reason"}], one object per row',
                          "rows": items})
        return path

    def sample_batch(self, round_no, n=None):
        """Pick n companies with a readable live site, not sampled before, and write sample-rN.json."""
        n = n or self.cfg["sample_size"]
        rows = self.accounts()
        import signals as signalsmod
        signalsmod.require_ready(self.run, self.run.brief(), rows)
        self.resolve_signal_drops(rows)
        dropped = self.signal_dropped(rows)  # hard-signal drops never reach the model, so they are not tuning samples
        rows = [r for r in rows if r["org_id"] not in dropped]
        log = read_json(self.sample_log, {"rounds": {}})
        used = {i for ids in log["rounds"].values() for i in ids}
        rng = random.Random("%s-%d" % (self.run.dir.name, round_no))
        cand = [r for r in rows if r["org_id"] not in used and r["domain"]]
        rng.shuffle(cand)
        chosen = []
        pool = cand[: max(n * 4, 20)]
        self.fetch_evidence([r["domain"] for r in pool], progress=False)
        ev = self.evidence()
        for r in pool:
            if ev.get(r["domain"], {}).get("status") in ("live", "blocked"):
                chosen.append(r)
            if len(chosen) >= n:
                break
        if not chosen:
            raise RuntimeError("no unsampled companies with a readable website left")
        log["rounds"][str(round_no)] = [r["org_id"] for r in chosen]
        write_json(self.sample_log, log)
        return self._write_batch("sample-r%d" % round_no, [self._item(r, ev.get(r["domain"])) for r in chosen], "sample")

    def make_batches(self, size=None, reissue=False):
        """Create batch files for rows that still need scoring. Fetches missing evidence first."""
        size = size or self.cfg["batch_size"]
        rows = self.accounts()
        import signals as signalsmod
        signalsmod.require_ready(self.run, self.run.brief(), rows)
        signal_drops = self.resolve_signal_drops(rows)
        dropped = self.signal_dropped(rows)
        counts = self.fetch_evidence([r["domain"] for r in rows if r["domain"] and r["org_id"] not in dropped])
        self.resolve_unreadable([r for r in rows if r["org_id"] not in dropped])
        pend = self.pending_rows([r for r in rows if r["org_id"] not in dropped])
        # skip rows already sitting in a fresh unanswered batch
        issued = set()
        stale = self.cfg["batch_stale_minutes"] * 60
        for p in sorted((self.dir / "batches").glob("batch-*.json")):
            if p.name.endswith(".result.json"):
                continue
            if (self.dir / "batches" / (p.stem + ".result.json")).exists() and not reissue:
                continue
            b = read_json(p)
            age = time.time() - p.stat().st_mtime
            if reissue or age > stale:
                continue
            issued |= {i["id"] for i in b["rows"]}
        todo = [r for r in pend if r["org_id"] not in issued]
        ev = self.evidence()
        existing = [int(re.search(r"(\d+)", p.stem).group(1)) for p in (self.dir / "batches").glob("batch-*.json")
                    if not p.name.endswith(".result.json")]
        n0 = max(existing or [0])
        paths = []
        for i in range(0, len(todo), size):
            chunk = todo[i:i + size]
            n0 += 1
            paths.append(self._write_batch("batch-%04d" % n0, [self._item(r, ev.get(r["domain"])) for r in chunk], "score"))
        return {"fetched": counts, "pending": len(pend), "batches": [str(p) for p in paths],
                "skipped_in_flight": len(pend) - len(todo), "signal_drops": signal_drops}

    def ingest_file(self, path):
        """Validate one result file against its batch and append results. Returns a report dict."""
        path = Path(path)
        batch_path = path.with_name(path.name.replace(".result.json", ".json"))
        batch = read_json(batch_path)
        if batch is None:
            raise RuntimeError("no batch file for %s" % path.name)
        items = {i["id"]: i for i in batch["rows"]}
        rows = {r["org_id"]: r for r in self.accounts()}
        ev = self.evidence()
        report = {"batch": batch["batch"], "ok": 0, "invalid": 0, "missing": 0, "problems": []}
        try:
            data = parse_result_text(path.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError) as e:
            report["problems"].append(str(e))
            report["missing"] = len(items)
            return report
        seen = set()
        cur_results = self.results()
        for it in data:
            clean, problem = validate_item(it, set(items))
            if clean is None:
                report["invalid"] += 1
                report["problems"].append(problem)
                continue
            oid = clean["id"]
            seen.add(oid)
            if batch["kind"] == "sample":
                continue
            row = rows.get(oid)
            if row is None:
                continue
            c0 = cur_results.get(oid) or {}
            if c0.get("batch") == "auto-signal" and c0.get("flag") == schema.FLAG_DROP:
                report["ok"] += 1  # dropped by a hard signal after this batch was issued: the signal drop stands
                continue
            if problem:
                report["invalid"] += 1
                report["problems"].append("%s: %s" % (oid, problem))
                self._record(row, ev.get(row["domain"]), None, "", "invalid result: " + problem, schema.FLAG_ERROR,
                             batch["batch"])
                continue
            flag = decide(clean["qualified"], clean["confidence"], self.cfg["min_confidence"])
            self._record(row, ev.get(row["domain"]), clean["qualified"], clean["confidence"], clean["reason"], flag,
                         batch["batch"])
            report["ok"] += 1
        if batch["kind"] == "sample":
            report["ok"] = len(seen)
        report["missing"] = len(set(items) - seen)
        return report

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
            out.append({"name": row["name"], "domain": row["domain"], "site": row["website_status"],
                        "title": row["page_title"], "qualified": g.get("qualified"), "confidence": g.get("confidence"),
                        "reason": g.get("reason", "(no result)")})
        return out

    def status(self):
        rows = read_csv(self.run.accounts_csv)
        res = self.results()
        flags = {}
        for r in rows:
            f = res.get(r["org_id"], {}).get("flag", "unscored")
            flags[f] = flags.get(f, 0) + 1
        batches = {"open": [], "answered": 0}
        for p in sorted((self.dir / "batches").glob("batch-*.json")):
            if p.name.endswith(".result.json"):
                continue
            if (self.dir / "batches" / (p.stem + ".result.json")).exists():
                batches["answered"] += 1
            else:
                age_min = (time.time() - p.stat().st_mtime) / 60
                batches["open"].append({"batch": p.stem, "age_min": round(age_min),
                                        "stale": age_min > self.cfg["batch_stale_minutes"]})
        return {"accounts": len(rows), "flags": flags, "locked": self.is_locked(),
                "clean_streak": self.clean_streak(), "batches": batches,
                "min_confidence": self.cfg["min_confidence"]}

    def finalize(self, push=True):
        import pilot
        import signals as signalsmod
        rows = self.accounts()
        res = self.results()
        ov = pilot.account_overrides(self.run)  # the human pilot review beats the AI (reject -> drop, approve -> not dropped)
        seeds = pilot.seeds(self.run)
        pilot_ids = set(pilot.account_ids(self.run))
        sg = signalsmod.Signals(self.run)
        recs = sg.records()
        out = []
        for r in rows:
            x = res.get(r["org_id"], {})
            row = dict(r)
            flag, q2, reason = pilot.apply_override(x.get("flag", ""), ov.get(r["org_id"]), x.get("reason", ""))
            qual = "" if x.get("qualified") is None else x.get("qualified", "")
            if q2 is not None:
                qual = q2
            row.update({"website_status": x.get("website_status", ""), "qualified": qual,
                        "confidence": x.get("confidence", ""), "flag": flag,
                        "reason": reason, "qualified_at": x.get("qualified_at", "")})
            vals = sg.values(r, recs) if recs else {}
            row.update({k: vals.get(k, "") for k in schema.SIGNAL_COLS})
            o = ov.get(r["org_id"]) or {}
            row.update({"pilot": "yes" if r["org_id"] in pilot_ids else "", "pilot_review": o.get("review", ""),
                        "pilot_note": o.get("note", ""), "is_seed": seeds.get(r["org_id"], "")})
            out.append(row)
        write_csv(self.qualified_csv, out, schema.ACCOUNT_COLS)
        pushed = None
        if push and self.run.sheet_id():
            import sheet as sheetmod
            recs = [{"org_id": r["org_id"], **{c: r[c] for c in schema.QUALIFY_COLS}} for r in out if r["flag"]]
            for rec in recs:
                if rec["qualified"] in (True, False):
                    rec["qualified"] = bool(rec["qualified"])
            pushed = sheetmod.SheetClient().upsert(self.run.sheet_id(), schema.TAB_ACCOUNTS, "org_id", recs)
        return {"rows": len(out), "scored": sum(1 for r in out if r["flag"]), "sheet": pushed}
