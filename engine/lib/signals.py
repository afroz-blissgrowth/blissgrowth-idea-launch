"""Company signals: which headcount and other facts matter for THIS idea, and the data to judge them.

Two halves.

1. The brief's `signals` list (decided WITH the user in /iv-brief, never by Claude alone):
     {"name": "engineers", "source_field": "engineering", "op": "lte", "value": 200, "strength": "hard"}
     {"name": "sales_share", "source_field": "sales_pct", "op": "gte", "value": 30, "strength": "soft"}
     {"name": "uses_sap", "kind": "text", "description": "Runs SAP or another ERP", "strength": "soft"}
   source_field is `employees`, an Apollo department key (engineering, operations, sales, information_technology, ...),
   or a department key plus `_pct` (that department as a percent of total employees). op is lt, lte, gt, gte, eq, ne
   or between (value [low, high]); the aliases <, <=, >, >=, =, !=, min (gte) and max (lte) are accepted. `hard`
   numeric signals can drop a company automatically (flag drop, reason "signal: engineers 2000 > max 200"); `soft`
   ones are only shown to the AI judge. A signal whose data is missing is `unknown` and NEVER drops a company.
   `text` signals (tools used, uses consultancies, anything Apollo has no number for) are judged by Claude from the
   website evidence, so they are always soft; a must-have text criterion belongs in icp.hard / qualify.qualifies.

2. The data: Apollo organization enrichment by domain (POST organizations/bulk_enrich, 10 domains per call, 1 credit per
   matched company). Each domain is enriched once: the answer is cached in the run (signals/enrich.jsonl) and in a
   shared cross-run cache (<lists dir>/_cache/signals-cache.jsonl, `signals.cache_days`), so a re-run or another idea never
   pays twice for the same company. Credits are read from the answer and logged in apollo-usage.jsonl.

The headcount columns (employees, engineering, operations, sales and the other configured departments) are written to
the "2 Accounts" tab with add_columns + upsert.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config
import schema
from util import append_jsonl, now_iso, read_csv, read_json, read_jsonl, write_json

OP_ALIASES = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "=": "eq", "==": "eq", "!=": "ne", "min": "gte", "max": "lte"}
OPS = ("lt", "lte", "gt", "gte", "eq", "ne", "between")
STRENGTHS = ("hard", "soft")
FINAL = ("matched", "not_found")


class SignalError(ValueError):
    pass


# ---- definitions (pure) --------------------------------------------------------------------------
def numeric_field_ok(field):
    """employees, <department>, <department>_pct."""
    if field == "employees":
        return True
    known = set(config.get("signals.known_departments", []))
    base = field[:-4] if field.endswith("_pct") else field
    return base in known


def norm_op(op):
    o = OP_ALIASES.get(str(op).strip().lower(), str(op).strip().lower())
    return o if o in OPS else None


def kind_of(sig):
    return sig.get("kind") or ("numeric" if sig.get("source_field") else "text")


def validate(signals):
    """Problems with a brief's signals list (empty list = OK). Accepts None."""
    errors = []
    if signals in (None, []):
        return errors
    if not isinstance(signals, list):
        return ["signals must be a list"]
    seen = set()
    for i, s in enumerate(signals):
        w = "signals[%d]" % i
        if not isinstance(s, dict):
            errors.append("%s must be an object" % w)
            continue
        name = s.get("name")
        if not name or not isinstance(name, str):
            errors.append("%s.name is required" % w)
        elif name.lower() in seen:
            errors.append("%s: duplicate signal name '%s'" % (w, name))
        else:
            seen.add(name.lower())
        if s.get("strength") not in STRENGTHS:
            errors.append("%s.strength must be 'hard' or 'soft' (the user decides which)" % w)
        k = kind_of(s)
        if k not in ("numeric", "text"):
            errors.append("%s.kind must be numeric or text" % w)
        elif k == "text":
            if not s.get("description"):
                errors.append("%s: a text signal needs a description (what Claude should look for in the evidence)" % w)
            if s.get("strength") == "hard":
                errors.append("%s: a text signal cannot be hard (nothing can check it automatically). Make it soft, or "
                              "put the must-have in icp.hard and qualify.qualifies/disqualifies" % w)
        else:
            f = s.get("source_field")
            if not f or not numeric_field_ok(f):
                errors.append("%s.source_field '%s' is not employees, a department key or <department>_pct. Known departments: %s"
                              % (w, f, ", ".join(config.get("signals.known_departments", []))))
            op = norm_op(s.get("op", ""))
            if not op:
                errors.append("%s.op must be one of %s (or <, <=, >, >=, =, !=, min, max)" % (w, ", ".join(OPS)))
            v = s.get("value")
            if op == "between":
                if not (isinstance(v, list) and len(v) == 2 and all(_isnum(x) for x in v) and v[0] <= v[1]):
                    errors.append("%s.value must be [low, high] for between" % w)
            elif not _isnum(v):
                errors.append("%s.value must be a number" % w)
    return errors


def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def canonical(signals):
    """Signals with op names normalised (call after validate)."""
    out = []
    for s in signals or []:
        c = dict(s)
        c["kind"] = kind_of(s)
        if c["kind"] == "numeric":
            c["op"] = norm_op(s["op"])
        out.append(c)
    return out


def numeric(signals):
    return [s for s in canonical(signals) if s["kind"] == "numeric"]


def needs_apollo(brief):
    """True when the brief has at least one numeric signal (so Apollo headcounts are needed)."""
    return bool(numeric((brief or {}).get("signals")))


def extra_departments(signals):
    """Departments the brief's signals use that are not among the fixed sheet columns (they get dept_<key> columns)."""
    fixed = set(config.get("signals.fixed_departments", schema.SIGNAL_COLS[1:8]))
    out = []
    for s in numeric(signals):
        f = s["source_field"]
        base = f[:-4] if f.endswith("_pct") else f
        if base != "employees" and base not in fixed and base not in out:
            out.append(base)
    return out


# ---- evaluation (pure) ---------------------------------------------------------------------------
def field_value(rec, field):
    """Value of a signal field for one enrichment record {employees, departments}. None = unknown."""
    if not rec or rec.get("status") not in (None, "matched"):
        return None
    emp = rec.get("employees")
    if field == "employees":
        return emp
    pct = field.endswith("_pct")
    dept = field[:-4] if pct else field
    depts = rec.get("departments") or {}
    if dept in depts:
        v = depts[dept]
    elif depts and config.get("signals.missing_department_is_zero", True):
        v = 0  # Apollo lists the departments it found people in; a missing one means none
    else:
        return None
    if not pct:
        return v
    if not emp:
        return None
    return round(100.0 * v / emp, 1)


def _cmp(op, v, thr):
    if op == "lt":
        return v < thr
    if op == "lte":
        return v <= thr
    if op == "gt":
        return v > thr
    if op == "gte":
        return v >= thr
    if op == "eq":
        return v == thr
    if op == "ne":
        return v != thr
    if op == "between":
        return thr[0] <= v <= thr[1]
    raise SignalError("bad op %r" % op)


def rule_text(sig):
    """The rule as the user would say it: 'max 200', 'min 30', 'between 10 and 20', '< 5'."""
    op, v = sig["op"], sig.get("value")
    pct = "%" if str(sig.get("source_field", "")).endswith("_pct") else ""
    if op == "lte":
        return "max %s%s" % (_num(v), pct)
    if op == "gte":
        return "min %s%s" % (_num(v), pct)
    if op == "between":
        return "between %s and %s%s" % (_num(v[0]), _num(v[1]), pct)
    return "%s %s%s" % ({"lt": "<", "gt": ">", "eq": "=", "ne": "!="}[op], _num(v), pct)


def _num(x):
    return str(int(x)) if isinstance(x, float) and x == int(x) else str(x)


def violation_text(sig, value):
    """'engineers 2000 > max 200' (what failed and how). Used as the drop reason after 'signal: '."""
    op, v = sig["op"], sig.get("value")
    pct = "%" if str(sig.get("source_field", "")).endswith("_pct") else ""
    val = "%s%s" % (_num(value), pct)
    if op == "lte":
        return "%s %s > max %s%s" % (sig["name"], val, _num(v), pct)
    if op == "gte":
        return "%s %s < min %s%s" % (sig["name"], val, _num(v), pct)
    if op == "between":
        return "%s %s outside %s to %s%s" % (sig["name"], val, _num(v[0]), _num(v[1]), pct)
    sym = {"lt": ">= %s", "gt": "<= %s", "eq": "!= %s", "ne": "= %s"}[op] % _num(v)
    return "%s %s %s%s" % (sig["name"], val, sym, pct)


def evaluate(signals, rec):
    """One result per signal: {name, kind, strength, field, rule, value, result, detail}. result is pass | fail |
    unknown | judge (text signals, judged by Claude). Never raises on missing data."""
    out = []
    for s in canonical(signals):
        base = {"name": s["name"], "kind": s["kind"], "strength": s["strength"], "note": s.get("note", "")}
        if s["kind"] == "text":
            out.append(dict(base, field="", rule=s["description"], value=None, result="judge", detail=s["description"]))
            continue
        val = field_value(rec, s["source_field"])
        rt = rule_text(s)
        if val is None:
            out.append(dict(base, field=s["source_field"], rule=rt, value=None, result="unknown",
                            detail="%s unknown (no Apollo data), rule %s" % (s["name"], rt)))
        elif _cmp(s["op"], val, s["value"]):
            out.append(dict(base, field=s["source_field"], rule=rt, value=val, result="pass",
                            detail="%s %s ok (%s)" % (s["name"], _num(val), rt)))
        else:
            out.append(dict(base, field=s["source_field"], rule=rt, value=val, result="fail",
                            detail=violation_text(s, val)))
    return out


def hard_failures(results):
    return [r for r in results if r["strength"] == "hard" and r["result"] == "fail"]


def drop_reason(results):
    """'signal: engineers 2000 > max 200' (several hard failures are joined with '; ') or ''."""
    hf = hard_failures(results)
    return ("signal: " + "; ".join(r["detail"] for r in hf))[:200] if hf else ""


# ---- caching and enrichment ----------------------------------------------------------------------
def shared_cache_path():
    return config.lists_dir() / "_cache" / "signals-cache.jsonl"


def _age_days(iso):
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return 10 ** 6


class Signals:
    """Signal enrichment for one run folder."""

    def __init__(self, run):
        self.run = run
        self.dir = run.dir / "signals"
        self.dir.mkdir(exist_ok=True)
        self.path = self.dir / "enrich.jsonl"
        self.cfg = config.get("signals") or {}

    # -- data
    def records(self):
        out = {}
        for r in read_jsonl(self.path):
            if r.get("domain"):
                out[r["domain"]] = r
        return out

    def shared(self):
        if not self.cfg.get("shared_cache", True):
            return {}
        out = {}
        for r in read_jsonl(shared_cache_path()):
            if r.get("domain") and r.get("status") in FINAL and _age_days(r.get("enriched_at")) <= self.cfg.get("cache_days", 90):
                out[r["domain"]] = r
        return out

    def accounts(self):
        return read_csv(self.run.accounts_csv)

    def scope_rows(self, scope=None):
        """Account rows in scope. scope: None (all of accounts.csv) | 'pilot' | an iterable of org ids."""
        rows = self.accounts()
        if scope == "pilot":
            import pilot
            ids = set(pilot.account_ids(self.run))
            rows = [r for r in rows if r["org_id"] in ids]
        elif scope:
            ids = set(scope)
            rows = [r for r in rows if r["org_id"] in ids]
        return rows

    def todo_domains(self, rows):
        """Distinct domains with no final answer (run or shared cache). Errors are retried. Returns (to_call, from_cache)."""
        have, shared = self.records(), self.shared()
        call, cached, seen = [], [], set()
        for r in rows:
            d = r.get("domain")
            if not d or d in seen:
                continue
            seen.add(d)
            if have.get(d, {}).get("status") in FINAL:
                continue
            (cached if d in shared else call).append(d)
        return call, cached

    def estimate(self, rows):
        call, cached = self.todo_domains(rows)
        return {"accounts": len(rows), "domains_to_enrich": len(call), "from_shared_cache": len(cached),
                "calls": -(-len(call) // self.cfg.get("batch", 10)),
                "credits_max": len(call) * self.cfg.get("credits_per_matched_org", 1),
                "note": "1 credit per matched company (0 when Apollo has no match). Each domain is enriched once."}

    def run_signals(self, client, scope=None, limit=None, progress=print):
        """Enrich the in-scope accounts not yet enriched. Returns a report. Stops on fatal Apollo errors."""
        import apollo
        rows = self.scope_rows(scope)
        call, cached = self.todo_domains(rows)
        rep = {"accounts": len(rows), "from_shared_cache": 0, "requested": 0, "matched": 0, "not_found": 0, "errors": 0,
               "credits": 0.0, "calls": 0, "paused": "", "skipped_by_limit": 0}
        shared = self.shared()
        for d in cached:  # free: another run already paid for this company
            rec = dict(shared[d], source="shared_cache", credits=0, copied_at=now_iso())
            append_jsonl(self.path, rec)
            rep["from_shared_cache"] += 1
        if limit is not None and len(call) > limit:
            rep["skipped_by_limit"] = len(call) - limit
            call = call[:limit]
        size = self.cfg.get("batch", 10)
        for i in range(0, len(call), size):
            if client.hour_budget_low():
                rep["paused"] = "hourly Apollo request budget nearly used; re-run later (nothing is paid twice)"
                break
            chunk = call[i:i + size]
            client.label = "signals"
            try:
                res = client.org_bulk_enrich(chunk)
            except apollo.ApolloError as e:
                rep["errors"] += 1
                rep["paused"] = "Apollo error, stopped: %s" % e
                for d in chunk:
                    append_jsonl(self.path, {"domain": d, "status": "error", "error": str(e)[:200], "enriched_at": now_iso()})
                if e.status in (401, 402, 403, 422) or rep["errors"] >= 3:
                    break
                continue
            rep["calls"] += 1
            rep["credits"] += res["credits"]
            for d, o in zip(chunk, pair_matches(chunk, res)):
                rep["requested"] += 1
                rec = {"domain": d, "enriched_at": now_iso(), "batch_credits": res["credits"], "batch_size": len(chunk),
                       "source": "apollo_org_bulk_enrich"}
                if o:
                    rec.update({"status": "matched", "apollo_org_id": o["org_id"], "name": o["name"],
                                "employees": o["employees"], "departments": o["departments"],
                                "industry": o["industry"], "technologies": o["technologies"]})
                    rep["matched"] += 1
                else:
                    rec["status"] = "not_found"
                    rep["not_found"] += 1
                append_jsonl(self.path, rec)
                if self.cfg.get("shared_cache", True):
                    try:
                        append_jsonl(shared_cache_path(), rec)
                    except OSError:
                        pass
            if progress:
                progress("  enriched %d of %d domains (credits so far %.1f)" % (min(i + size, len(call)), len(call), rep["credits"]))
        rep["credits"] = round(rep["credits"], 2)
        return rep

    # -- per account view
    def status_of(self, row, recs=None):
        recs = recs if recs is not None else self.records()
        d = row.get("domain")
        if not d:
            return "no_domain"
        r = recs.get(d)
        if not r:
            return "pending"
        return {"matched": "enriched", "not_found": "not_found", "error": "error"}.get(r.get("status"), "pending")

    def values(self, row, recs=None):
        """Flat signal values for one account row: the sheet columns plus the raw record."""
        recs = recs if recs is not None else self.records()
        r = recs.get(row.get("domain") or "") or {}
        depts = r.get("departments") or {}
        out = {"employees": "" if r.get("employees") is None else r.get("employees", ""),
               "signals_status": self.status_of(row, recs), "signals_at": r.get("enriched_at", "")}
        for d in config.get("signals.fixed_departments", []):
            out[d] = depts[d] if d in depts else ("" if not depts else 0)
        return out

    def evaluate_row(self, signals, row, recs=None):
        recs = recs if recs is not None else self.records()
        return evaluate(signals, recs.get(row.get("domain") or ""))

    def sheet_records(self, rows, extra_depts=()):
        recs = self.records()
        out = []
        for r in rows:
            v = self.values(r, recs)
            rec = {"org_id": r["org_id"]}
            rec.update({k: v[k] for k in schema.SIGNAL_COLS if k in v})
            depts = (recs.get(r.get("domain") or "") or {}).get("departments") or {}
            for d in extra_depts:
                rec["dept_" + d] = depts[d] if d in depts else ("" if not depts else 0)
            if v["signals_status"] != "pending":
                out.append(rec)
        return out

    def push_to_sheet(self, rows, brief, sc=None):
        """Add the signal columns to '2 Accounts' (add_columns, idempotent) and upsert the values by org_id."""
        import sheet as sheetmod
        sid = self.run.sheet_id()
        if not sid:
            return {"pushed": 0, "note": "no sheet for this run"}
        sc = sc or sheetmod.SheetClient()
        extra = extra_departments((brief or {}).get("signals"))
        sc.add_columns(sid, schema.TAB_ACCOUNTS, schema.ACCOUNT_COLS + ["dept_" + d for d in extra])
        recs = self.sheet_records(rows, extra)
        if not recs:
            return {"pushed": 0}
        up = sc.upsert(sid, schema.TAB_ACCOUNTS, "org_id", recs)
        return {"pushed": up.get("updated", 0) + up.get("appended", 0), "unknown_columns": up.get("unknown_columns", [])}

    def summary(self, rows):
        recs = self.records()
        c = {"accounts": len(rows), "enriched": 0, "not_found": 0, "pending": 0, "no_domain": 0, "error": 0}
        for r in rows:
            c[self.status_of(r, recs)] += 1
        return c


def pair_matches(chunk, res):
    """Pair each requested domain with its enrichment record: by domain first, then by position when Apollo kept the
    input order (`aligned`), then a single leftover record with a single leftover domain. None = not matched."""
    orgs = list(res.get("orgs") or [])
    by_dom = {o["domain"]: o for o in orgs if o.get("domain")}
    out = [by_dom.get(d) for d in chunk]
    aligned = res.get("aligned")
    if aligned:
        for i, d in enumerate(chunk):
            if out[i] is None and aligned[i] is not None and aligned[i] not in out:
                out[i] = aligned[i]
    used = [o for o in out if o]
    left_orgs = [o for o in orgs if o not in used]
    left_idx = [i for i, o in enumerate(out) if o is None]
    if len(left_orgs) == 1 and len(left_idx) == 1:
        out[left_idx[0]] = left_orgs[0]
    return out


def require_ready(run, brief, rows=None):
    """Raise RuntimeError when the brief has numeric signals and some account with a domain is not enriched yet.
    rows: the accounts qualify is about to work on (default: all of accounts.csv)."""
    if not needs_apollo(brief):
        return
    sg = Signals(run)
    c = sg.summary(rows if rows is not None else sg.accounts())
    if c["pending"] or c["error"]:
        raise RuntimeError("signals are not enriched for %d accounts. Run: python3 -I bin/signals_run.py run %s "
                           "(1 credit per matched company), then qualify." % (c["pending"] + c["error"], run.dir.name))
