"""List quality report: the 8 checks of coldoutboundskills list-quality-scorecard/scripts/score-list.ts
(MIT, copyright 2026 GrowthEngineX), ported to Python and adapted to this engine.

The 8 dimensions, in the original order, with the adaptation noted where we deviate on purpose:
 1. Email verification      share of people with an email whose MillionVerifier result is `ok` (strict: only ok).
 2. Duplicate emails        100 - 20 * duplicate percent (as the original).
 3. Domain concentration    ADAPTED. The original scores average leads per domain (<2 good). This engine wants up
                            to T1 cap + T2 cap people per company by design, so the limit here is that sum and only
                            rows above it count.
 4. Title relevance         share of people whose title matches the brief's titles (or who Claude tiered T1/T2).
 5. Bad titles              intern, assistant, coordinator, student, part-time, retired, trainee (config.quality).
 6. Role and catch-all      role-based addresses (info@, sales@ ...) plus, ADDED, MillionVerifier `catch_all` results
                            (the original only had the role-based list). Thresholds as the original (<5% good).
 7. ICP fit                 ADAPTED. We do not filter by industry or headcount (the qualify step judges fit), so this
                            is the share of people at companies the qualify step marked `keep` (review counts half).
 8. Name quality            first and last name present, not ALL CAPS, no digits, not a fake name.
Weighted average (verification and ICP fit weigh 2, title relevance 1.5), letter grade bands as the original.
Graded list: selected (capped) people who have an email. Under 100 rows the grade is indicative only (the original
says so too). The grade goes to summary.md and the Run Log; the full report to list-quality.md.
"""
from __future__ import annotations

import re

import brief as briefmod
import config
import people as peoplemod
import schema
from util import atomic_write, now_iso, read_csv, write_json


def letter(score, bands=None):
    for lo, g in (bands or config.get("quality.grade_bands")):
        if score >= lo:
            return g
    return "F"


def _fake_name(first, last, fakes):
    if not first or not last:
        return True
    if first.upper() == first and len(first) > 2:
        return True
    if re.search(r"\d", first + last):
        return True
    return first.lower() in fakes or last.lower() in fakes


def score(rows, brief, qualify_flags=None):
    """rows: people table rows (dicts). qualify_flags: {org_id: 'keep'|'review'}. Returns the report dict."""
    qcfg = config.get("quality")
    vcfg = config.get("verify")
    graded = [r for r in rows if r["cap_status"] == schema.CAP_SELECTED and r.get("email")]
    n = len(graded)
    out = {"rows": n, "selected": sum(1 for r in rows if r["cap_status"] == schema.CAP_SELECTED), "dims": [],
           "issues": [], "generated_at": now_iso(), "indicative_only": n < 100}
    if n == 0:
        out.update({"score": 0, "grade": "F", "issues": ["no selected people with an email yet"]})
        return out
    caps = briefmod.people_caps(brief)
    limit = caps["T1"] + caps["T2"]
    bad = [re.compile(r"\b%s\b" % p, re.I) for p in qcfg["bad_title_patterns"]]
    fakes = set(qcfg["fake_names"])
    roles = set(vcfg["role_local_parts"])
    dims = []

    def add(key, name, sc, detail):
        dims.append({"key": key, "name": name, "score": max(0, min(100, int(round(sc)))), "detail": detail,
                     "weight": qcfg["dim_weights"][key]})

    ok = sum(1 for r in graded if (r["mv_result"] or "") in vcfg["pass_results"])
    checked = sum(1 for r in graded if r["mv_result"])
    add("email_verification", "Email verification", 100.0 * ok / n if checked else 0,
        "%d of %d emails are ok (%d checked at all)" % (ok, n, checked))
    seen, dup = set(), 0
    for r in graded:
        e = r["email"].lower()
        dup += e in seen
        seen.add(e)
    add("duplicate_emails", "Duplicate emails", 100 - 20.0 * (100.0 * dup / n), "%d duplicate emails (%.1f%%)" % (dup, 100.0 * dup / n))
    dom = {}
    for r in graded:
        d = (r["domain"] or r["email"].split("@")[1]).lower()
        dom[d] = dom.get(d, 0) + 1
    excess = sum(max(0, c - limit) for c in dom.values())
    add("domain_concentration", "Domain concentration", 100 - 100.0 * excess / n,
        "%d domains, max %d people on one (limit %d = T1 cap + T2 cap), %d rows above the limit"
        % (len(dom), max(dom.values()), limit, excess))
    rel = sum(1 for r in graded if peoplemod.rank_of(r["title_rank"]) < 1000 or r["tier"] in (schema.TIER_T1, schema.TIER_T2))
    add("title_relevance", "Title relevance", 100.0 * rel / n, "%d of %d titles match the brief or were tiered T1/T2" % (rel, n))
    nbad = sum(1 for r in graded if any(p.search(r["title"] or "") for p in bad))
    add("bad_titles", "Bad-title detection", 100 - 10.0 * (100.0 * nbad / n), "%d bad titles (%.1f%%)" % (nbad, 100.0 * nbad / n))
    nrole = sum(1 for r in graded if r["email"].split("@")[0].lower() in roles)
    ncatch = sum(1 for r in graded if (r["mv_result"] or "") in vcfg["catch_all_results"])
    pct = 100.0 * (nrole + ncatch) / n
    add("catch_all_density", "Role and catch-all", 100 if pct < 5 else (100 - (pct - 5) * 5 if pct < 15 else 0),
        "%d role addresses, %d catch-all results (%.1f%%)" % (nrole, ncatch, pct))
    flags = qualify_flags or {}
    fit = sum(1.0 if flags.get(r["org_id"]) == schema.FLAG_KEEP else (0.5 if flags.get(r["org_id"]) == schema.FLAG_REVIEW else 0)
              for r in graded)
    add("icp_fit", "ICP fit", 100.0 * fit / n, "%.0f%% of people at companies qualified `keep` (review counts half)" % (100.0 * fit / n))
    nfake = sum(1 for r in graded if _fake_name(r["first_name"], r["last_name"], fakes))
    add("name_quality", "Name quality", 100.0 * (n - nfake) / n, "%d of %d names look wrong or are missing" % (nfake, n))
    tw = sum(d["weight"] for d in dims)
    overall = int(round(sum(d["score"] * d["weight"] for d in dims) / tw))
    out.update({"dims": dims, "score": overall, "grade": letter(overall, qcfg["grade_bands"])})
    issues = []
    if ok < n:
        issues.append("%d of %d emails are not `ok` (%d unchecked): verify, then drop invalid ones" % (n - ok, n, n - checked))
    if dup:
        issues.append("%d duplicate emails: deduplicate before upload" % dup)
    if ncatch:
        issues.append("%d emails are catch-all: keep for a secondary verifier, do not send blind" % ncatch)
    if nrole:
        issues.append("%d role addresses (info@, sales@ ...): drop or deprioritise" % nrole)
    if nbad:
        issues.append("%d bad titles: tighten the title list or tier them X" % nbad)
    if excess:
        issues.append("%d rows above the per-company limit of %d" % (excess, limit))
    if rel < 0.8 * n:
        issues.append("only %.0f%% of titles match the brief: titles from similar-title expansion may be drifting" % (100.0 * rel / n))
    if fit < 0.8 * n:
        issues.append("%.0f%% of people sit at `review` companies: consider tightening qualify" % (100 - 100.0 * fit / n))
    if nfake > 0.05 * n:
        issues.append("%d rows with likely-wrong names: review and drop" % nfake)
    out["issues"] = issues[:5]
    return out


def render(rep, run_name=""):
    L = ["# List Quality Report", "", "**Run:** %s" % run_name, "**Rows graded:** %d (selected people with an email)" % rep["rows"],
         "**Grade:** %s (%s/100)%s" % (rep["grade"], rep.get("score", 0),
                                     "  INDICATIVE ONLY: fewer than 100 rows" if rep.get("indicative_only") else ""),
         "**Generated:** %s" % rep["generated_at"], "", "## Dimensions", ""]
    for i, d in enumerate(rep["dims"], 1):
        L.append("%d. %-24s %3d/100  %s" % (i, d["name"], d["score"], d["detail"]))
    L += ["", "## Top issues to fix", ""]
    L += ["%d. %s" % (i, t) for i, t in enumerate(rep["issues"], 1)] or ["None."]
    L += ["", "## Pre-send checklist", "", "- [ ] Only MillionVerifier `ok` emails go to the Email tab",
          "- [ ] Catch-all emails wait for a secondary verifier", "- [ ] Deduplicate by email (done automatically in people.csv)",
          "- [ ] Drop role addresses and bad titles", "- [ ] Re-run after any large change; below grade C rebuild instead of sending", ""]
    L += ["Method: port of the 8 checks of list-quality-scorecard (MIT, GrowthEngineX), see lib/quality.py for the adaptations.", ""]
    return "\n".join(L)


def write_report(run, rows=None, brief=None):
    """Compute, write list-quality.md and verify/quality.json, return the report."""
    brief = brief or run.brief()
    rows = rows if rows is not None else peoplemod.rebuild(run, brief)
    flags = {}
    for r in read_csv(run.qdir / "qualified.csv"):
        flags[r["org_id"]] = r.get("flag")
    rep = score(rows, brief, flags)
    f = peoplemod.Files(run)
    atomic_write(f.quality, render(rep, run.dir.name))
    write_json(f.quality_json, rep)
    return rep
